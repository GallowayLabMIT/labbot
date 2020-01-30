from bs4 import BeautifulSoup # HTML parsing
import requests # For logging in
import re
import json


def poll(credentials):
    # Login to Genewiz
    session = requests.Session()
    print('Sending login')
    r = session.post('https://clims4.genewiz.com/RegisterAccount/Login',
            data={'LoginName': credentials['username'],
                'Password' : credentials['password'], 'RememberMe': 'true'})
    main_screen = session.get('https://clims4.genewiz.com/CustomerHome/Index') 
    soup = BeautifulSoup(main_screen.text, 'html.parser')

    # Start extracting data
    model_match = re.search("var model = (.*);\W+var totalOrders", main_screen.text)
    orders = json.loads(model_match.group(1))
    print(orders)
