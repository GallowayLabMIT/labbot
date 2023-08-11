"""
Module that tracks various in-lab sensors using MQTT and iMonnit.
"""
from labbot.module_loader import ModuleLoader
import fastapi 
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from pydantic import BaseModel
import typing
import sqlite3
import secrets
import datetime
import collections
import copy
import functools
import time

from typing import List


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

Measurement = collections.namedtuple("Measurement", 'timestamp, measurement')
SensorStatus = collections.namedtuple('SensorStatus', 'overall, measurements')

module_config = {}

loader = ModuleLoader()

def register_module(config):
    # Override defaults if present 
    module_config.update(config)

    # Check for token secret
    if 'iMonnit_webhook' not in module_config or 'username' not in module_config['iMonnit_webhook'] or 'password' not in module_config['iMonnit_webhook']:
        raise RuntimeError("Expected the iMonnit webhook username/password to be passed as a dictionary {'username': 'foo', 'password': 'bar'} to key 'iMonnit_webhook'!")
    if 'sensor_limits' not in module_config:
        raise RuntimeError("Expected to have sensor critical levels set in key 'sensor_limits'!")
    if 'channel_id' not in module_config:
        raise RuntimeError("Expected to have channel id set in key 'channel_id'!")
    
    
    # Init database connection
    db_con = sqlite3.connect('sensors.db')
    with db_con:
        db_con.execute('''
        CREATE TABLE IF NOT EXISTS sensors (
            id integer PRIMARY KEY,
            type integer NOT NULL,
            name text NOT NULL
        );
        ''')
        db_con.execute('''
        CREATE TABLE IF NOT EXISTS temperature_measurements (
            timestamp text,
            received_timestamp text,
            sensor integer NOT NULL,
            measurement real NOT NULL,
            battery_level real NOT NULL,
            FOREIGN KEY (sensor)
                REFERENCES sensors (sensor)
        );
        ''')
        db_con.execute('''
        CREATE TABLE IF NOT EXISTS alarm_measurements (
            timestamp text,
            sensor integer NOT NULL,
            measurement real NOT NULL,
            FOREIGN KEY (sensor)
                REFERENCES sensors (sensor)
        );
        ''')
        db_con.execute('''
        CREATE TABLE IF NOT EXISTS alerts (
            id integer PRIMARY KEY,
            sensor integer NOT NULL,
            status integer NOT NULL,
            slack_ts text,
            initial_timestamp text NOT NULL,
            last_timestamp text NOT NULL,
            inflight BOOLEAN NOT NULL CHECK (inflight IN (0, 1)),
            FOREIGN KEY (sensor)
                REFERENCES sensors (sensor)
        );
        ''')
        db_con.execute('''
        CREATE TABLE IF NOT EXISTS battery_alerts (
            id integer PRIMARY KEY,
            sensor integer NOT NULL,
            slack_ts text,
            initial_timestamp text NOT NULL,
            last_timestamp text NOT NULL,
            inflight BOOLEAN NOT NULL CHECK (inflight IN (0, 1)),
            FOREIGN KEY (sensor)
                REFERENCES sensors (sensor)
        );
        ''')
    db_con.close()
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
    with db_con:
        for s_message in message.sensorMessages:
            # See if sensor is already in database. If not, add it as a 
            cursor = db_con.cursor()
            cursor.execute("SELECT id FROM sensors WHERE type=0 AND name=?;", (s_message.sensorName,))
            if not cursor.fetchone():
                cursor.execute("INSERT INTO sensors(type,name) VALUES (?,?);", (0, s_message.sensorName))
            # Find sensor ID, writing measurement into 
            cursor.execute("SELECT id FROM sensors WHERE type=0 AND name=?;", (s_message.sensorName,))
            sensor_id = cursor.fetchone()[0]
            db_con.execute(
                "INSERT INTO temperature_measurements(timestamp,received_timestamp, sensor,measurement,battery_level) VALUES (?,?,?,?,?)",(
                datetime.datetime.fromisoformat(s_message.messageDate + '+00:00').isoformat(),
                datetime.datetime.now(datetime.timezone.utc).isoformat(),
                sensor_id,
                float(s_message.dataValue),
                float(s_message.batteryLevel)
            ))
            cursor.close()
    check_status_alerts(db_con)
    db_con.close()
    return {'success': True}

