from copy import deepcopy
from datetime import datetime
import subprocess
import pytz
import re

from labbot.module_loader import ModuleLoader

ETC = pytz.timezone('America/New_York')

module_config = {}

loader = ModuleLoader()

def register_module(config):
    module_config.update(config)
    if 'remote_name' not in module_config:
        raise RuntimeError("Must specify a remote name that is accessible over https for read-only!")
    if 'setup_py_path' not in module_config:
        raise RuntimeError("Must specify the path to the setup.py file, relative to the runtime working directory!")
    return loader

@loader.home_tab
def dev_tools_home_tab(user):
    # Ignores the user, displaying the same thing
    # for everyone
    now = datetime.now(ETC)
    return [{
        "type": "section",
        "text": {
                "type": "mrkdwn",
                "text": "Last updated _{}_".format(
                    now.strftime('%B %e, %l:%M:%S %p'))
        },
        "accessory": {
                "type": "button",
                "text": {
                        "type": "plain_text",
                        "text": "Dev tools",
                        "emoji": True
                },
                "action_id": "open_dev_tools"
        }
	},]

@loader.timer
def print_startup(client):
    client.chat_postMessage(
            channel='#labbot_debug',
            text=':wave: Labbot starting on {}'.format(get_branch()))
    return None

def get_branch(name='HEAD'):
    """
    Returns a summary of the current HEAD git state
    """
    branch_name = subprocess.run(['git', 'rev-parse', '--abbrev-ref', name], capture_output=True).stdout.decode('utf-8').strip('\n')

    if branch_name == 'HEAD':
        all_names = subprocess.run(['git', 'show', '-s', '--pretty=%D', name], capture_output = True)
        match = re.search(r"origin_readonly/([^,\s]+)", all_names.stdout.decode('utf-8'))
        if match is not None:
            branch_name = match.group(1)
    commit_name = subprocess.run(['git', 'rev-parse', '--short', name], capture_output=True).stdout.decode('utf-8').strip('\n')
    return '{}({})'.format(branch_name, commit_name)

def validate_git_commits(branch_name):
    """
    Verifies that the specified branch does not have changes to the setup.py
    """
    pull_result = subprocess.run(['git', 'fetch', module_config['remote_name'], '--tags'])
    result = subprocess.run(['git', 'diff', 'HEAD', '{}/{}'.format(module_config['remote_name'],branch_name),
        '--exit-code', '-s', module_config['setup_py_path']])

    return result.returncode == 0


"git diff HEAD test_branch --exit-code -s test.txt"
@loader.slack.action('commit_validate')
def validate_commit(ack, body, client):
    """
    Checks that the commit can be pulled.
    """
    ack()

    branch_name = body['view']['state']['values']['branch_selection']['branch_name']['value']

    # Update the view to be updated
    view = deepcopy(dev_tools_view)
    view['blocks'][2]['elements'][0]['text']['text'] = ':hourglass: Validating commit...'
    first_update = client.views_update(
            view_id=body['view']['id'],
            hash=body['view']['hash'],
            view=view)
    if validate_git_commits(branch_name):
        view = deepcopy(dev_tools_validated)
        view['blocks'][0]['text']['text'] = 'Updating `{}` -> `{}`'.format(
                get_branch(),
                get_branch(branch_name))
        view['private_metadata'] = branch_name
    else:
        view = deepcopy(dev_tools_view)
        view['blocks'][0]['text']['text'] = ('Branch/tag `{}` invalid!\nCheck the name of the branch/tag. If you modified the `setup.py` file (e.g. adding new dependencies)' +
        ' then you need to reload the server manually after doing `pip install -e .`').format(branch_name)

    client.views_update(
        view_id=body['view']['id'],
        hash=first_update['view']['hash'],
        view=view)

@loader.slack.view("reload_modal")
def handle_reload_request(ack, body, client, view):
    ack()

    module_config['shutdown_func'](restart=True)

