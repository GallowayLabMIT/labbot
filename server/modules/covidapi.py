from datetime import datetime, timedelta
from labbot.module_loader import ModuleLoader
import json
from collections import namedtuple
import pytz
import re
import csv
import pathlib

ETC = pytz.timezone('America/New_York')

# -- Module loading --

# Set defaults if they make sense here. Do not store secrets directly in code!
module_config = {'hours_per_week': 20, 'lab_members': 5}

loader = ModuleLoader()

def register_module(config):
    # Override defaults if present 
    module_config.update(config)

    # Return
    return loader

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
                "action_id": "view_covid_submissions"
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

# -- Slack functions --

@loader.slack.shortcut("track_hours")
def main_tracker(ack, shortcut, client):
    """
    Handles when a user requests to open the track hours form
    """
    ack()

    # Check the existing covid CSV file
    check_covid_file_existence('covid_hours.csv')
    hour_results = parse_csv('covid_hours.csv')
    now_dt = datetime.now(ETC)
    current_week = now_dt + timedelta(days=-now_dt.weekday())


    # Update the main model
    now_dt = datetime.now(ETC)
    main_model["blocks"][4]["element"]["initial_date"] = now_dt.strftime('%Y-%m-%d')

    hour_summary = summarize_hour_results(hour_results, current_week, shortcut['user']['username'])
    main_model["blocks"][2]["text"]["text"] = "This week you have used *{:.1f}* out of *{:.1f}* hours.\nAll lab members have used *{:.1f}* out of *{:.1f}* hours.".format(
            hour_summary[0],
            module_config['hours_per_week'],
            hour_summary[1],
            module_config['hours_per_week'] * module_config['lab_members'])
    client.views_open(
        trigger_id = shortcut['trigger_id'],
        view = main_model)

@loader.slack.action("view_covid_submissions")
def show_detailed_hours(ack, body, client):
    """
    Displays the detailed hours summary for the last week.
    """
    ack()

    # Check the existing covid CSV file
    check_covid_file_existence('covid_hours.csv')
    hour_results = parse_csv('covid_hours.csv')
    now_dt = datetime.now(ETC)
    current_week = now_dt + timedelta(days=-now_dt.weekday())

    hour_summary = summarize_hour_results(hour_results, current_week, body['user']['username'])
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

    print(hour_summary)
    client.views_push(
        trigger_id = body['trigger_id'],
        view = submissions_model)

@loader.slack.view('covid_hour_track_submission')
def handle_form_submission(ack, body, client, view):
    """
    Handles what happens when the track submission form gets submitted
    """
    # Perform validiation on the times before ack'ing
    form_state = view['state']['values']
    time_regex = '^([01]?[0-9]|2[0-3]):([0-5][0-9])$'
    arrival = re.match(time_regex, form_state['arrival_time_input']['arrival_time']['value'])
    departure = re.match(time_regex, form_state['departure_time_input']['departure_time']['value'])

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
        ack(response_actions='errors', errors=errors)
        return
    # Otherwise we are good; ack to close the form
    ack()
    
    # Otherwise, add row
    day = form_state['submit_date_input']['submit_date']['selected_date']
    arrival = form_state['arrival_time_input']['arrival_time']['value']
    departure = form_state['departure_time_input']['departure_time']['value']
    add_row('covid_hours.csv',
            body['user']['username'],
            day,
            arrival,
            departure)

    duration = datetime.strptime(departure, '%H:%M') - datetime.strptime(arrival, '%H:%M')
    client.chat_postMessage(
        channel=body['user']['id'],
        text='{:.1f} hours submitted successfully for {}, from {} to {}'.format(
            duration.total_seconds() / 3600.0,
            datetime.strptime(day, '%Y-%m-%d').strftime('%B %d'),
            arrival, departure),
        user=body['user']['id'])

@loader.slack.shortcut("get_hours_csv")
def csv_export(ack, shortcut, client):
    ack()

    result = client.files_upload(
        channels=shortcut['user']['id'],
        initial_comment='Hours CSV:',
        file='covid_hours.csv')

# -- Helper functions --

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
