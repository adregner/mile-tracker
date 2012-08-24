#!/usr/bin/env python
import sys
import os
import re
import MySQLdb
import json
from calendar import HTMLCalendar
from googlemaps import GoogleMaps
from binascii import crc32
from datetime import date
import cgi
import cgitb
cgitb.enable()

GDATA_API_KEY = "AIzaSyB8MH1PUGs5fUYOTeU_uauklOkVT5wIXDs"

data = {}
if 'PATH_INFO' in os.environ:
    args = [a for a in os.environ['PATH_INFO'].split('/') if a]
else:
    args = []

db = MySQLdb.connect('localhost', 'therapy_user', 'w4rfotwuh4t', 'stacey_therapy')
cursor = db.cursor(MySQLdb.cursors.DictCursor)

def hash_visits(day):
    global db, cursor
    cursor.execute("SELECT address FROM visits v, destinations d WHERE v.day = %s AND v.dest_id = d.id ORDER BY v.time ASC", [day])
    running_hash = 0
    for v in cursor.fetchall():
        running_hash = crc32(v['address'], running_hash)
    return running_hash & 0xffffffff

if args and os.environ['REQUEST_METHOD'] == 'GET':
    if args[0] == 'day':
        day = args[1]
        cursor.execute("SELECT * FROM visits WHERE `day` = %s ORDER BY time ASC", [day])
        print "Content-type: application/json\r\n"
        visits = []
        for v in cursor.fetchall():
            v['day'] = str(v['day'])
            visits.append(v)
        print json.dumps(visits)
    
    elif args[0] == 'dest':
        cursor.execute("SELECT * FROM destinations")
        print "Content-type: application/json\r\n"
        destinations = {}
        for dest in cursor.fetchall():
            destinations[dest['id']] = dest
            destinations[dest['name']] = dest
        print json.dumps(destinations)
    
    elif args[0] == 'miles':
        day = args[1]
        cursor.execute("SELECT * FROM miles WHERE day = %s", [day])
        miles = cursor.fetchone()
        trip_hash = hash_visits(day)
        if not miles or trip_hash != miles['hash']:
            # regenerate the distances
            gmaps = GoogleMaps(GDATA_API_KEY)
            cursor.execute("SELECT * FROM visits v, destinations d WHERE v.day = %s AND v.dest_id = d.id ORDER BY v.time ASC", [day])
            meters = 0
            trip_hash = 0
            start = None
            miles = {'day':day}
            for visit in cursor.fetchall():
                trip_hash = crc32(visit['address'], trip_hash)
                if not start:
                    start = visit['address']
                    continue
                directions = gmaps.directions(start, visit['address'])
                meters += directions['Directions']['Distance']['meters']
                start = visit['address']
            miles['miles'] = int(meters * (1/1609.344))
            miles['hash'] = trip_hash & 0xffffffff
            cursor.execute("INSERT INTO miles (day, miles, hash) VALUES(%%s, %(miles)d, %(hash)d) ON DUPLICATE KEY UPDATE miles = %(miles)d, hash = %(hash)d" % miles, [day])
        else:
            miles['day'] = str(miles['day'])
        print "Content-type: application/json\r\n"
        print json.dumps(miles)
    
    elif args[0] == 'report.txt':
        print "Content-type: text/plain\r\n"
        #print "<title> MT Milage Report </title>"
        cursor.execute("SELECT * FROM miles m ORDER BY m.day ASC")
        stats = {'total':0, 'week':0}
        last_visit = None
        week_num = -1
        for visit in cursor.fetchall():
            new_week_num = int(visit['day'].strftime("%U"))
            if last_visit is not None and week_num != new_week_num:
                print '-----------------------------'
                print "Total miles this week: %(week)d" % stats
                print
                stats['week'] = 0
            print visit['day'].strftime("%A, %B %d %Y").ljust(28), '|', visit['miles']
            stats['week'] += visit['miles']
            stats['total'] += visit['miles']
            week_num = new_week_num
            last_visit = visit
        print '-----------------------------'
        print "Total miles this week: %(week)d" % stats
        print
        print
        print '============================='
        print '============================='
        print "Total miles: %(total)d" % stats
    
    elif args[0] == 'delete':
        if args[1] == 'dest':
            tablename = "destinations"
            redir = ''
        elif args[1] == 'visit':
            tablename = "visits"
            cursor.execute("SELECT day FROM visits WHERE id = %s", [args[2]])
            redir = "#%s" % cursor.fetchone()['day']
        cursor.execute("DELETE FROM %s WHERE id = %s" % (tablename, args[2]))
        cursor.execute("DELETE FROM miles WHERE miles = 0")
        print "Location: http://adr-bytes/therapy/distance.py%s\r\n" % redir
    
elif args and os.environ['REQUEST_METHOD'] == 'POST':
    form = cgi.FieldStorage()
    print "Content-type: text/plain"
    
    if args[0] == 'day':
        day = args[1]

    elif args[0] == 'dest':
        name = form.getvalue('name')
        address = form.getvalue('address')
        if ',' not in address:
            address += ", San Antonio, TX"
        cursor.execute("INSERT INTO destinations (name, address) VALUES(%s, %s)", (name, address))
        print "Location: http://adr-bytes/therapy/distance.py\r\n"

    elif args[0] == 'goto':
        dest_id = form.getvalue('dest')
        date = form.getvalue('date')
        cursor.execute("SELECT coalesce(max(time), 0)+1 as time FROM visits WHERE day = %s", [date])
        time = cursor.fetchone()['time']
        cursor.execute("INSERT INTO visits (day, dest_id, time) VALUES(%s, %s, %s)", [date, dest_id, time])
        print

else:
    data['calendar'] = re.sub('([SMTWF])(un|on|ue|ed|hu|ri|at)', '\\1', HTMLCalendar(6).formatyear(2012))
    data['destinations'] = []
    cursor.execute("SELECT * FROM destinations ORDER BY name ASC")
    for dest in cursor.fetchall():
        data['destinations'].append("<a href=\"distance.py/delete/dest/%(id)d\">x</a> <a href=\"javascript:;;\" onclick=\"select_dest(%(id)d)\"><b>%(name)s</b> -- %(address)s</a>" % dest)
    data['destinations'] = "<br>".join(data['destinations'])
    ## default UI
    print "Content-type: text/html\r\n\r\n"
    print """
    <title> MT Milage </title>
    <link type="text/css" rel="stylesheet" href="distance.css"/>
    <script type="text/javascript" src="http://ajax.googleapis.com/ajax/libs/prototype/1.7/prototype.js"></script>
    <script type="text/javascript" src="distance.js"></script>
    <div id="report"><a href="distance.py/report.txt">View Report</a></div>
    <div class="float">
    %(calendar)s
    <br/>
    <div class="dests">%(destinations)s</div>
    <div class="dests"><form method="post" action="distance.py/dest">
    <input type="text" name="name" size="10"/> <input type="text" name="address" size="50"/> <input type="submit" value="Add"/>
    </form></div>
    </div>
    <div class="float">
    <b>Journey (<span id=\"date\"></span>):</b>
    <br/><br/>
    <div id="visits"></div>
    <br/>
    <div id="distance"></div>
    </div>
    """ % data

cursor.close()
db.commit()
db.close()
