"""
Module that tracks various in-lab sensors using MQTT and iMonnit.
"""
from labbot.module_loader import ModuleLoader
import fastapi 
from fastapi.security import HTTPBasic, HTTPBasicCredentials
import paho.mqtt.client as mqtt
from pydantic import BaseModel
import typing
import sqlite3
import secrets
import datetime
import time


class MonnitGatewayMessage(BaseModel):
    gatewayID: str
    gatewayName: str
    accountID: str
    networkID: str
    messageType: str
    power: str
    batteryLevel: str
    date: str
    count: str
    signalStrength: str
    pendingChange: str

class MonnitSensorMessage(BaseModel):
    sensorID: str
    sensorName: str
    applicationID: str
    networkID: str
    dataMessageGUID: str
    state: str
    messageDate: str
    rawData: str
    dataType: str
    dataValue: str
    plotValues: str
    plotLabels: str
    batteryLevel: str
    signalStrength: str
    pendingChange: str
    voltage: str

class MonnitMessage(BaseModel):
    gatewayMessage: MonnitGatewayMessage
    sensorMessages: typing.List[MonnitSensorMessage]

module_config = {}

loader = ModuleLoader()

mqtt_client = mqtt.Client()


def on_connect(client, _, flags, rc):
    client.subscribe('status/request')

def on_message(client, userdata, msg):
    if msg.topic == 'status/request':
        client.publish('status/current', '0')


