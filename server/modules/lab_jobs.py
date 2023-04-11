"""
Module that tracks lab jobs.
"""
import traceback
from labbot.module_loader import ModuleLoader
import fastapi 
from pydantic import BaseModel
import typing
import sqlite3
import secrets
import datetime
import collections
import copy
from pytz import timezone
from dateutil import rrule
from durations import Duration
import functools
import time

from typing import Callable, Dict, List

ET = timezone('US/Eastern')

REMINDER_MESSAGE = [
    {
        "type": "section",
        "text": {
            "type": "mrkdwn",
            "text": "Lab job: {job_name}\n<!date^{due_ts}^Due {{date_long_pretty}}|{fallback_ts}>\n_If you are unable to do your job this time, reassign it to someone who can after confirming with them_"
        }
    },
    {
        "type": "actions",
        "elements": [
            {
                "type": "button",
                "text": {
                    "type": "plain_text",
                    "text": ":white_check_mark: I did this job",
                    "emoji": True
                },
                "value": "{job_id}",
                "action_id": "labjob-complete"
            },
            {
                "type": "button",
                "text": {
                    "type": "plain_text",
                    "text": ":recycle: Reassign this instance",
                    "emoji": True
                },
                "value": "{job_id}",
                "action_id": "labjob-reassign"
            }
        ]
    }
]

REMINDER_COMPLETE_MESSAGE = [
    {
        "type": "section",
        "text": {
            "type": "mrkdwn",
            "text": "Lab job: {job_name} complete!"
        }
    }
]

REMINDER_REASSIGNED_MESSAGE = [
    {
        "type": "section",
        "text": {
            "type": "mrkdwn",
            "text": "Lab job: {job_name} reassigned to <@{assignee}>"
        }
    }
]

def build_reminder_message(job_id: int, job_name: str, due: datetime.datetime):
    message = copy.deepcopy(REMINDER_MESSAGE)
    message[0]['text']['text'] = message[0]['text']['text'].format(
        job_name=job_name,
        due_ts=int(due.timestamp()),
        fallback_ts=f'Due {due.isoformat()}'
    )
    message[1]['elements'][0]['value'] = str(job_id)
    message[1]['elements'][1]['value'] = str(job_id)
    return message

def build_completed_message(job_name: str, due: datetime.datetime):
    message = copy.deepcopy(REMINDER_COMPLETE_MESSAGE)
    message[0]['text']['text'] = message[0]['text']['text'].format(
        job_name=job_name, due_ts=int(due.timestamp()), fallback_ts=f'Due {due.isoformat()}'
    )
    return message

def build_reassigned_message(job_name: str, assignee: str):
    message = copy.deepcopy(REMINDER_REASSIGNED_MESSAGE)
    message[0]['text']['text'] = message[0]['text']['text'].format(
        job_name=job_name, assignee=assignee
    )
    return message

REASSIGN_MODAL = {
    "type": "modal",
    "callback_id": "labjob-reassign-modal",
    "title": {
        "type": "plain_text",
        "text": "Reassign lab job",
        "emoji": True
    },
    "submit": {
        "type": "plain_text",
        "text": "Submit",
        "emoji": True
    },
    "close": {
        "type": "plain_text",
        "text": "Cancel",
        "emoji": True
    },
    "blocks": [
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": "{lab_job}\n<!date^{due_ts}^Posted {{date_long_pretty}}|{fallback_ts}>"
            }
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": "_If you want to permanently reassign this job, go to the Labbot home page._"
            }
        },
        {
            "type": "section",
            "block_id": "userselect",
            "text": {
                "type": "mrkdwn",
                "text": "Reassign this occurrence to:"
            },
            "accessory": {
                "type": "users_select",
                "placeholder": {
                    "type": "plain_text",
                    "text": "Select a user",
                    "emoji": True
                },
                "action_id": "userselectval"
            }
        }
    ]
}

