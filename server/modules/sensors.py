"""
Module that tracks various in-lab sensors using MQTT and iMonnit.
"""
from labbot.module_loader import ModuleLoader
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from pydantic import BaseModel
from typing import Collection
import json


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
    sensorMessages: Collection[MonnitSensorMessage]

module_config = {}

loader = ModuleLoader()

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
    return loader

@loader.fastapi.post("/imonnit_endpoint")
def imonnit_push(message: MonnitMessage):
    module_config['logger'](f'Got message {message}')
    return {'success': True}