def check_status_alerts(db_con:sqlite3.Connection, perform_hometab_update:bool=True) -> dict:
    """
    Given a database connection, checks the current status, returning the status dictionary
    and updating Slack alerts and MQTT as necessary.

    Checks the status of all sensors, comparing to the built in limits.
    These limits take the form of a temperature level and a TTA, time to alarm.
    Each also has a heartbeat_timeout, which is the time in seconds that have elapsed
    """

    status_dict = {}
    cursor = db_con.cursor()
    for sensor, limits in module_config['sensor_limits'].items():
        cursor.execute("SELECT id FROM sensors WHERE type=0 AND name=?;", (sensor,))
        sensor_id = cursor.fetchone()

        if sensor_id is not None:
            cursor.execute("SELECT timestamp, measurement FROM temperature_measurements WHERE sensor=? ORDER BY timestamp DESC", (sensor_id[0],))
            # Collect sensor readings. Ensure that we always take at least one measurement, and take until we are beyond the heartbeat limit
            measurements : List[Measurement] = []
            now = datetime.datetime.now(datetime.timezone.utc)
            heartbeat_cutoff = now - datetime.timedelta(seconds=limits['heartbeat_timeout_sec']) - datetime.timedelta(days=5)
            alarm_cutoff = now - datetime.timedelta(seconds=limits['time_to_alarm_sec'])
            for row in cursor:
                cur_m = Measurement(timestamp=datetime.datetime.fromisoformat(row[0]), measurement=row[1])
                measurements.append(cur_m)
                if cur_m.timestamp < heartbeat_cutoff:
                    break

            
            if len(measurements) > 0:
                num_in_heartbeat_interval = sum([measurement.timestamp > heartbeat_cutoff for measurement in measurements])
                alarm_measurements = [m for m in measurements if m.timestamp > alarm_cutoff]
                last_measurement_bad = measurements[0].measurement > limits['temperature_limit']
                good_readings_in_alarm_tspan = sum(m.measurement < limits['temperature_limit'] for m in alarm_measurements)

                # if last measurement is bad and there are no good readings in alarm limit, alarm
                overall_status = 0
                if last_measurement_bad and good_readings_in_alarm_tspan == 0:
                    overall_status = 2
                elif num_in_heartbeat_interval == 0:
                    overall_status = 1
                #module_config['logger'](f'Sensor {sensor}: num_in_heartbeat{num_in_heartbeat_interval}, last_measurement_bad:{last_measurement_bad}, good_readings_in_alarm_num:{good_readings_in_alarm_tspan}')
            else:
                overall_status = 0
            status_dict[sensor] = SensorStatus(overall=overall_status, measurements=measurements)
            #module_config['logger'](f'Sensor {sensor}: {status_dict[sensor]}')
    cursor.close()

    overall_status = max([v.overall for v in status_dict.values()]) if len(status_dict) > 0 else 0

    for k, v in status_dict.items():
        slack_alert(db_con, k, v)

    if perform_hometab_update:
        module_config['hometab_update']()
    
    return status_dict


BASE_ALERT_MESSAGE = [
    {
        "type": "section",
        "text": {
            "type": "mrkdwn",
            "text": "{at_channel} Sensor *{sensor_name}* {status_phrase}\t<{home_tab_url}|View dashboard>"
        }
    },
    {
        "type": "section",
        "fields": [
            {
                "type": "mrkdwn",
                # TODO: actually fill in this stuff
                "text": "*Recent measurements:*\n{readings}"
            },
            {
                "type": "mrkdwn",
                "text": "{is_resolved}\n{resolved_reading}"
            }
        ]
    }
]

def measurement_to_str(measurement: Measurement) -> str:
    return f'{measurement.measurement}C _(<!date^{int(measurement.timestamp.timestamp())}^{{date_short_pretty}}, {{time}}|{measurement.timestamp.isoformat()}>)_'