def build_reassign_modal(job_id: int, job_name: str, due: datetime.datetime):
    modal = copy.deepcopy(REASSIGN_MODAL)
    modal['blocks'][0]['text']['text'] = modal['blocks'][0]['text']['text'].format(
        lab_job=job_name,
        due_ts=due.timestamp(),
        fallback_ts=f'Due {due.isoformat()}'
    )
    modal['private_metadata'] = str(job_id)
    return modal

VIEW_REMINDER_SCHEDULE_MODAL = {
    "type": "modal",
    "title": {
        "type": "plain_text",
        "text": "View reminder schedules",
        "emoji": True
    },
    "close": {
        "type": "plain_text",
        "text": "Done",
        "emoji": True
    },
    "clear_on_close": True,
    "blocks": [
        {
            "type": "actions",
            "elements": [
                {
                    "type": "button",
                    "text": {
                        "type": "plain_text",
                        "text": "Add reminder schedule"
                    },
                    "action_id": "reminder_schedule-add"
                }
            ]
        }
    ]
}

def build_reminder_schedule_modal(db_con: sqlite3.Connection):
    """Returns the list of reminder schedules"""

    view_modal = copy.deepcopy(VIEW_REMINDER_SCHEDULE_MODAL)
    schedules = db_con.execute("SELECT id, name FROM reminder_schedules").fetchall()
    view_modal['blocks'] = [
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": schedule['name']
            },
            "accessory": {
                "type": "button",
                "text": {
                    "type": "plain_text",
                    "text": "Edit",
                    "emoji": True
                },
                "value": f"{schedule['id']}",
                "action_id": "reminder_schedule-edit"
            }
        } for schedule in schedules
    ] + view_modal['blocks']
    return view_modal

VIEW_JOBS_MODAL = {
    "type": "modal",
    "title": {
        "type": "plain_text",
        "text": "View jobs",
        "emoji": True
    },
    "close": {
        "type": "plain_text",
        "text": "Done",
        "emoji": True
    },
    "clear_on_close": True,
    "blocks": [
        {
            "type": "actions",
            "elements": [
                {
                    "type": "button",
                    "text": {
                        "type": "plain_text",
                        "text": "Add job",
                        "emoji": True
                    },
                    "action_id": "labjob-add"
                }
            ]
        }
    ]
}

def build_view_jobs_modal(db_con: sqlite3.Connection):
    """Returns the list of jobs with edit links"""

    view_modal = copy.deepcopy(VIEW_JOBS_MODAL)

    jobs = db_con.execute("""
        SELECT template_jobs.id, template_jobs.name, template_jobs.assignee, reminder_schedules.name AS reminder_name
        FROM template_jobs LEFT JOIN reminder_schedules ON template_jobs.reminder_schedule=reminder_schedules.id
        """
    ).fetchall()
    view_modal['blocks'] = [
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"{job['name']} ({job['reminder_name']} by <@{job['assignee']}>)"
            },
            "accessory": {
                "type": "button",
                "text": {
                    "type": "plain_text",
                    "text": "Edit",
                    "emoji": True
                },
                "value": f"{job['id']}",
                "action_id": "labjob-edit"
            }
        } for job in jobs
    ] + view_modal['blocks']
    return view_modal