@loader.slack.view("validated_reload_modal")
def handle_update_reload_request(ack, body, client, view):
    ack()

    result = subprocess.run(['git', 'checkout', '{}/{}'.format(module_config['remote_name'], view['private_metadata'])], capture_output=True)
    if result.returncode != 0:
        module_config['logger'](result.stdout.decode('utf-8'))
        return
    # Restart if checkout successful
    module_config['shutdown_func'](restart=True)

@loader.slack.view("confirm_shutdown_modal")
def handle_shutdown(ack, body, client, view):
    ack(response_action="clear")
    module_config['shutdown_func'](restart=False)
    

@loader.slack.action('shutdown_button')
def handle_shutdown_request(ack, body, client):
    ack()

    client.views_push(
            trigger_id=body['trigger_id'],
            view=confirm_modal)

@loader.slack.action('open_dev_tools')
def open_dev_tools(ack, body, client):
    """
    Opens the dev tools model
    """
    ack()

    view = dev_tools_view
    view['blocks'][0]['text']['text'] = 'Current HEAD: `{}`'.format(get_branch())
    client.views_open(
            trigger_id = body['trigger_id'],
            view=view)

dev_tools_view = {
	"type": "modal",
        "private_metadata": "",
        "callback_id": "reload_modal",
	"title": {
		"type": "plain_text",
		"text": "Dev tools",
		"emoji": True
	},
	"submit": {
		"type": "plain_text",
		"text": "Restart",
		"emoji": True
	},
	"blocks": [
		{
			"type": "section",
			"text": {
				"type": "mrkdwn",
				"text": "Current HEAD: `{}`"
			}
		},
		{
			"type": "input",
			"element": {
				"type": "plain_text_input",
				"action_id": "branch_name"
			},
			"label": {
				"type": "plain_text",
				"text": "Load branch/tag:",
				"emoji": True
			},
                        "block_id": "branch_selection",
                        "optional": True
		},
		{
			"type": "actions",
			"elements": [
				{
					"type": "button",
					"text": {
						"type": "plain_text",
						"text": "Validate commit"
					},
					"action_id": "commit_validate"
				},
				{
					"type": "button",
					"text": {
						"type": "plain_text",
						"text": "Shutdown",
						"emoji": True
					},
                                        "style": "danger",
					"action_id": "shutdown_button",
				}
			]
		}
	]
}

dev_tools_validated = {
	"type": "modal",
        "private_metadata": "",
        "callback_id": "validated_reload_modal",
	"title": {
		"type": "plain_text",
		"text": "Dev tools",
		"emoji": True
	},
	"submit": {
		"type": "plain_text",
		"text": "Update and restart",
		"emoji": True
	},
	"blocks": [
		{
			"type": "section",
			"text": {
				"type": "mrkdwn",
				"text": "Current HEAD: `{}`"
			}
		},
		{
			"type": "input",
			"element": {
				"type": "plain_text_input",
				"action_id": "branch_name"
			},
			"label": {
				"type": "plain_text",
				"text": "Load branch/tag:",
				"emoji": True
			},
                        "block_id": "branch_selection"
		},
		{
			"type": "actions",
			"elements": [
				{
					"type": "button",
					"text": {
						"type": "plain_text",
						"text": "Validate commit"
					},
					"action_id": "commit_validate"
				},
				{
					"type": "button",
					"text": {
						"type": "plain_text",
						"text": "Shutdown",
						"emoji": True
					},
					"action_id": "shutdown_button",
					"style": "danger"
				}
			]
		}
	]
}
confirm_modal = {
	"type": "modal",
        "private_metadata": "",
        "callback_id": "confirm_shutdown_modal",
	"title": {
		"type": "plain_text",
                "text": "Confirm shutdown",
		"emoji": True
	},
        "close": {
            "type": "plain_text",
            "text": "Cancel"
        },
	"submit": {
		"type": "plain_text",
                "text": ":warning: Shutdown",
		"emoji": True
	},
	"blocks": [
		{
			"type": "section",
			"text": {
				"type": "mrkdwn",
				"text": "This will _*shutdown the entire*_ LabBot server! It must be restarted manually over `ssh`!"
			}
		}
        ]
}
