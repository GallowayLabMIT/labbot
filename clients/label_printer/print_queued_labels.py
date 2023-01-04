import requests
import json
import subprocess
import sys
import time

if __name__ == '__main__':
    with open ('config.json') as f:
        config = json.load(f)
    
    params = {'token': config['token']}
    
    while True:
        time.sleep(1)
        # Try to dequeue an item
        label_dequeue = json.loads(requests.post(config['base-route'] + '/dequeue', data=params).text)
        print(label_dequeue)