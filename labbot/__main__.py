import slack # Slack connection
import json # For reading the secrets file
from modules import genewiz

with open('labbot.secret') as json_secrets:
    secrets = json.load(json_secrets)

genewiz.poll(credentials=secrets['genewiz'])
