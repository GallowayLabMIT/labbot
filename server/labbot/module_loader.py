"""
A class that handles delayed-loading of modules via simple decorators.

This allows FastAPI and python-bolt style decorators to be used almost
directly, even though each module will not be creating its own instances
of these runners.
"""
from slack_bolt.async_app import AsyncApp
import fastapi

class SlackPassthrough:
    """
    Helper class that creates helper functions for every
    non-protected method that slack_bolt.AsyncApp exports, saving
    the decorator arguments for calling later.
    """
    
    def __init__(self):
        """
        Looks at the module export for async_app and copies these functions.
        """
        self.accumulator = []

        slack_methods = [f for f in dir(AsyncApp)
                            if callable(getattr(AsyncApp, f))
                            and not func.startswith("__")]
        for method in slack_methods:
            setattr(self, method) = functools.partialmethod(_defer_slack, method)
    
    def _defer_slack(self, method_name, *args, **kwargs):
        """
        Function to be specalized to a specific Slack function.
        Takes arbitrary args and kwargs that later get passed to the
        named Slack function. 

        Parameters
        ----------
        method_name : str
            The name of the method decorator to later be called as:
            AsyncApp.method_name(*args. **kwargs)(func)
        *args
            Variable length argument list
        **kwargs
            Arbitrary keyword arguments

        Returns:
        --------
        A function with the signature "f(decorated_func)" that returns
        the decorated func directly.
        """

        def decorator(func):
            self.accumulator.append((method_name, func, args, kwargs))
            return func
        return decorator

class FastAPIPassthrough:
    """
    Helper class that creates helper functions for every
    non-protected method that FastAPI.App exports, saving
    the decorator arguments for calling later.
    """
    
    def __init__(self):
        """
        Looks at the module export for async_app and copies these functions.
        """
        self.accumulator = []

        fastapi_methods = [f for f in dir(fastapi.FastAPI)
                            if callable(getattr(fastapi.FastAPI, f))
                            and not func.startswith("__")]
        for method in fastapi_methods:
            setattr(self, method) = functools.partialmethod(_defer_fastapi, method)
    
    def _defer_fastapi(self, method_name, *args, **kwargs):
        """
        Function to be specalized to a specific FastAPI function.
        Takes arbitrary args and kwargs that later get passed to the
        named function. 

        Parameters
        ----------
        method_name : str
            The name of the method decorator to later be called as:
            App.method_name(*args. **kwargs)(func)
        *args
            Variable length argument list
        **kwargs
            Arbitrary keyword arguments

        Returns
        --------
        A function with the signature "f(decorated_func)" that returns
        the decorated func directly.
        """

        def decorator(func):
            self.accumulator.append((method_name, func, args, kwargs))
            return func
        return decorator

class ModuleLoader:
    """
    ModuleLoader accumulates functions registered via decorators.

    To use, initalize a ModuleLoader, then use the @loader.timer,
    @loader.slack.*, and @loader.fastapi.* decorators. The
    available slack decorators are those listed in the bolt_python
    documentation, and the available fastapi ones are those in the
    FastAPI documentation.

    To integrate with the rest of LabBot, you should have a standalone
    function "return_loader", which returns the ModuleLoader created.
    Surrounding code uses this to initalize all of the functions.
    """

    def __init__(self):
        self.slack = SlackPassthrough()
        self.fastapi = FastAPIPassthrough()
        self.timer_accumulator = []

    def timer(self, func):
        """
        Decorator that calls the given function in a timer in the async loop.

        Parameters
        ----------
        func : function
            A function that will be called without arguments on a timer loop.
            This function is expected to return a float or integer representing
            the number of seconds before it should be called again.
        """

        self.timer_accumulator.append(func)
        return func

    def register(self, slack_bolt_instance, fastapi_instance):
        """
        Given the instances of slack and FastAPI, uses the information
        recorded by the decorators to register the functions properly.
        
        Parameters
        ----------
        slack_bolt_instance
            Instance of slack_bolt.async_app.AsyncApp
        fastapi_instance
            Instance of fastapi.FastAPI
        """
        for decoration in self.slack.accumulator:
            name, func, args, kwargs = decoration
            getattr(slack_bolt_instance, name)(*args, **kwargs)(func)

        for decoration in self.fastapi.accumulator:
            name, func, args, kwargs = decoration
            getattr(fastapi_instance, name)(*args, **kwargs)(func)
