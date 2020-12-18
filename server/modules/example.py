"""
Example module demonstrating both the Slack integration
basics and timer basics, plus module loading
"""
from labbot.module_loader import ModuleLoader

# Create a module_config dictionary to store necessary
# configuration information, loaded from `labbot.secret`
#
# In this dictionary, you can set default values for parameters; if
# also specified in `labbot.secret`, they will be overwritten when you
# do an update merge.
module_config = {}

# Create a new ModuleLoader, which gives us all the decorators you need
loader = ModuleLoader()

# Labbot will try to call this function to actually load your module!
# It will give you the config object, which should be merged into your config.
# This config object also has several helper key/values:
#
# slack_client: A slack client object. This should _only_ be used in the async
#   part of the code! (e.g. in fastAPI or slack decorated functions)
#   Timer callbacks get passed their own thread-safe slack client object.
#
# logger: A function you can call to report log information back to the
#   #labbot_debug channel
def register_module(config):
    # Override defaults if present 
    module_config.update(config)

    # Here, you should make any checks on the config.
    # If there are any necessary keys missing (such as username
    # or password), raise a RuntimeError
    
    # Example:
    # if 'super_secret_key_that_is_needed' not in module_config:
    #    raise RuntimeError("Our module was not passed the 'super_secret' key!")

    # Return the ModuleLoader object we created, so that labbot can hook your
    # module in
    return loader

# Use the timer decorator to specify a timer function.
@loader.timer
def hello_world_timer(slack_client):
    """
    Functions that run on a timer are expected to take
    a single argument, named slack_client. This is a WebClient,
    so you can use it to post messages and such.

    Timer functions should return either None or a number.

    If you return None, then your timer function will not be called again.
    If you return a number, either an integer or float, then your function
    will be called again in that number of seconds.
    """
    # Send slack messages every minute.
    slack_client.chat_postMessage(
            channel='#labbot_debug',
            text='Hello world from the example module!')
    # Reschedule us to run again in one minute
    return 60

# Any decorator in the slack_bolt documentation:
#
# https://slack.dev/bolt-python/
#
# or in the FastAPI documentation
#
# https://fastapi.tiangolo.com/
#
# can be called via the loader function. Whenever you see @app.decorator,
# instead use @loader.slack.decorator or @loader.fastapi.decorator
@loader.slack.event("app_mention")
def handle_mention(body, say):
    """
    Respond to mentions of labbot (@labbot) with a friendly
    response
    """
    user = body['event']['user']

    # <@blah> is special Slack syntax for bot users.
    # user is actually your user ID string (something like W08A1734),
    # so <@W08A1734> gets formatted as whatever your display name is.
    say('Hi <@{}>!'.format(user))
