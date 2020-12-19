import asyncio
from datetime import datetime
import functools
import importlib
import json # For reading the secrets file
import os
import sys
import threading
import time
import traceback
import pytz

import slack_bolt# Slack file
from slack_bolt.adapter.fastapi import SlackRequestHandler
import fastapi
import contextlib
import uvicorn

ETC = pytz.timezone('America/New_York')

# Create shutdown variables
restart_flag = False
should_shutdown = threading.Condition()

def shutdown_func(restart=False):
    global restart_flag
    should_shutdown.acquire()
    restart_flag = restart
    should_shutdown.notify()
    should_shutdown.release()

with open('labbot.secret') as json_secrets:
    secrets = json.load(json_secrets)

# Create slack credentials
bolt_client = slack_bolt.App(
        signing_secret=secrets['slack']['signing_secret'],
        token=secrets['slack']['api_token']
)
bolt_handler = SlackRequestHandler(bolt_client)

api = fastapi.FastAPI()

@api.post("/slack/events")
async def slack_endpoint(req: fastapi.Request):
    return await bolt_handler.handle(req)



# Define logging function
def slack_log(message, header):
    """
    Logs a message to the #labbot_debug channel.

    Parameters
    ----------
    message : str
        A string message to log. It is logged inside a unformatted text box.
    header : str
        A string message to place within the header to inform the user what module/source generate the message.
    """
    print(message)
    if len(message) > 2000:
        message = message[:2000]
    result = bolt_client.client.chat_postMessage(
            channel='#labbot_debug',
            text='Labbot log:{}'.format(header),
            blocks=json.dumps([{'type':'section', 'text':
                {'type': 'mrkdwn', 'text':
                    '`{}`:\n{}'.format(header, message)}}]))

@bolt_client.error
def labbot_debug_error(error, body, logger):
    try:
        slack_log('Error: {}\nStacktrace:\n```{}```\nCall body: ```{}```'.format(
            error,
            '\n'.join(traceback.TracebackException.from_exception(error).format()),
            body),
            'error_handler')
        logger.exception(f"Error: {error}")
        logger.info(f"Request body: {body}")
    except Exception as e:
        print(e)

home_tab_users = set()
home_tab_functions = []
home_tab_lock = threading.Lock()
should_update_home_tab = False

@bolt_client.event("app_home_opened")
def register_home_tab_open(client, event):
    home_tab_users.add(event['user'])
    update_home_tab()

def update_home_tab():
    """
    Schedules an update to the home tab, to occur in the next asyncio
    update
    """
    global should_update_home_tab
    home_tab_lock.acquire()
    should_update_home_tab = True
    print('Set update flag')
    home_tab_lock.release()



# Start by loading Google credentials
#GAPI_SCOPES = ['https://www.googleapis.com/auth/spreadsheets']
#google_flow = google_auth_oauthlib.flow.InstalledAppFlow.from_client_config(secrets['gapi'], GAPI_SCOPES)
#gapi_creds = google_flow.run_local_server(port=0)



# Load modules
timer_tasks = []
for module_name in secrets['global']['modules']:
    try:
        module = importlib.import_module('modules.{}'.format(module_name))
        if module_name in secrets:
            config = secrets[module_name]
        else:
            config = {}
        config['slack_client'] = bolt_client.client
        config['logger'] = functools.partial(slack_log, header=module_name)
        config['shutdown_func'] = shutdown_func
        module_hooks = module.register_module(config)
        module_hooks.register(bolt_client, api)
        home_tab_functions.extend(module_hooks.home_accumulator)
        timer_tasks.extend(module_hooks.timer_accumulator)
    except Exception as e:
        slack_log('Could not load module `{}`\nError:\n```{}```\nStacktrace:\n```{}```'.format(
            module_name,
            e,
            '\n'.join(traceback.TracebackException.from_exception(e).format())), 'module_loader')


# Start the server

