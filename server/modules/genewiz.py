from bs4 import BeautifulSoup # HTML parsing
import requests # For logging in
import slack # For connecting to Slack
import re
import json
import tempfile # For creating a temp zipping directory
from zipfile import ZipFile # for creating the zip file
import os       # for file operations
import rsa
import base64

from labbot.module_loader import ModuleLoader

module_config = {}

loader = ModuleLoader()

def register_module(config):
    # Override defaults if present 
    module_config.update(config)

    if 'username' not in module_config:
        raise RuntimeError("Genewiz username not specified in the config file!")
    if 'password' not in module_config:
        raise RuntimeError("Genewize password not specified in the config file!")

    # Return
    return loader

@loader.timer
def poll(slack_client):
    """
    Given Genewiz login credentials, checks for newly completed
    primers and sequencing orders, and sends Slack messages to
    keep people updated.

    Args:
        credentials: a dictionary including the 'username' and
            'password' keys, set to the valid username/passwords.

    Returns:
        None
    """
    try:
        # Login to Genewiz
        session = requests.Session()
        r = session.get('https://clims4.genewiz.com/RegisterAccount/Login')
        token = re.search(r'<input name="__RequestVerificationToken" type="hidden" value="([^"]*)" />', r.text)
        pubkey = re.search(r"encrypt.setPublicKey\('([^']*)'\);", r.text)
        if token is None or pubkey is None:
            module_config['logger']('Unable to load CSRF token and password pubkey')
            return 5 * 60
        
        pubkey_bytes = rsa.PublicKey.load_pkcs1_openssl_der(base64.b64decode(pubkey.group(1)))
        
        encoded_pass = base64.b64encode(
                        rsa.encrypt(
                            module_config['password'].encode('utf8'),
                            pubkey_bytes
                       ))
        r = session.post('https://clims4.genewiz.com/RegisterAccount/Login',
                data={
                    '__RequestVerificationToken': token.group(1),
                    'LoginName': module_config['username'],
                    'Password' : encoded_pass, 'RememberMe': 'true'})
        main_screen = session.get('https://clims4.genewiz.com/CustomerHome/Index') 

        # Pull out the sequencing requests and oligos
        try:
            sanger_sequencing = _extract_orders(main_screen.text, 'Sanger Sequencing')
            oligos = _extract_orders(main_screen.text, 'Oligo Synthesis')
        except AttributeError as e:
            # Ignore Genewiz page load errors from time to time
            module_config['logger'](f'Failed to extract orders :(\nError: {str(e)}')
            return 5 * 60

        # Extracted saved non-extracted orders

        if not os.path.isfile('pending_genewiz.json'):
            pending_orders = {}
        else:
            with open('pending_genewiz.json') as pending:
                pending_json = pending.read()
                if len(pending_json) == 0:
                    pending_orders = {}
                else:
                    pending_orders = set(json.loads(pending_json))
        
        # Find orders that used to be pending:
        updated_sequences = [seq for seq in sanger_sequencing if
                seq['orderStatus'] == 'Completed' and seq['id'] in pending_orders]

        for sequence in updated_sequences:

            (text_out, zip_filename) = _extract_seq_results(sequence, session)
            try:
                module_config['logger']('Order {} finished! Posting to #sequencing'.format(sequence['id']))
                slack_response = slack_client.chat_postMessage(
                    channel='#sequencing',
                    text='Sequencing results:',
                    blocks=json.dumps([{'type':'section', 'text':
                        {'type': 'mrkdwn', 'text': text_out}}]))

                slack_response = slack_client.files_upload(
                        channels='#sequencing',
                        file=zip_filename,
                        filename=os.path.basename(zip_filename))
                assert slack_response["ok"]
            finally:
                os.remove(zip_filename)
                os.rmdir(os.path.dirname(zip_filename)) # Safe because we created this tempdir

        # Update the pending orders list
        new_pending_orders = [order['id'] for order in (sanger_sequencing + oligos)
                if order['orderStatus'] != 'Completed']
        
        if set(new_pending_orders) != pending_orders:
            module_config['logger']('New order detected. New pending queue:{}'.format(new_pending_orders))
        
        with open('pending_genewiz.json', 'w') as pending:
            json.dump(new_pending_orders, pending)

    except Exception as e:
        module_config['logger'](str(e))
    finally:
        # Reschedule in 5 minutes
        return 5 * 60


