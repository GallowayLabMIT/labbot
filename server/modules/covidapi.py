from multiprocessing import Process
import slack # For connecting to Slack
import uvicorn
from fastapi import Body, FastAPI, Request
from pydantic import BaseModel
from datetime import datetime, timedelta
from typing import Optional, List
import json
import pytz
import re
import csv
import pathlib

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


@slackapi_app.post("/slack/covid_hours")
async def root(request: Request):
    form_data = await request.form()

    check_covid_file_existence('covid_hours.csv')
    hour_results = parse_csv('covid_hours.csv')
    now_dt = datetime.now(ETC)
    current_week = now_dt + timedelta(days=-now_dt.weekday())

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
                    "text": "Submit your lab arrival and depature times!"
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
                    "text": ""
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
                                    "text": " "
                            }
                    },
                    {
                            "type": "divider"
                    },
                    {
                            "type": "section",
                            "text": {
                                    "type": "mrkdwn",
                                    "text": " "
                            }
                    }
            ]
    }


    print(json.loads(form_data['payload']))
    payload_raw = json.loads(form_data['payload'])
    if payload_raw['type'] == 'shortcut':
        payload = ShortcutPayload.parse_raw(form_data['payload'])

        if payload.callback_id == 'track_hours':
            # Update the main model
            now_dt = datetime.now(ETC)
            main_model["blocks"][4]["element"]["initial_date"] = now_dt.strftime('%Y-%m-%d')

            hour_summary = summarize_hour_results(hour_results, current_week, payload.user.username)
            main_model["blocks"][2]["text"]["text"] = "This week you have used *{:.1f}* out of *{:.1f}* hours.\nAll lab members have used *{:.1f}* out of *{:.1f}* hours.".format(
                    hour_summary[0], hours_per_week, hour_summary[1], hours_per_week * lab_members)
            sclient.views_open(
                trigger_id = payload.trigger_id,
                view = main_model)
            return {}
        elif payload.callback_id == 'get_hours_csv':
            # Send a message to the requester
            with open('covid_hours.csv') as covidfile:
                csv_text = covidfile.read()
            sclient.chat_postMessage(
                channel=payload.user.id,
                text='Hours CSV:',
                blocks=json.dumps([{'type':'section', 'text':
                    {'type': 'mrkdwn', 'text': '```{}```'.format(csv_text)}}]))
            return {}


    elif payload_raw['type'] == 'block_actions':
        payload = BlockActionPayload.parse_raw(form_data['payload'])

        if len(payload.actions) > 0:
            action = payload.actions[0]
            # Load the detailed submissions model if required
            if action.action_id == 'view_submissions':
                hour_summary = summarize_hour_results(hour_results, current_week, payload.user.username)
                submissions_model["blocks"][0]["text"]["text"] = "For the week of *{}* to *{}*, you have submitted *{:.1f}* hours:".format(
                        current_week.strftime("%B %d"),
                        (current_week + timedelta(days=6)).strftime("%B %d"),
                        hour_summary[0])
                submissions_model["blocks"][2]["text"]["text"] = ' \n' + '\n'.join([
                        "*{}*: {} to {}".format(
                            val[0].strftime("%B %d"),
                            val[1].strftime("%k:%M"),
                            val[2].strftime("%k:%M")) for val in 
                        hour_summary[2]])

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
        
        # Otherwise, add row
        day = form_values['submit_date_input']['submit_date']['selected_date']
        arrival = form_values['arrival_time_input']['arrival_time']['value']
        departure = form_values['departure_time_input']['departure_time']['value']
        add_row('covid_hours.csv',
                payload.user.username,
                day,
                arrival,
                departure)

        print(departure)
        print(arrival)
        duration = datetime.strptime(departure, '%H:%M') - datetime.strptime(arrival, '%H:%M')
        print(duration)
        sclient.chat_postMessage(
            channel=payload.user.id,
            text='{:.1f} hours submitted successfully for {}, from {} to {}'.format(
                duration.total_seconds() / 3600.0,
                datetime.strptime(day, '%Y-%m-%d').strftime('%B %d'),
                arrival, departure),
            user=payload.user.id)

        return {
            "response_action": "clear"}
    return {}


def parse_csv(filename):
    results = {}
    # The Monday date is the current week
    with open(filename) as covid_file:
        reader = csv.DictReader(covid_file)
        for row in reader:
            week = datetime.strptime(row['week'], '%Y-%m-%d')
            day = datetime.strptime(row['day'], '%Y-%m-%d')
            arrival_time = datetime.strptime(row['arrival_time'], '%H:%M')
            departure_time = datetime.strptime(row['departure_time'], '%H:%M')

            if row['user'] not in results:
                results[row['user']] = {}

            week_str = week.strftime('%Y-%m-%d')
            if week_str not in results[row['user']]:
                results[row['user']][week_str] = {'total_time': 0.0, 'instances': []}

            results[row['user']][week_str]['instances'].append(
                    [day, arrival_time, departure_time])
            results[row['user']][week_str]['total_time'] += (departure_time - arrival_time).total_seconds()
    return results

def summarize_hour_results(results, week, username):
    user_results = 0
    all_results = 0
    instances = []

    week_str = week.strftime('%Y-%m-%d')

    print(results)
    for user, results in results.items():
        if week_str in results:
            all_results += results[week_str]['total_time']

            if user == username:
                user_results += results[week_str]['total_time']
                instances = results[week_str]['instances']

    user_results /= 3600
    all_results /= 3600
    return (user_results, all_results, instances)

def check_covid_file_existence(filename):
    if not pathlib.Path(filename).exists():
        with open(filename, 'w') as covid_file:
            covid_file.write('user,week,day,arrival_time,departure_time\n')

def add_row(filename, user, day, arrival, departure):
    day_dt = datetime.strptime(day, '%Y-%m-%d')
    week = day_dt + timedelta(days=-day_dt.weekday())
    with open(filename, 'a') as covid_file:
        covid_file.write('{},{},{},{},{}\n'.format(
            user,
            week.strftime('%Y-%m-%d'),
            day,
            arrival,
            departure))

proc = None
hours_per_week = None
lab_members = None

def run(port):
    """
    Run the uvicorn server
    """
    uvicorn.run(app=slackapi_app, host='localhost', port=port)

def start(slack_client, port, hours, members):
    """
    Spawn a new process for the server
    """
    global proc
    global sclient
    global hours_per_week
    global lab_members
    hours_per_week = hours
    lab_members = members
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
