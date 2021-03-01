"""
Module to keep track of if someone is already using a Flowjo license,
so as not to disturb them.
"""
from labbot.module_loader import ModuleLoader
from fastapi import HTTPException
import json

module_config = {}

loader = ModuleLoader()

def is_checked_out():
    with open('flowjo_checkout.json') as f:

        status = json.load(f)
        return status['in_use']

def write_status(checked_out: bool):
    with open('flowjo_checkout.json', 'w') as f:
        json.dump({
            'in_use': checked_out
        }, f)



def register_module(config):
    # Override defaults if present 
    module_config.update(config)

    # Check for token secret
    if 'token' not in module_config:
        raise RuntimeError("Expected a secret token for authentication! We weren't passed a 'token' key")
    return loader

@loader.fastapi.get("flowjo/state")
def current_status(token: str):
    # If the token is correct, respond with the current checkout status
    if (token != module_config['token']):
        raise HTTPException(status_code=401, detail="Invalid auth token")

    return {"checked_out": is_checked_out()}

@loader.fastapi.post("flowjo/checkin")
def checkin_license(token: str):
    if (token != module_config['token']):
        raise HTTPException(status_code=401, detail="Invalid auth token")

    # Can only check-in if we are checked out
    if not is_checked_out():
        raise HTTPException(status_code=409, detail="License already checked in")
    write_status(False)
    module_config['hometab_update']()

@loader.fastapi.post("flowjo/checkout")
def checkout_license(token: str):
    if (token != module_config['token']):
        raise HTTPException(status_code=403, detail="Invalid auth token")
    # Can only check out if we are not in use
    if is_checked_out():
        raise HTTPException(status_code=409, detail="License already checked out!")
    write_status(True)
    module_config['hometab_update']()

@loader.home_tab
def flowjo_checkout_home(user):
    # Ignores the user, displaying the same thing
    # for everyone
    return [{
        "type": "section",
        "text": {
                "type": "mrkdwn",
                "text": "*Flowjo license:* {}".format('In use' if is_checked_out() else 'Free!')
        },
	},]