def _extract_seq_results(order, session):
    """
    Given an order (full metadata), saves the ABI trace files into a temporary zip file and
    returns some information about the order.

    Args:
        order: a dictionary containing the keys 'id', 'orderType',
            'orderName', and 'orderStatus' representing a certain GeneWiz order.
        session: a Requests session to download files with
    Returns:
        A tuple encoding (string_summary, zip_file_path). String_summary is a
        message fit for a Slack message summarizing the results and zip_file_path
        is a filesystem path to a temporary zip file containing all trace files.
    """
    if order['orderType'] != 'Sanger Sequencing':
        raise RuntimeError('Order is not a Sanger sequencing result')
    if order['orderStatus'] != 'Completed':
        raise RuntimeError('Selected order is not completed!')
    details_html = session.get('https://clims4.genewiz.com/SangerSequencing/ViewResults',
            data={'OrderId': order['id']})

    details_model_match = re.search("window.GWZ.CLIMS.model = (.*);", details_html.text)
    details = json.loads(details_model_match.group(1))

    reaction_list = list(details['OrdersResults'].values())[0]
    
    # Extract each sequencing reaction information
    tempdir = tempfile.mkdtemp()
    ab1_files = []
    names = []
    qualities = []
    lengths = []
    for reaction in reaction_list:
        quality = reaction['QS']
        length = reaction['CRL']
        order_id = order['id']
        sequencer = reaction['Sequencer']
        folder = reaction['ActualPlateFolder']
        file_name = reaction['AB1FileName']
        labwell = '_' + reaction['LabWellFormatted']
        query_string = {'orderId': order_id,
                    'sequencer': sequencer,
                    'folder': folder,
                    'fileName': file_name[:-4] + labwell + '.ab1',
                    'labwell': labwell}

        reaction['SamplePrimerName'] = reaction['SamplePrimerName'].replace('/','--')
        names.append(reaction['SamplePrimerName'])
        qualities.append(quality)
        lengths.append(length)

        ab1_file = session.get('https://clims4.genewiz.com/SangerSequencing/DownloadResult',
                data=query_string)
        # Assert that we actually got an AB1 files
        assert ab1_file.content[0:4] == b'ABIF'

        # Save the file into our temp directory
        new_ab1 = os.path.join(tempdir, reaction['SamplePrimerName'] + '.ab1')
        ab1_files.append(new_ab1)
        with open(new_ab1, 'wb') as outfile:
            outfile.write(ab1_file.content)

    # Zip all files together
    order_name = reaction_list[0]['OrderName']
    if order_name is None:
        order_name = 'no_order_name'
    order_name = order_name.replace('/', '--')
    zip_filename = os.path.join(tempdir, order_name + '.zip')
    with ZipFile(zip_filename, 'w') as outzip:
        for ab1 in ab1_files:
            outzip.write(ab1, arcname = os.path.basename(ab1))

    # Cleanup
    for filename in ab1_files:
        os.remove(filename)

    # Built output string:
    url = '<https://clims4.genewiz.com/SangerSequencing/ViewResults?OrderID={}|Sequencing results>'.format(order['id'])
    order_str = 'Order: {}'.format(order_name)
    table = ''
    for tup in zip(names, lengths, qualities):
        table += '\n\t{}: Length {}, quality {}'.format(*tup)
    
    return (order_str + '\n' + url + table, zip_filename)

def _extract_orders(html, order_type=None):
    """
    Given HTML of the main order pages, extracts all orders. Can
    optionally extract orders of a given type.

    Args:
        html: string containing the returned Genewiz main-page.
        type: string containing the type of item to filter based on,
            otherwise None by default

    Returns:
        a list of items (represented as dictionaries)
    """
    # Start extracting data
    model_match = re.search("var model = (.*);\W+var totalOrders", html)

    # Load all order data
    orders = json.loads(model_match.group(1))

    if order_type is None:
        return orders

    return [order for order in orders
            if order['orderType'] == order_type]
