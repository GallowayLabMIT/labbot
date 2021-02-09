import os
import csv
import re

os.getcwd()
os.chdir('test_logs/')

log_file = 'System_2020-11-10_18-52-23.log'
#Define regexes

User_dictionary = {
    'test' : 'test1'
}

event_done = re.compile('^Event:(?P<event>[^_]+)_Done')
function_in_process = re.compile('^Instrument function (?P<state>.+) executing line (?P<line>\d+)$')
event_start = re.compile('^Event:Starting_(?P<event>.+)$')
user_login = re.compile('login')
bubble_error = re.compile('^Data:New Bubble Detected')
big_bubble = re.compile('BUBBLE SIZE GREATER THAN THRESHOLD!!!')
aquisition_well = re.compile('^Acquisition initiated on well (?P<well>.+) Preload')
aquisition_tube= re.compile('^Acquisition initiated$')


with open(log_file) as log:
    csv_log = csv.DictReader(log, delimiter=',')
    csv_log.fieldnames = [
        'TimeStamp', 
        "LogType", 
        "User", 
        "Category", 
        "Message", 
        "unclearNumberString" ]

    for line in csv_log:

        
        result=event_start.match(line["Message"])
        if result != None:
            function = result.group("event")
            State = "Active"

        result=function_in_process.match(line["Message"])
        if result != None:
            function = result.group("state")
            lines = result.group("line")

        result=event_done.match(line["Message"])
        if result != None:
            function = result.group("event")
            State = "done"

        #result=user_login.match(line["Message"])
        #if result != None:
        #   User_ID = line["User"] 
        #    User = User_Dictionary[User_ID.lower()]

        result_well = aquisition_well.match(line["Message"])
        if result_well != None:
            last_well = result_well.group("well")
            print(last_well)
           

        

        result_tube = aquisition_tube.match(csv_log.__next__()["Message"])
        if result_tube != None and result_well == None:
            last_well = "tube"
            print(last_well)
            
        
        


        #result=bubble_error.match(line["Message"])
        #if result != None:
            #print('Bubble Error on well', last_well, '!') 
            

print(function, lines, State)