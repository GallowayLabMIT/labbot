import slack # Slack connection
import slack_bolt
import json # For reading the secrets file
import contextlib
import time
import threading
import uvicorn
import time
import traceback
from modules import genewiz, covidapi

import googleapiclient.discovery
import google_auth_oauthlib.flow
import google.auth.transport.requests

class WebServer(uvicorn.Server):
    def install_signal_handlers(self):
        pass # Use default signal handlers

    @contextlib.contextmanager
    def run_in_thread(self):
        thread = threading.Thread(target=self.run)
        thread.start()
        try:
            while not self.started:
                time.sleep(1e-3)
            yield
        finally:
            self.should_exit = True
            thread.join()

with open('labbot.secret') as json_secrets:
    secrets = json.load(json_secrets)

# Start by loading Google credentials
#GAPI_SCOPES = ['https://www.googleapis.com/auth/spreadsheets']
#google_flow = google_auth_oauthlib.flow.InstalledAppFlow.from_client_config(secrets['gapi'], GAPI_SCOPES)
#gapi_creds = google_flow.run_local_server(port=0)


# Create slack credentials
bolt_client = slack_bolt.async_app.AsyncApp(
        signing_secret=secrets['slack']['signing_secret'],
        token=secrets['slack']['api_token']
)
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