class WebServer(uvicorn.Server):
    def install_signal_handlers(self):
        pass # Use default signal handlers
    
    def run_threaded(self):
        self.config.setup_event_loop()
        loop = asyncio.new_event_loop()
        loop.create_task(self.timer_coroutine(timer_tasks))
        loop.create_task(self.home_tab_coroutine())
        loop.run_until_complete(self.serve())

    async def home_tab_coroutine(self):
        """
        Checks if the home tab should be updated, then sends updated
        views.
        """
        global should_update_home_tab

        while not self.should_exit:
            await asyncio.sleep(0.1)
            if home_tab_lock.acquire(blocking=False):
                try:
                    hour = datetime.now(ETC).hour
                    if hour < 5:
                        time_summary = 'night'
                    elif hour < 12:
                        time_summary = 'morning'
                    elif hour < 17:
                        time_summary = 'afternoon'
                    else:
                        time_summary = 'evening'

                    if should_update_home_tab:
                        should_update_home_tab = False
                        for user in home_tab_users:
                            accum_blocks = []
                            for f in home_tab_functions:
                                accum_blocks.append(f(user))


                            blocks = [{
                                "type": "header",
                                "text": {
                                    "type": "plain_text",
                                    "text": "Good {}!".format(time_summary),
                                }}]
                            for mod_blocks in accum_blocks:
                                if len(mod_blocks) > 0:
                                    blocks.append({ "type": "divider" })
                                    blocks.extend(mod_blocks)

                            built_view = {
                                    "type": "home",
                                    "blocks": blocks
                                    }
                            print(built_view)
                            bolt_client.client.views_publish(
                                    user_id=user,
                                    view=built_view)
                except Exception as e:
                    slack_log('Timer error:\nError:\n```{}```\nStacktrace:\n```{}```'.format(
                        e,
                        '\n'.join(traceback.TracebackException.from_exception(e).format())), 'timer_runner')
                                # If delay is not none, the task wants to be rescheduled

                finally:
                    home_tab_lock.release()

    async def timer_coroutine(self, tasks):
        """
        Runs a series of tasks that should be scheduled on a timer.

        Parameters
        ----------
        tasks
            A list of functions with the signature def f(slack_client) that
            returns either None, if this task should not be repeated, or a
            number (integer or float) of how many seconds should elapse before
            the next check.
        """
        # Spawn a new client for thread safety
        threaded_client = slack_bolt.App(
                signing_secret=secrets['slack']['signing_secret'],
                token=secrets['slack']['api_token']
        )
        loop = asyncio.get_event_loop()

        last_time = time.time()
        # Init the tuple list with the starting time
        tasks_to_complete = [(f, last_time) for f in tasks]

        while not self.should_exit and len(tasks_to_complete) > 0:
            # Wait one second
            await asyncio.sleep(1)
            last_time = time.time()

            rescheduled_tasks = []
            for func, trigger_time in tasks_to_complete:
                # If a function hasn't reached the trigger time, just reschedule
                if trigger_time > last_time:
                    rescheduled_tasks.append((func, trigger_time))
                else:
                    # Otherwise, run the task, handing it the Slack client if needed.
                    try:
                        delay = await loop.run_in_executor(None, func, threaded_client.client)
                        if delay is not None:
                            rescheduled_tasks.append((func, last_time + delay))
                    except Exception as e:
                        slack_log('Timer error:\nError:\n```{}```\nStacktrace:\n```{}```'.format(
                            e,
                            '\n'.join(traceback.TracebackException.from_exception(e).format())), 'timer_runner')
                                    # If delay is not none, the task wants to be rescheduled
            tasks_to_complete = rescheduled_tasks
        # THis will exit when the rest of the webserver is asked to close.

    @contextlib.contextmanager
    def run_in_thread(self):
        thread = threading.Thread(target=self.run_threaded)
        thread.start()
        try:
            while not self.started:
                time.sleep(1e-3)
            yield
        finally:
            self.should_exit = True
            thread.join()

webserver_config = uvicorn.Config(
        api,
        host='localhost',
        port=secrets['global']['port'],
        loop='uvloop')

server = WebServer(webserver_config)

with server.run_in_thread():
    should_shutdown.acquire()
    should_shutdown.wait()

bolt_client.client.chat_postMessage(
        channel='#labbot_debug',
        text='LabBot shutting down. Bye!')

if restart_flag:
    os.execv(sys.executable, ['python'] + sys.argv)



# Launch COVID API
"""
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
"""