EDIT_JOB_MODAL = {
    "callback_id": "labjob-edit-modal",
    "title": {
        "type": "plain_text",
        "text": "Edit job"
    },
    "submit": {
        "type": "plain_text",
        "text": "Done"
    },
    "close": {
        "type": "plain_text",
        "text": "Cancel",
    },
    "type": "modal",
    "blocks": [
        {
            "type": "input",
            "block_id": "labjob-name",
            "element": {
                "type": "plain_text_input",
                "action_id": "labjob-nameval",
                "placeholder": {
                    "type": "plain_text",
                    "text": "Enter something. Markdown allowed."
                }
            },
            "label": {
                "type": "plain_text",
                "text": "Job description"
            }
        },
        {
            "type": "section",
            "block_id": "labjob-assignee",
            "text": {
                "type": "mrkdwn",
                "text": "*Assignee*"
            },
            "accessory": {
                "type": "users_select",
                "placeholder": {
                    "type": "plain_text",
                    "text": "Select a user"
                },
                "action_id": "labjob-assigneeval"
            }
        },
        {
            "type": "input",
            "block_id": "labjob-sort_priority",
            "element": {
                "type": "number_input",
                "is_decimal_allowed": True,
                "action_id": "labjob-sort_priorityval"
            },
            "label": {
                "type": "plain_text",
                "text": "Sort priority"
            }
        },
        {
            "type": "section",
            "block_id": "labjob-reminder_schedule",
            "text": {
                "type": "mrkdwn",
                "text": "*Reminder schedule*"
            },
            "accessory": {
                "type": "static_select",
                "placeholder": {
                    "type": "plain_text",
                    "text": "Select a reminder schedule"
                },
                "options": [],
                "action_id": "labjob-reminder_scheduleval"
            }
        },
        {
            "type": "divider"
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": "*Scheduling*\nPick a schedule for this lab job. You can effectively do anything that e.g. Google Calendar lets you do. I don't have a good GUI, so just use a <https://icalendar.org/rrule-tool.html|RRULE editor> to generate more complicated schedules. The default is weekly on Monday."
            }
        },
        {
            "type": "input",
            "block_id": "labjob-recurrence",
            "element": {
                "type": "plain_text_input",
                "action_id": "labjob-recurrenceval",
                "initial_value": "FREQ=WEEKLY;INTERVAL=1;BYDAY=MO"
            },
            "label": {
                "type": "plain_text",
                "text": "RRULE recurrence rule"
            }
        },
        {
            "type": "actions",
            "elements": [
                {
                    "type": "button",
                    "text": {
                        "type": "plain_text",
                        "text": "Delete lab job",
                    },
                    "style": "danger",
                    "value": "",
                    "action_id": "labjob-delete",
                    "confirm": {
                        "title": {
                            "type": "plain_text",
                            "text": "Are you sure?"
                        },
                        "text": {
                            "type": "plain_text",
                            "text": "This will delete future instances of this lab job."
                        },
                        "confirm": {
                            "type": "plain_text",
                            "text": "Delete lab job"
                        },
                        "deny": {
                            "type": "plain_text",
                            "text": "Cancel"
                        }
                    }
                }
            ]
        }
    ]
}

def build_edit_job_modal(db_con: sqlite3.Connection, job_id: int, prev_view: str):
    """Returns the edit job modal"""

    edit_modal = copy.deepcopy(EDIT_JOB_MODAL)

    job = db_con.execute("SELECT name, sort_priority, reminder_schedule, recurrence, assignee FROM template_jobs WHERE id=? ORDER BY sort_priority", (job_id,)).fetchone()
    schedules = db_con.execute("SELECT id, name FROM reminder_schedules").fetchall()
    schedule_option_map = {schedule['id']: {
        "text": {
            "type": "plain_text",
            "text": schedule['name']
        },
        "value": f"{schedule['id']}"
        } for schedule in schedules
    }
    
    edit_modal['blocks'][0]['element']['initial_value'] = job['name']
    if job['assignee'] is not None:
        edit_modal['blocks'][1]['accessory']['initial_user'] = job['assignee']
    edit_modal['blocks'][2]['element']['initial_value'] = str(job['sort_priority'])
    # Fill in reminder schedule options
    edit_modal['blocks'][3]['accessory']['options'] = list(schedule_option_map.values())
    if job['reminder_schedule'] is not None:
        edit_modal['blocks'][3]['accessory']['initial_option'] = schedule_option_map[job['reminder_schedule']]
    
    edit_modal['blocks'][6]['element']['initial_value'] = job['recurrence']
    edit_modal['blocks'][7]['elements'][0]['value'] = str(job_id)

    edit_modal['private_metadata'] = f'{job_id};{prev_view}'
    return edit_modal

