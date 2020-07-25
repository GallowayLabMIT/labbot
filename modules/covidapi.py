from multiprocessing import Process
import slack # For connecting to Slack
import uvicorn
from fastapi import Body, FastAPI, Request
from pydantic import BaseModel
from datetime import datetime
from typing import Optional, List
import json
import pytz
import re

ETC = pytz.timezone('America/New_York')

class TeamModel(BaseModel):
    id: str
    domain: str
    enterprise_id: str
    enterprise_name: str

class UserModel(BaseModel):
    id: str
    username: str
    team_id: str

class ShortcutPayload(BaseModel):
    type: str
    token: str
    action_ts: str
    team: TeamModel
    user: UserModel
    callback_id: str
    trigger_id: str

class ContainerModel(BaseModel):
    type: str
    view_id: str

class ViewModel(BaseModel):
    id: str
    team_id: str
    type: str
    blocks: list
    private_metadata: Optional[str] = ''
    callback_id: str
    state: dict
    hash: str
    title: dict
    clear_on_close: bool
    notify_on_close: bool
    close: Optional[dict] = None
    submit: Optional[dict] = None

class ActionModel(BaseModel):
    action_id: str
    block_id: str
    text: dict
    value: str
    type: str
    action_ts: str

class BlockActionPayload(BaseModel):
    type: str
    user: UserModel
    api_app_id: str
    token: str
    container: ContainerModel
    trigger_id: str
    team: TeamModel
    view: ViewModel
    actions: List[ActionModel]

class ViewSubmissionPayload(BaseModel):
    type: str
    team: TeamModel
    user: UserModel
    api_app_id: str
    token: str
    trigger_id: str
    view: ViewModel
    response_urls: list

slackapi_app = FastAPI()
sclient = None

main_model = {
  "type": "modal",
  "title": {
    "type": "plain_text",
    "text": "COVID hour tracking"
  },
    "blocks": [
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": "Submit your lab arrival and depature times:"
            },
            "block_id": "header_section"
        },
        {
            "type": "divider"
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": "This week you have used *15* out of *25* hours.\nAll lab members have used *15* out of *150* hours."
            },
            "accessory": {
                "type": "button",
                "text": {
                    "type": "plain_text",
                    "text": "View your submissions"
                },
                "value": "view_submissions_button",
                "action_id": "view_submissions"
            },
            "block_id": "submissions_summary"
        },
        {
            "type": "divider"
        },
        {
            "type": "input",
            "label": {
                "type": "plain_text",
                "text": "Date"
            },
            "element": {
                "type": "datepicker",
                "action_id": "submit_date",
                "initial_date": "2020-01-01"
            },
            "optional": False,
            "block_id": "submit_date_input"
        },
        {
            "type": "input",
            "label": {
                "type": "plain_text",
                "text": "Arrival time"
            },
            "element": {
                "type": "plain_text_input",
                "action_id": "arrival_time",
                "placeholder": {
                    "type": "plain_text",
                    "text": "Use 24-hour time (H:MM or HH:MM)"
                },
                "multiline": False
            },
            "optional": False,
            "block_id": "arrival_time_input"
        },
        {
            "type": "input",
            "label": {
                "type": "plain_text",
                "text": "Departure time"
            },
            "element": {
                "type": "plain_text_input",
                "action_id": "departure_time",
                "placeholder": {
                    "type": "plain_text",
                    "text": "Use 24-hour time (H:MM or HH:MM)"
                },
                "multiline": False
            },
            "optional": False,
            "block_id": "departure_time_input"
        }
    ],
  "close": {
    "type": "plain_text",
    "text": "Cancel"
  },
  "submit": {
    "type": "plain_text",
    "text": "Submit hours"
  },
  "private_metadata": "Shhhhhhhh",
  "callback_id": "covid_hour_track_submission"
}

submissions_model = {
	"type": "modal",
	"title": {
		"type": "plain_text",
		"text": "Submitted hours"
	},
	"close": {
		"type": "plain_text",
		"text": "Close"
	},
	"blocks": [
		{
			"type": "section",
			"text": {
				"type": "mrkdwn",
				"text": "For the week of *July 15* to *July 27*, you have submitted *25.4* hours:"
			}
		},
		{
			"type": "divider"
		},
		{
			"type": "section",
			"text": {
				"type": "mrkdwn",
				"text": "*7/25*: 9:30 to 11:30"
			}
		}
	]
}

@slackapi_app.post("/slack/covid_hours")
async def root(request: Request):
    form_data = await request.form()
    print(json.loads(form_data['payload']))
    payload_raw = json.loads(form_data['payload'])
    if payload_raw['type'] == 'shortcut':
        payload = ShortcutPayload.parse_raw(form_data['payload'])

        # Update the main model
        now_dt = datetime.now(ETC)
        main_model["blocks"][4]["element"]["initial_date"] = now_dt.strftime('%Y-%m-%d')
        sclient.views_open(
            trigger_id = payload.trigger_id,
            view = main_model)
    elif payload_raw['type'] == 'block_actions':
        payload = BlockActionPayload.parse_raw(form_data['payload'])

        if len(payload.actions) > 0:
            action = payload.actions[0]
            # Load the detailed submissions model if required
            if action.action_id == 'view_submissions':
                sclient.views_push(
                    trigger_id = payload.trigger_id,
                    view = submissions_model)
    elif payload_raw['type'] == 'view_submission':
        # We received a submission on the covid hour tracking modal.
        payload = ViewSubmissionPayload.parse_raw(form_data['payload'])
        form_values = payload.view.state['values']

        # Perform validiation on  the times
        time_regex = '^([01]?[0-9]|2[0-3]):([0-5][0-9])$'
        arrival = re.match(time_regex, form_values['arrival_time_input']['arrival_time']['value'])
        departure = re.match(time_regex, form_values['departure_time_input']['departure_time']['value'])

        errors = {}
        if arrival is None:
            errors['arrival_time_input'] = 'You must enter arrival time in the 24-hour format (H:MM or HH:MM)'
        if departure is None:
            errors['departure_time_input'] = 'You must enter departure time in the 24-hour format (H:MM or HH:MM)'

        if arrival is not None and departure is not None:
            arrival_time = int(arrival.group(1)) + float(arrival.group(2)) / 60
            departure_time = int(departure.group(1)) + float(departure.group(2)) / 60

            if departure_time < arrival_time:
                error_msg = 'Departure time must be later than arrival time! '
                if departure_time < 4:
                    error_msg += 'To submit hours crossing midnight, please submit as two'
                    error_msg += ' separate time intervals for each day'
                errors['departure_time_input'] = error_msg
        if len(errors) > 0:
            return {
                "response_action": "errors",
                "errors": errors}
    return

proc = None

def run(port):
    """
    Run the uvicorn server
    """
    uvicorn.run(app=slackapi_app, host='localhost', port=port)

def start(slack_client, port):
    """
    Spawn a new process for the server
    """
    global proc
    global sclient
    sclient = slack_client
    proc = Process(target=run, args=(port,), daemon=True)
    proc.start()

def stop():
    """
    Join the server after closing
    """
    global proc
    if proc:
        proc.join(0.25)
