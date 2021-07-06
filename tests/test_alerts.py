import argparse
import datetime
import sqlite3

parser = argparse.ArgumentParser()
parser.add_argument('step', choices=('valid_heartbeat_timeout', 'invalid_heartbeat_timeout', 'invalid_stale', 'valid_stale', 'valid', 'invalid', 'insert_valid', 'insert_invalid'))

def insert_measurement(db_con, now, delta_seconds, temp, battery):
    db_con.execute("INSERT INTO temperature_measurements(timestamp,received_timestamp, sensor,measurement,battery_level) VALUES (?,?,?,?,?)",(
        (now - datetime.timedelta(seconds=delta_seconds)).isoformat(),
        (now - datetime.timedelta(seconds=delta_seconds)).isoformat(),
        1,
        temp,
        battery
    ))

if __name__ == '__main__':
    args = parser.parse_args()
    db_con = sqlite3.connect('sensors.db')
    now = datetime.datetime.now(datetime.timezone.utc)
    with db_con:
        if not args.step.startswith('insert'):
            db_con.execute('DELETE FROM temperature_measurements')
            db_con.execute('DELETE FROM alerts')
        if args.step == 'valid_heartbeat_timeout':
            insert_measurement(db_con, now, 1900, -100, 94)
        elif args.step == 'invalid_heartbeat_timeout':
            insert_measurement(db_con, now, 1900, -50, 94)
        elif args.step == 'valid_stale':
            insert_measurement(db_con, now, 1400, -100, 94)
        elif args.step == 'invalid_stale':
            insert_measurement(db_con, now, 1400, -50, 94)
        elif args.step == 'valid':
            insert_measurement(db_con, now, 800, -100, 94)
            insert_measurement(db_con, now, 500, -100, 94)
        elif args.step == 'invalid':
            insert_measurement(db_con, now, 800, -50, 94)
            insert_measurement(db_con, now, 500, -50, 94)
        elif args.step == 'insert_valid':
            insert_measurement(db_con, now, 0, -100, 94)
        elif args.step == 'insert_invalid':
            insert_measurement(db_con, now, 0, -50, 94)