EDIT_REMINDER_SCHEDULE_MODAL = {
    "callback_id": "reminder_schedule-edit-modal",
    "title": {
        "type": "plain_text",
        "text": "Edit reminder schedule",
    },
    "submit": {
        "type": "plain_text",
        "text": "Done",
    },
    "close": {
        "type": "plain_text",
        "text": "Cancel",
    },
    "type": "modal",
    "blocks": [
        {
            "type": "input",
            "block_id": "reminder_schedule-name",
            "element": {
                "type": "plain_text_input",
                "action_id": "reminder_schedule-nameval",
                "placeholder": {
                    "type": "plain_text",
                    "text": "Enter a short description"
                }
            },
            "label": {
                "type": "plain_text",
                "text": "Reminder schedule name",
            }
        },
        {
            "type": "divider"
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": "Specify a schedule as a series of `delay_time=reminder_time` entries, separated by semicolons. For example, ```0s=1d; 2d=12h; 4d=4h; 1w=1h``` means that after zero seconds (e.g. immediately), reminders are sent every day. After two days, reminders are sent every 12 hours. After four days, reminders are sent every four hours, and so on."
            }
        },
        {
            "type": "input",
            "block_id": "reminder_schedule-schedule",
            "element": {
                "type": "plain_text_input",
                "action_id": "reminder_schedule-scheduleval"
            },
            "label": {
                "type": "plain_text",
                "text": "Reminder schedule",
            }
        },
        {
            "type": "actions",
            "elements": [
                {
                    "type": "button",
                    "text": {
                        "type": "plain_text",
                        "text": "Delete reminder schedule",
                    },
                    "style": "danger",
                    "value": "",
                    "action_id": "reminder_schedule-delete",
                    "confirm": {
                        "title": {
                            "type": "plain_text",
                            "text": "Are you sure?"
                        },
                        "text": {
                            "type": "plain_text",
                            "text": "This will stop reminders for any lab jobs using this schedule!"
                        },
                        "confirm": {
                            "type": "plain_text",
                            "text": "Delete reminder schedule"
                        },
                        "deny": {
                            "type": "plain_text",
                            "text": "Cancel"
                        }
                    }
                }
            ]
        }
    ]
}

def build_edit_reminder_schedule_modal(db_con: sqlite3.Connection, reminder_schedule_id: int, source_view: str):
    """Returns the edit job modal"""

    edit_modal = copy.deepcopy(EDIT_REMINDER_SCHEDULE_MODAL)

    schedule = db_con.execute("SELECT id, name, reminders FROM reminder_schedules WHERE id=?", (reminder_schedule_id,)).fetchone()
    
    edit_modal['blocks'][0]['element']['initial_value'] = schedule['name']
    edit_modal['blocks'][3]['element']['initial_value'] = schedule['reminders']
    edit_modal['blocks'][4]['elements'][0]['value'] = str(reminder_schedule_id)
    edit_modal['private_metadata'] = f'{reminder_schedule_id};{source_view}'
    return edit_modal

JOB_HOME = [
    {
        "type": "header",
        "text": {
            "type": "plain_text",
            "text": "Lab jobs"
        }
    },
    {
        "type": "section",
        "text": {
            "type": "mrkdwn",
            "text": "There are currently {num_jobs} lab jobs defined."
        }
    },
    {
        "type": "actions",
        "elements": [
            {
                "type": "button",
                "text": {
                    "type": "plain_text",
                    "text": "Edit jobs"
                },
                "value": "edit",
                "action_id": "labjob-view"
            },
            {
                "type": "button",
                "text": {
                    "type": "plain_text",
                    "text": "Edit reminder schedules"
                },
                "value": "edit",
                "action_id": "reminder_schedule-view"
            }
        ]
    },
    {
        "type": "section",
        "text": {
            "type": "mrkdwn",
            "text": "No pending lab jobs"
        }
    }
]


module_config = {}

loader = ModuleLoader()

