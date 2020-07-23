from multiprocessing import Process
import uvicorn
from fastapi import FastAPI

slackapi_app = FastAPI()

@slackapi_app.get("/")
async def root():
    return {"message": "Hello World"}

proc = None

def run(port):
    """
    Run the uvicorn server
    """
    uvicorn.run(app=slackapi_app, host='localhost', port=port)

def start(port):
    """
    Spawn a new process for the server
    """
    global proc
    proc = Process(target=run, args=(port,), daemon=True)
    proc.start()

def stop():
    """
    Join the server after closing
    """
    global proc
    if proc:
        proc.join(0.25)
