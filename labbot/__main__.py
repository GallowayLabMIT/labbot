import slack # Slack connection
import json # For reading the secrets file
from modules import genewiz

with open('labbot.secret') as json_secrets:
    secrets = json.load(json_secrets)

# Create slack credentials
slack_client = slack.WebClient(token=secrets['slack']['api_token'])

genewiz.poll(secrets['genewiz']['data'], slack_client)