def register_module(config):
    # Override defaults if present 
    module_config.update(config)

    # Init database connection
    db_con = sqlite3.connect('labjobs.db')
    with db_con:
        db_con.execute('''
        CREATE TABLE IF NOT EXISTS reminder_schedules (
            id integer PRIMARY KEY,
            name text NOT NULL,
            reminders text NOT NULL
        )
        ''')
        db_con.execute('''
        CREATE TABLE IF NOT EXISTS template_jobs (
            id integer PRIMARY KEY,
            sort_priority integer NOT NULL,
            name text NOT NULL,
            last_generated_ts text NOT NULL,
            reminder_schedule integer,
            recurrence text NOT NULL,
            assignee tex,
            FOREIGN KEY (reminder_schedule)
                REFERENCES reminder_schedules (id)
        );
        ''')
        db_con.execute('''CREATE INDEX IF NOT EXISTS template_jobs_reminder_schedule_index ON template_jobs (reminder_schedule)''')
        db_con.execute('''CREATE INDEX IF NOT EXISTS template_jobs_sort_index ON template_jobs (sort_priority)''')
        db_con.execute('''
        CREATE TABLE IF NOT EXISTS jobs (
            id integer PRIMARY KEY,
            name text NOT NULL,
            done integer NOT NULL,
            due_ts text NOT NULL,
            last_reminder_ts text NOT NULL,
            reminder_schedule integer,
            assignee text,
            FOREIGN KEY (reminder_schedule)
                REFERENCES reminder_schedules (id)
        );
        ''')
        db_con.execute('''CREATE INDEX IF NOT EXISTS jobs_reminder_schedule_index ON jobs (reminder_schedule)''')
        db_con.execute('''
        CREATE TABLE IF NOT EXISTS reminder_messages (
            job_id integer NOT NULL,
            channel text NOT NULL,
            slack_message_ts text NOT NULL,
            FOREIGN KEY (job_id)
                REFERENCES jobs (id)
        );
        ''')
        db_con.execute('''CREATE INDEX IF NOT EXISTS job_id_slack_index ON reminder_messages (job_id)''')
    db_con.commit()
    db_con.close()
    return loader

def add_new_jobs(db_con:sqlite3.Connection) -> List[int]:
    """
    Using the recurrence rules, adds new lab job reminders. Returns the new job rowids
    """
    now = datetime.datetime.now(ET)
    # Only do the check after 9am
    if now.hour <= 9:
        return []
    today: str = datetime.date.today().isoformat()
    possible_jobs = db_con.execute("SELECT id, name, reminder_schedule, recurrence, assignee, last_generated_ts FROM template_jobs WHERE last_generated_ts<?;", (today,)).fetchall()

    inserted_rows: List[int] = []
    for job in possible_jobs:
        if job['assignee'] is None:
            continue
        # Check the recurrence against today
        next_event: datetime.datetime = rrule.rrulestr(job['recurrence']).after(now.replace(tzinfo=None), inc=True)
        module_config['logger'](f'Next event for {job["name"]}: {next_event.date().isoformat()} with last_ts: {job["last_generated_ts"]}')
        if next_event.date() == now.date():
            # Generate an event
            cur = db_con.execute(
                "INSERT INTO jobs (done, name, due_ts, last_reminder_ts, reminder_schedule, assignee) VALUES (0, ?, ?, ?, ?, ?)",
                (job['name'], now.isoformat(), now.isoformat(), job["reminder_schedule"], job["assignee"])
            )
            if cur.lastrowid is not None:
                inserted_rows.append(cur.lastrowid)
            db_con.execute("UPDATE template_jobs SET last_generated_ts=? WHERE id=?", (today, job['id']))
    return inserted_rows

def get_schedules(db_con:sqlite3.Connection) -> Dict[int, Callable[[datetime.timedelta], datetime.timedelta]]:
    """Gets a mapping between schedule mappings and a lambda function that takes a delta and returns the reminder delta"""
    schedules = db_con.execute("SELECT id, name, reminders FROM reminder_schedules").fetchall()
    results: Dict[int, Callable[[datetime.timedelta], datetime.timedelta]] = {}
    for schedule in schedules:
        # Parse the reminders string
        # This is of the form "<delay>:reminder_duration; <delay2>:reminder_duration2"
        reminder_pairs = [[datetime.timedelta(seconds=Duration(x).to_seconds()) for x in s.split('=')] for s in schedule['reminders'].split(';')]
        # Add an "infinite" delay at time delta zero
        reminder_pairs.append([datetime.timedelta(seconds=0), datetime.timedelta(days=100*365)])

        results[schedule['id']] = lambda td: min([pair[1] for pair in reminder_pairs if pair[0] < td])
    return results

