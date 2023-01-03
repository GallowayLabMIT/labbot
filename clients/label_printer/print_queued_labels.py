import requests
import json
import argparse
import subprocess
import sys
import time


def dequeue(config):
    r = requests.post(config['base-route'] + '/checkin', =params)
    if r.status_code == 200:
        print('Check-in succeeded!')
    elif r.status_code == 409:
        raise RuntimeError('Check-in failed; license already checked in!')
    else:
        raise RuntimeError(f'Check-in failed: unknown return status:{r.status_code}: {r.text}')

def update_status():
    r = requests.post(config['base-route'] + '/checkout', params=params)
    if r.status_code == 200:
        print('Check-out succeeded!')
    elif r.status_code == 409:
        raise RuntimeError('Check-out failed; license already checked out!')
    else:
        raise RuntimeError(f'Check-out failed; Unknown return status:{r.status_code}: {r.text}')


if __name__ == '__main__':
    with open ('config.json') as f:
        config = json.load(f)
    
    params = {'token': config['token']}
    
    while True:
        time.sleep(1)
        # Try to dequeue an item
        label_dequeue = json.loads(requests.post(config['base-route'] + '/dequeue', data=params).text)