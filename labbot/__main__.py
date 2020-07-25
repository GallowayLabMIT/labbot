import slack # Slack connection
import json # For reading the secrets file
import time
import traceback
from modules import genewiz, covidapi

import googleapiclient.discovery
import google_auth_oauthlib.flow
import google.auth.transport.requests

with open('labbot.secret') as json_secrets:
    secrets = json.load(json_secrets)

# Start by loading Google credentials
#GAPI_SCOPES = ['https://www.googleapis.com/auth/spreadsheets']
#google_flow = google_auth_oauthlib.flow.InstalledAppFlow.from_client_config(secrets['gapi'], GAPI_SCOPES)
#gapi_creds = google_flow.run_local_server(port=0)


# Create slack credentials
slack_client = slack.WebClient(token=secrets['slack']['api_token'])

# Launch COVID API
covidapi.start(slack_client,
               secrets['slackapi']['port'],
               secrets['slackapi']['hours_per_week'],
               secrets['slackapi']['lab_members'])

while True:
    try:
        genewiz.poll(secrets['genewiz']['data'], slack_client)
    except Exception as e:
        slack_client.chat_postMessage(
                channel='#labbot_debug',
                text='Script died:',
                blocks=json.dumps([{'type':'section', 'text':
                    {'type': 'mrkdwn', 'text':
                        'Script died. Stacktrace:\n```\n{}\n```'.format(
                            traceback.format_exc())}}]))
    time.sleep(60 * 5)