def send_reminders(db_con:sqlite3.Connection, new_jobs: List[int]):
    """Sends reminders for new and existing jobs"""
    now = datetime.datetime.now(ET)
    to_remind_ids = new_jobs

    reminder_schedules = get_schedules(db_con)

    possible_jobs = db_con.execute("SELECT id, due_ts, last_reminder_ts, reminder_schedule, assignee FROM jobs WHERE done=0").fetchall()
    for job in possible_jobs:
        if job['assignee'] is None:
            return
        due_time_delta = now - datetime.datetime.fromisoformat(job['due_ts'])
        reminder_time_delta = now - datetime.datetime.fromisoformat(job['last_reminder_ts'])

        current_reminder_delay = reminder_schedules[job['reminder_schedule']](due_time_delta)

        if reminder_time_delta > current_reminder_delay:
            to_remind_ids.append(job['id'])
    # Send messages
    for job_id in to_remind_ids:
        job = db_con.execute("SELECT name, due_ts, assignee FROM jobs WHERE id=?", (job_id,)).fetchone()
        new_message = module_config['slack_client'].chat_postMessage(
            channel=job['assignee'],
            blocks=build_reminder_message(job_id, job['name'], datetime.datetime.fromisoformat(job['due_ts'])),
            text=f"Reminder: {job['name']}"
        )

        # Track the new message and set the last reminder timestamp properly
        db_con.execute(
            "INSERT INTO reminder_messages (job_id, channel, slack_message_ts) VALUES (?,?,?)",
            (job_id, new_message['channel'], new_message['ts'])
        )
        db_con.execute("UPDATE jobs SET last_reminder_ts=? WHERE id=?", (now.isoformat(),job_id))
    db_con.commit()

@loader.timer
def check_jobs_reminders(_):
    try:
        db_con = sqlite3.connect('labjobs.db')
        db_con.row_factory = sqlite3.Row
        new_jobs = add_new_jobs(db_con)
        send_reminders(db_con, new_jobs)
        db_con.close()
    except (Exception, OSError) as e:
        stacktrace = '\n'.join(traceback.TracebackException.from_exception(e).format())
        module_config['logger'](f'Got exception while running reminders: {e}\nStacktrace: {stacktrace}')
    return 30 * 1

@loader.home_tab
def lab_job_home_tab(_user):
    # Ignores the user, displaying the same thing
    # for everyone
    home_tab_blocks = copy.deepcopy(JOB_HOME)
    db_con = sqlite3.connect('labjobs.db')
    db_con.row_factory = sqlite3.Row

    n_jobs = len(db_con.execute("SELECT id FROM template_jobs").fetchall())

    due_jobs = db_con.execute("SELECT name, assignee FROM jobs WHERE done=0").fetchall()

    home_tab_blocks[1]['text']['text'] = home_tab_blocks[1]['text']['text'].format(num_jobs=n_jobs)
    if len(due_jobs) > 0:
        home_tab_blocks[3]['text']['text'] = '*Pending jobs*:\n' + '\n'.join([
            f'{job["name"]} (<@{job["assignee"]}>)'
            for job in due_jobs
        ])

    db_con.close()
    return home_tab_blocks

@loader.slack.action({"action_id": "labjob-complete"})
def complete_labjob(ack, body, client):
    """Completes the given lab job, updating all messages."""
    ack()
    module_config['logger'](body)
    db_con = sqlite3.connect('labjobs.db')
    db_con.row_factory = sqlite3.Row

    job_id = int(body['actions'][0]['value'])
    db_con.execute("UPDATE jobs SET done=1 WHERE id=?", (job_id,))
    db_con.commit()
    job = db_con.execute("SELECT name, due_ts FROM jobs WHERE id=?", (job_id,)).fetchone()
    reminders = db_con.execute("SELECT channel, slack_message_ts FROM reminder_messages WHERE job_id=?", (job_id,)).fetchall()
    for reminder in reminders:
        module_config['logger'](reminder)
        client.chat_update(
            channel=reminder['channel'],
            ts=reminder['slack_message_ts'],
            blocks=build_completed_message(job['name'], datetime.datetime.fromisoformat(job['due_ts'])),
            text=f'Lab job {job["name"]} complete!'
        )
    db_con.close()