def register_module(config):
    # Override defaults if present 
    module_config.update(config)

    # Check for token secret
    if 'iMonnit_webhook' not in module_config or 'username' not in module_config['iMonnit_webhook'] or 'password' not in module_config['iMonnit_webhook']:
        raise RuntimeError("Expected the iMonnit webhook username/password to be passed as a dictionary {'username': 'foo', 'password': 'bar'} to key 'iMonnit_webhook'!")
    if 'mqtt' not in module_config:
        raise RuntimeError("Expected to be passed MQTT configuration information in key 'mqtt'!")
    if 'username' not in module_config['mqtt'] or 'password' not in module_config['mqtt']:
        raise RuntimeError("Expected to be passed client credentials in keys 'username' and 'password' under 'mqtt'!")
    if 'url' not in module_config['mqtt'] or 'port' not in module_config['mqtt']:
        raise RuntimeError("Expected to be passed broker location ('url' and 'port') in key 'mqtt'!")
    if 'client_id' not in module_config['mqtt']:
        raise RuntimeError("Expected to be passed a persistant client ID ('client_id') in key 'mqtt'!")
    
    
    # Attempt to connect to MQTT
    mqtt_client.reinitialise(client_id=module_config['mqtt']['client_id'], clean_session=False)
    mqtt_client.tls_set(tls_version=mqtt.ssl.PROTOCOL_TLS)
    mqtt_client.on_connect = on_connect
    mqtt_client.on_message = on_message
    mqtt_client.enable_logger()
    #mqtt_client.on_message = lambda x: x
    mqtt_client.username_pw_set(module_config['mqtt']['username'], module_config['mqtt']['password'])
    mqtt_client.connect_async(module_config['mqtt']['url'], module_config['mqtt']['port'], keepalive=60)

    # Init database connection
    db_con = sqlite3.connect('sensors.db')
    cursor = db_con.cursor()
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS sensors (
        id integer PRIMARY KEY,
        type integer NOT NULL,
        name text NOT NULL
    );
    ''')
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS temperature_measurements (
        datetime text,
        sensor integer NOT NULL,
        measurement real NOT NULL,
        battery_level real NOT NULL,
        FOREIGN KEY (sensor)
            REFERENCES sensors (sensor)
    );
    ''')
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS alarm_measurements (
        datetime text,
        sensor integer NOT NULL,
        measurement real NOT NULL,
        FOREIGN KEY (sensor)
            REFERENCES sensors (sensor)
    );
    ''')

    return loader

imonnit_security = HTTPBasic()

@loader.fastapi.post("/imonnit_endpoint")
def imonnit_push(message: MonnitMessage, credentials: HTTPBasicCredentials = fastapi.Depends(imonnit_security)):
    if not (
        secrets.compare_digest(credentials.username, module_config['iMonnit_webhook']['username']) and
        secrets.compare_digest(credentials.password, module_config['iMonnit_webhook']['password'])):
        raise fastapi.HTTPException(
            status_code = fastapi.status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Basic"}
        )
    
    db_con = sqlite3.connect('sensors.db')
    cursor = db_con.cursor()
    for s_message in message.sensorMessages:
        # See if sensor is already in database. If not, add it as a 
        cursor.execute("SELECT id FROM sensors WHERE type=0 AND name=?;", (s_message.sensorName,))
        if not cursor.fetchone():
            cursor.execute("INSERT INTO sensors(type,name) VALUES (?,?);", (0, s_message.sensorName))
        # Find sensor ID, writing measurement into 
        cursor.execute("SELECT id FROM sensors WHERE type=0 AND name=?;", (s_message.sensorName,))
        sensor_id = cursor.fetchone()[0]
        cursor.execute(
            "INSERT INTO temperature_measurements(datetime,sensor,measurement,battery_level) VALUES (?,?,?,?)",(
            datetime.datetime.now(datetime.timezone.utc).isoformat(),
            sensor_id,
            float(s_message.dataValue),
            float(s_message.batteryLevel)
        ))
    return {'success': True}

@loader.timer
def poll_mqtt(slack_client):
    # Check that MQTT is still alive
    if mqtt_client._state == mqtt.mqtt_cs_connect_async:
        mqtt_client.reconnect()
    # Call the MQTT loop command once every five seconds
    mqtt_client.loop(timeout=0.1)
    return 5

BASE_HOME_TAB_MODEL = {
    "type": "home",
    "blocks": [
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": "*Sensor status*"
            }
        },
        {
            "type": "divider"
        }
    ]
}


# -- https://stackoverflow.com/a/5333305 -- CC BY-SA 2.5 ----------------------------------
def plur(it):
    '''Quick way to know when you should pluralize something.'''
    try:
        size = len(it)
    except TypeError:
        size = int(it)
    return '' if size==1 else 's'

def readable_delta(from_timestamp:datetime.datetime, until_timestamp:datetime.datetime) -> str:
    '''Returns a nice readable delta with datetimes'''
    delta = until_timestamp - from_timestamp

    # deltas store time as seconds and days, we have to get hours and minutes ourselves
    delta_minutes = delta.seconds // 60
    delta_hours = delta_minutes // 60

    ## show a fuzzy but useful approximation of the time delta
    if delta.days:
        return '%d day%s ago' % (delta.days, plur(delta.days))
    elif delta_hours:
        return '%d hour%s, %d minute%s ago' % (delta_hours, plur(delta_hours),
                                               delta_minutes, plur(delta_minutes))
    elif delta_minutes:
        return '%d minute%s ago' % (delta_minutes, plur(delta_minutes))
    else:
        return '%d second%s ago' % (delta.seconds, plur(delta.seconds))
# ---------------------------------------------------------------------------------------


def generate_sensor_status_item(sensor_name: str, status: int, timestamp:datetime.datetime, temp: float) -> dict:
    status_mapping = {0: 'large_green_circle:', 1:':large_yellow_circle', 2: ':red_circle'}
    str_delta = readable_delta(timestamp, datetime.datetime.now(datetime.timezone.utc))
    return {
        "type": "section",
        "text": {
            "type": "mrkdwn",
            "text": f"{status_mapping[status]}\t*{sensor_name}*\t\t_last update {str_delta}_\n\t\t *Temperature:* {temp:.1f}C"
        },
        "accessory": {
            "type": "image",
            "image_url": "https://gallowaylabmit.github.io/protocols",
            "alt_text": "Temperature graph not avaliable"
        }
    }

@loader.home_tab
def dev_tools_home_tab(user):
    # Ignores the user, displaying the same thing
    # for everyone
    home_tab_model = BASE_HOME_TAB_MODEL.copy()
    db_con = sqlite3.connect('sensors.db')
    cursor = db_con.cursor()
    cursor.execute("SELECT id, name FROM sensors WHERE type=0")
    sensors = cursor.fetchall()
    for id, name in sensors:
        cursor.execute("SELECT datetime, measurement FROM temperature_measurements ORDER BY datetime DESC WHERE sensor=?", (id,))
        row = cursor.fetchone()
        if row is not None:
            timestamp = datetime.datetime.fromisoformat(row[0]['datetime'])
            temp = float(row[0]['measurement'])
            home_tab_model['blocks'].append(generate_sensor_status_item(name, 2, timestamp, temp))
    return [home_tab_model,]