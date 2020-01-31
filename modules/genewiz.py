from bs4 import BeautifulSoup # HTML parsing
import requests # For logging in
import re
import json


def poll(credentials):
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
    # Login to Genewiz
    session = requests.Session()
    print('Sending login')
    r = session.post('https://clims4.genewiz.com/RegisterAccount/Login',
            data={'LoginName': credentials['username'],
                'Password' : credentials['password'], 'RememberMe': 'true'})
    main_screen = session.get('https://clims4.genewiz.com/CustomerHome/Index') 
    #soup = BeautifulSoup(main_screen.text, 'html.parser')

    # Pull out the sequencing requests and oligos
    sanger_sequencing = _extract_orders(main_screen.text, 'Sanger Sequencing')
    oligos = _extract_orders(main_screen.text, 'Oligo Synthesis')

    # For order page, window.GWZ.CLIMS.model
    _extract_oligo_results([seq for seq in sanger_sequencing if seq['orderStatus'] == 'Completed'][0],
            session)

def _extract_oligo_results(order, session):
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
    for reaction in reaction_list:
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
        abi_file = session.get('https://clims4.genewiz.com/SangerSequencing/DownloadResult',
                data=query_string)
        with open(reaction['SamplePrimerName'] + '.ab1', 'wb') as outfile:
            outfile.write(abi_file.content)

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
