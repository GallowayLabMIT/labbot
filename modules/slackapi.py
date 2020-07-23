from multiprocessing import Process
import slack # For connecting to Slack
import uvicorn
from fastapi import Body, FastAPI, Request
from pydantic import BaseModel
from datetime import datetime
import pytz

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

class InteractionPayload(BaseModel):
    type: str
    token: str
    action_ts: str
    team: TeamModel
    user: UserModel
    callback_id: str
    trigger_id: str

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
        "text": "Submit your arrival and depature times"
      },
      "block_id": "section1",
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
      "optional": False
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
          "text": "Use 24-hour time (HH:MM)"
        },
        "multiline": False
      },
      "optional": False
    },
    {
      "type": "input",
      "label": {
        "type": "plain_text",
        "text": "Depature time"
      },
      "element": {
        "type": "plain_text_input",
        "action_id": "depature_time",
        "placeholder": {
          "type": "plain_text",
          "text": "Use 24-hour time (HH:MM)"
        },
        "multiline": False
      },
      "optional": False
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
  "callback_id": "view_identifier_12"
}

@slackapi_app.post("/slack/covid_hours")
async def root(request: Request):
    form_data = await request.form()
    print(form_data)
    payload = InteractionPayload.parse_raw(form_data['payload'])

    now_dt = datetime.now(ETC)
    main_model["blocks"][1]["element"]["initial_date"] = now_dt.strftime('%Y-%m-%d')
    sclient.views_open(
        trigger_id = payload.trigger_id,
        view = main_model)
    
    return {"message": "Hello World"}

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