def measurements_to_str(measurements: List[Measurement], max_n=10) -> str:
    if len(measurements) > max_n:
        # Elide the list
        return '\n'.join(
            [measurement_to_str(m) for m in measurements[:(max_n // 2)]] +
            ['...'] +
            [measurement_to_str(m) for m in measurements[-(max_n - (max_n // 2)):]]
            )
    return '\n'.join(measurement_to_str(m) for m in measurements)


def build_alert_message(sensor_name: str, sensor_status: SensorStatus, old_status: int):
    message = copy.deepcopy(BASE_ALERT_MESSAGE)
    if sensor_status.overall != old_status:
        # Alert is over
        message[0]['text']['text'] = message[0]['text']['text'].format(
            at_channel='',
            sensor_name=sensor_name,
            status_phrase='was alarming.' if old_status == 2 else 'previously missed heartbeat check-ins.',
            home_tab_url=module_config['home_tab_url']
        )
        message[1]['fields'][0]['text'] = message[1]['fields'][0]['text'].format(
            readings=measurements_to_str(sensor_status.measurements[1:])
        )
        message[1]['fields'][1]['text'] = message[1]['fields'][1]['text'].format(
            is_resolved='*Resolved by:*',
            resolved_reading = measurement_to_str(sensor_status.measurements[0])
        )
    else:
        message[0]['text']['text'] = message[0]['text']['text'].format(
            at_channel='' if sensor_status.overall == 1 else '<!channel>',
            sensor_name=sensor_name,
            status_phrase='is alarming!' if sensor_status.overall == 2 else 'is missing heartbeat check-ins!',
            home_tab_url=module_config['home_tab_url']
        )
        message[1]['fields'][0]['text'] = message[1]['fields'][0]['text'].format(
            readings=measurements_to_str(sensor_status.measurements)
        )
        message[1]['fields'][1]['text'] = message[1]['fields'][1]['text'].format(
            is_resolved='',
            resolved_reading = ''
        )
    return message

def slack_alert(db_con, sensor_name: str, sensor_status: SensorStatus) -> None:
    """
    Given a sensor name and the updated sensor status, creates or updates
    the status message.
    """
    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    with db_con:
        sensor_id = db_con.execute("SELECT id FROM sensors WHERE name=?;", (sensor_name,)).fetchone()[0]
        # Check to see if there is an inflight item
        inflight = db_con.execute("SELECT id, status, slack_ts FROM alerts WHERE sensor=? AND inflight=1 LIMIT 1", (sensor_id,)).fetchone()
        if inflight is not None:
            # Check if we need to finalize this alert.
            if inflight[1] != sensor_status.overall:
                module_config['slack_client'].chat_update(
                    channel=module_config['channel_id'],
                    ts=inflight[2],
                    blocks=build_alert_message(sensor_name, sensor_status, inflight[1])
                )
                db_con.execute("UPDATE alerts SET last_timestamp=?, inflight=0 WHERE id=?", (
                    now,
                    inflight[0]
                ))
            else:
                # Just update the alert
                module_config['slack_client'].chat_update(
                    channel=module_config['channel_id'],
                    ts=inflight[2],
                    blocks=build_alert_message(sensor_name, sensor_status, inflight[1])
                )
                db_con.execute("UPDATE alerts SET last_timestamp=? WHERE id=?", (
                    datetime.datetime.now(datetime.timezone.utc).isoformat(),
                    inflight[0]
                ))
        if sensor_status.overall == 0:
            # We're done here
            return

        if inflight is None or (inflight is not None and inflight[1] != sensor_status.overall):
            # Start new alert
            new_alert = module_config['slack_client'].chat_postMessage(
                channel=module_config['channel_id'],
                blocks=build_alert_message(sensor_name, sensor_status, sensor_status.overall)
            )
            db_con.execute("INSERT INTO alerts(sensor, status, slack_ts, initial_timestamp, last_timestamp, inflight) VALUES (?,?,?,?,?,1)",(
                sensor_id,
                sensor_status.overall,
                new_alert['ts'],
                now,
                now,
            ))
        
@loader.timer
def status_updates(_):
    db_con = sqlite3.connect('sensors.db')
    check_status_alerts(db_con)
    db_con.close()
    return 60 * 5


BASE_HOME_TAB_MODEL = [
    {
        "type": "header",
        "text": {
            "type": "plain_text",
            "text": "Sensor status"
        }
    },
    {
        "type": "divider"
    }
]



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
    status_mapping = {0: ':large_green_circle:', 1:':large_yellow_circle:', 2: ':red_circle:'}
    str_delta = readable_delta(timestamp, datetime.datetime.now(datetime.timezone.utc))
    return {
        "type": "section",
        "text": {
            "type": "mrkdwn",
            "text": f"{status_mapping[status]}\t*{sensor_name}*\t\t_last update {str_delta}_\n\t\t *Temperature:* {temp:.1f}C"
        },
        #"accessory": {
        #    "type": "image",
        #    "image_url": "https://gallowaylabmit.github.io/protocols",
        #    "alt_text": "Temperature graph not avaliable"
        #}
    }

@loader.home_tab
def dev_tools_home_tab(user):
    # Ignores the user, displaying the same thing
    # for everyone
    home_tab_blocks = BASE_HOME_TAB_MODEL.copy()
    db_con = sqlite3.connect('sensors.db')
    status_dict = check_status_alerts(db_con, False) # prevent infinite loop in home tab
    for id, name in db_con.execute("SELECT id, name FROM sensors WHERE type=0"):
        cursor = db_con.cursor()
        cursor.execute("SELECT timestamp, measurement FROM temperature_measurements WHERE sensor=? ORDER BY timestamp DESC", (id,))
        row = cursor.fetchone()
        if row is not None:
            timestamp = datetime.datetime.fromisoformat(row[0])
            temp = float(row[1])
            home_tab_blocks.append(generate_sensor_status_item(name, status_dict[name].overall, timestamp, temp))
        cursor.close()
    db_con.close()
    return home_tab_blocks