@loader.slack.action({"action_id": "labjob-reassign"})
def show_reassign_modal(ack, body, client):
    ack()

    db_con = sqlite3.connect('labjobs.db')
    db_con.row_factory = sqlite3.Row
    job_id = int(body['actions'][0]['value'])
    job = db_con.execute("SELECT name, due_ts FROM jobs WHERE id=?", (job_id,)).fetchone()

    client.views_open(
        view=build_reassign_modal(job_id, job["name"], datetime.datetime.fromisoformat(job["due_ts"])),
        trigger_id=body['trigger_id']
    )

    db_con.close()

    module_config['logger'](body['actions'])

@loader.slack.view("labjob-reassign-modal")
def reassign_labjob(ack, body, client, view):
    ack()
    module_config['logger'](body)

@loader.slack.action({"action_id": "reminder_schedule-add"})
def add_reminder_schedule(ack, body, client):
    ack()

    db_con = sqlite3.connect('labjobs.db')
    db_con.row_factory = sqlite3.Row

    db_con.execute("""
        INSERT INTO reminder_schedules (name, reminders)
        VALUES ("Unnamed", "")
    """)
    db_con.commit()

    client.views_update(
        view=build_reminder_schedule_modal(db_con),
        view_id=body['container']['view_id']
    )

    db_con.close()

    module_config['logger'](body)

@loader.slack.action({"action_id": "reminder_schedule-edit"})
def edit_reminder_schedule(ack, body, client):
    ack()

    module_config['logger'](body)

    db_con = sqlite3.connect('labjobs.db')
    db_con.row_factory = sqlite3.Row
    client.views_push(
        view=build_edit_reminder_schedule_modal(db_con, int(body['actions'][0]['value']), body['container']['view_id']),
        trigger_id=body['trigger_id']
    )
    db_con.close()

@loader.slack.view("reminder_schedule-edit-modal")
def edit_reminder_schedule_modal(ack, body, client, view):
    ack()

    metadata_split = view['private_metadata'].split(';')
    schedule_id = int(metadata_split[0])
    prev_view_id = metadata_split[1]
    name = view['state']['values']['reminder_schedule-name']['reminder_schedule-nameval']['value']
    reminders = view['state']['values']['reminder_schedule-schedule']['reminder_schedule-scheduleval']['value']
    module_config['logger'](f'Schedule update: {name},{reminders}')
    db_con = sqlite3.connect('labjobs.db')
    db_con.row_factory = sqlite3.Row
    db_con.execute("""
        UPDATE reminder_schedules
        SET name=?, reminders=?
        WHERE id=?
    """, (name, reminders, schedule_id))
    db_con.commit()

    client.views_update(
        view=build_reminder_schedule_modal(db_con),
        view_id=prev_view_id
    )
    db_con.close()

@loader.slack.action({"action_id": "reminder_schedule-delete"})
def delete_reminder_schedule(ack, body, client):
    ack()
    
    # NULL out any template jobs and jobs that reference this schedule
    schedule_id = int(body['actions'][0]['value'])
    db_con = sqlite3.connect('labjobs.db')
    db_con.row_factory = sqlite3.Row
    db_con.execute("UPDATE template_jobs SET reminder_schedule=NULL WHERE reminder_schedule=?", (schedule_id,))
    db_con.execute("UPDATE jobs SET reminder_schedule=NULL WHERE reminder_schedule=?", (schedule_id,))
    db_con.execute("DELETE FROM reminder_schedules WHERE id=?", (schedule_id,))
    db_con.commit()

    client.views_update(
        view=build_reminder_schedule_modal(db_con),
        view_id=body['container']['view_id']
    )

    db_con.close()

