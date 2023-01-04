import csv
import requests
import json
import subprocess
import tempfile
from pathlib import Path
import time

if __name__ == '__main__':
    with open ('config.json') as f:
        config = json.load(f)
    
    params = {'token': config['token']}
    
    while True:
        time.sleep(1)
        # Try to dequeue an item
        try:
            label_dequeue = json.loads(requests.post(config['base-route'] + '/dequeue', json=params).text)
        except json.decoder.JSONDecodeError:
            print("Failed to decode response. Pausing for 10 seconds...")
            time.sleep(10)
            continue

        if len(label_dequeue) == 0:
            continue

        try:
            requests.post(config['base-route'] + '/update_status', json=(params | {
                'view_id': label_dequeue['external_id'],
                'status_text': 'Generating print file...'
            }))

            with tempfile.TemporaryDirectory() as tempdir:
                temppath = Path(tempdir)

                with (temppath / 'labels.csv').open('w') as csvfile:
                    writer = csv.writer(csvfile)
                    writer.writerows(label_dequeue['labels'])

                subprocess.run([
                    'glabels-3-batch',
                    '-i', str(temppath / 'labels.csv'), 'fourfield_labels.glabels',
                    '-c', str(label_dequeue['label_count']),
                    '-o', str(temppath / 'labels.ps'),
                ], check=True)

                requests.post(config['base-route'] + '/update_status', json=(params | {
                    'view_id': label_dequeue['external_id'],
                    'status_text': 'Sending to Dymo printer...'
                }))

                subprocess.run([
                    'lpr',
                    '-P', 'LabelWriter-450-Turbo', '-o', 'media=Custom.1.90x0.75in',
                    str(temppath / 'labels.ps')
                ], check=True)

                requests.post(config['base-route'] + '/update_status', json=(params | {
                    'view_id': label_dequeue['external_id'],
                    'status_text': 'Done!'
                }))
        except Exception as err:
            # If the view_id exists, try to send our message that way
            if 'external_id' in label_dequeue:
                requests.post(config['base-route'] + '/update_status', json=(params | {
                    'view_id': label_dequeue['external_id'],
                    'status_text': f'ERROR: {str(err)}'
                }))
            time.sleep(10)