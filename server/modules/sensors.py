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
import struct
import random


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
    if mqtt_client._state != mqtt.mqtt_cs_connected:
        mqtt_client.reconnect()
    # Call the MQTT loop command once every ten seconds
    mqtt_client.loop(timeout=1.0)
    return 10