@loader.slack.action({"action_id": "labjob-add"})
def add_labjob(ack, body, client):
    ack()

    db_con = sqlite3.connect('labjobs.db')
    db_con.row_factory = sqlite3.Row

    db_con.execute("""
        INSERT INTO template_jobs (sort_priority, name, last_generated_ts, recurrence)
        VALUES (0, "Unnamed", "1970-01-01", "FREQ=WEEKLY;INTERVAL=1;BYDAY=MO")
    """)
    db_con.commit()

    client.views_update(
        view=build_view_jobs_modal(db_con),
        view_id=body['container']['view_id']
    )

    db_con.close()

@loader.slack.action({"action_id": "labjob-edit"})
def edit_labjob(ack, body, client):
    ack()
    
    module_config['logger'](body)
    db_con = sqlite3.connect('labjobs.db')
    db_con.row_factory = sqlite3.Row
    client.views_push(
        view=build_edit_job_modal(db_con, int(body['actions'][0]['value']), body['container']['view_id']),
        trigger_id=body['trigger_id']
    )
    db_con.close()

@loader.slack.view("labjob-edit-modal")
def edit_labjob(ack, body, client, view):
    ack()

    metadata_split = view['private_metadata'].split(';')
    job_id = int(metadata_split[0])
    prev_view = metadata_split[1]
    name = view['state']['values']['labjob-name']['labjob-nameval']['value']
    assignee = view['state']['values']['labjob-assignee']['labjob-assigneeval']['selected_user']
    sort_priority = int(view['state']['values']['labjob-sort_priority']['labjob-sort_priorityval']['value'])
    reminder_schedule = int(view['state']['values']['labjob-reminder_schedule']['labjob-reminder_scheduleval']['selected_option']['value'])
    recurrence = view['state']['values']['labjob-recurrence']['labjob-recurrenceval']['value']
    module_config['logger'](f'Job update: {name},{assignee},{sort_priority},{reminder_schedule},{recurrence}')
    db_con = sqlite3.connect('labjobs.db')
    db_con.row_factory = sqlite3.Row
    db_con.execute("""
        UPDATE template_jobs
        SET sort_priority=?, name=?, last_generated_ts="1970-01-01", reminder_schedule=?, recurrence=?, assignee=?
        WHERE id=?
    """, (sort_priority, name, reminder_schedule, recurrence, assignee, job_id))
    db_con.commit()

    client.views_update(
        view=build_view_jobs_modal(db_con),
        view_id=prev_view
    )
    db_con.close()

@loader.slack.action({"action_id": "labjob-delete"})
def delete_labjob(ack, body, client):
    ack()

    labjob_id = int(body['actions'][0]['value'])
    db_con = sqlite3.connect('labjobs.db')
    db_con.row_factory = sqlite3.Row
    db_con.execute("DELETE FROM template_jobs WHERE id=?", (labjob_id,))
    db_con.commit()

    client.views_update(
        view=build_view_jobs_modal(db_con),
        view_id=body['container']['view_id']
    )
    db_con.close()

@loader.slack.action({"action_id": "labjob-view"})
def show_labjob_view_modal(ack, body, client):
    ack()

    db_con = sqlite3.connect('labjobs.db')
    db_con.row_factory = sqlite3.Row

    client.views_open(
        view=build_view_jobs_modal(db_con),
        trigger_id=body['trigger_id']
    )

    db_con.close()

@loader.slack.action({"action_id": "reminder_schedule-view"})
def show_schedule_view_modal(ack, body, client):
    ack()

    db_con = sqlite3.connect('labjobs.db')
    db_con.row_factory = sqlite3.Row

    client.views_open(
        view=build_reminder_schedule_modal(db_con),
        trigger_id=body['trigger_id']
    )

    db_con.close()

@loader.slack.action({"action_id": "labjob-assigneeval"})
def _assignee_noop(ack, body, logger):
    ack()
@loader.slack.action({"action_id": "labjob-reminder_scheduleval"})
def _assignee_noop(ack, body, logger):
    ack()