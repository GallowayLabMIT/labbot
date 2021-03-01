import requests
import json
import argparse
import subprocess
import sys


parser = argparse.ArgumentParser()
group = parser.add_mutually_exclusive_group()
group.add_argument('--checkin', action='store_true')
group.add_argument('--checkout', action='store_true')
group.add_argument('--auto', action='store_true')

def checkin():
    r = requests.post(config['base-route'] + '/checkin', params=params)
    if r.status_code == 200:
        print('Check-in succeeded!')
    elif r.status_code == 409:
        raise RuntimeError('Check-in failed; license already checked in!')
    else:
        raise RuntimeError(f'Check-in failed: unknown return status:{r.status_code}: {r.text}')

def checkout():
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
    
    args = parser.parse_args()

    if args.checkin:
        checkin()
    elif args.checkout:
        checkout()
    else:
        current_status = json.loads(requests.get(config['base-route'] + '/state', params=params).text)

        if current_status['checked_out']:
            print('Check-out failed; license already checked out!')
            sys.exit(1)

        checkout()
        subprocess.run(config['flowjo-executable'])
        checkin() 
    
