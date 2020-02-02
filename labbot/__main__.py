import slack # Slack connection
import json # For reading the secrets file
import time
import traceback
from modules import genewiz

with open('labbot.secret') as json_secrets:
    secrets = json.load(json_secrets)

# Create slack credentials
slack_client = slack.WebClient(token=secrets['slack']['api_token'])

try:
    while True:
        genewiz.poll(secrets['genewiz']['data'], slack_client)
        time.sleep(60 * 5)
except Exception as e:
    slack_client.chat_postMessage(
            channel='#sequencing',
            text='Script died:',
            blocks=json.dumps([{'type':'section', 'text':
                {'type': 'mrkdwn', 'text':
                    'Script died. Stacktrace:\n```\n{}\n```'.format(
                        traceback.format_exc())}}]))

