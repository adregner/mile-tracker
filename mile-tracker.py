#!/usr/bin/env python
import sys
import os
import re
import MySQLdb
import json
import hashlib
from calendar import HTMLCalendar
from googlemaps import GoogleMaps
from datetime import date, timedelta
from Crypto.Cipher import Blowfish
from Crypto import Random

from flask import Flask, app, render_template, g, session, request, flash, redirect, url_for, jsonify

APP_ROOT = os.path.abspath(os.path.dirname(__file__))

app = Flask(__name__)
app.debug = len(sys.argv) > 1 and sys.argv[1] == '--debug'
app.secret_key = '12345' if app.debug else Random.new().read(64)

GDATA_API_KEY = "AIzaSyB8MH1PUGs5fUYOTeU_uauklOkVT5wIXDs"

CONFIG = {}

@app.before_request
def pre_request_checks():
    # connect to the database
    g.db = MySQLdb.connect(*CONFIG['database'])
    g.cursor = g.db.cursor(MySQLdb.cursors.DictCursor)

    if session.get('logged_in'):
        # the key is their hashed password
        g.cursor.execute("SELECT password_hash FROM users WHERE id = %s", session['user_id'])
        key = g.cursor.fetchone()['password_hash']
        # build the cipher from that key
        g.cipher_bs = Blowfish.block_size
        g.iv = Random.new().read(g.cipher_bs)
        g.cipher = Blowfish.new(key, Blowfish.MODE_CBC, g.iv)
        # helpers
        g.user_id = session['user_id']

        if request.referrer and '/calendar' in request.referrer:
            refer_year = request.referrer.split('/')[-1]
            if refer_year.isdigit():
                g.refer_year = refer_year

def encrypt(plaintext):
    pad = g.cipher_bs - divmod(len(plaintext), g.cipher_bs)[1]
    pad *= '\x00'
    return g.iv + g.cipher.encrypt(plaintext + pad)

def decrypt(encoded):
    return g.cipher.decrypt(encoded)[g.cipher_bs:].strip('\x00')

@app.route('/')
def index():
    if session.get('logged_in'):
        return redirect(url_for('calendar'))
    else:
        return redirect(url_for('register'))

@app.route('/register')
def register():
    return render_template('register.html')

@app.route('/register/new', methods=['POST'])
def register_new():
    userin = {}
    for a in ('name', 'email', 'password', 'confirm'):
        userin[a] = request.form[a]

    if userin['password'] != userin['confirm']:
        flash("You typed in two different passwords, try again.")
        return redirect(url_for('register'))

    g.cursor.execute("SELECT id FROM users WHERE email = %s", userin['email'])
    if g.cursor.fetchone():
        flash("There is already an account with that email address.")
        return redirect(url_for('register'))

    password_hash = hashlib.sha224(userin['password']).hexdigest()

    g.cursor.execute("INSERT INTO users (name, email, home_city, password_hash) VALUES(%s, %s, %s, %s)",
            (userin['name'], userin['email'], userin['home_city'], password_hash))

    session['logged_in'] = True
    session['user_id'] = g.db.insert_id()
    session['home_city'] = userin['home_city']

    return redirect(url_for('calendar'))

@app.route('/register/login', methods=['POST'])
def register_login():
    g.cursor.execute("SELECT * FROM users WHERE email = %s", request.form['email'])
    user = g.cursor.fetchone()

    if not user:
        flash("There is no registered account with that email address.")
        return redirect(url_for('register'))

    if user['password_hash'] != hashlib.sha224(request.form['password']).hexdigest():
        flash("The password you entered is incorrect.")
        return redirect(url_for('register'))

    session['logged_in'] = True
    session['user_id'] = user['id']
    session['home_city'] = user['home_city']

    return redirect(url_for('calendar'))


@app.route('/calendar')
@app.route('/calendar/<year>/<month>')
def calendar(year=date.today().year, month=date.today().month):
    if not session.get('logged_in'):
        return redirect(url_for('register'))

    year, month = int(year), int(month)
    thismonth = date(year, month, 1)

    data = {}
    data['calendar_code'] = HTMLCalendar(6).formatmonth(year, month)
    data['calendar_code'] = re.sub('([SMTWF])(un|on|ue|ed|hu|ri|at)', '\\1', data['calendar_code'])

    data['destinations'] = get_decoded_destinations()

    data['year'] = year
    data['previous'] = thismonth - timedelta(1)
    data['next'] = thismonth + timedelta(32)

    return render_template('calendar.html', **data)

@app.route('/day/<date>')
def day(date):
    if not session.get('logged_in'):
        return redirect(url_for('register'))

    g.cursor.execute("SELECT * FROM visits WHERE `day` = %s AND user_id = %s ORDER BY time ASC", (date, g.user_id))
    visits = []
    for v in g.cursor.fetchall():
        v['day'] = str(v['day'])
        visits.append(v)
    return jsonify(visits=visits)

def get_decoded_destinations():
    destinations = []
    g.cursor.execute("SELECT * FROM destinations WHERE user_id = %s", g.user_id)
    for dest in g.cursor.fetchall():
        dest = decode_destination(dest)
        destinations.append(dest)
    return destinations

def decode_destination(dest):
    # decrypt it first
    decrypted_info = json.loads(decrypt(dest['encrypted_info']))
    del dest['encrypted_info'], dest['user_id']
    # use the destination data
    dest.update(decrypted_info)
    return dest

@app.route('/dest')
def destinations():
    if not session.get('logged_in'):
        return redirect(url_for('register'))

    destinations = {}
    g.cursor.execute("SELECT * FROM destinations WHERE user_id = %s", g.user_id)
    for dest in get_decoded_destinations():
        destinations[dest['id']] = dest
        destinations[dest['name']] = dest

    return jsonify(destinations=destinations)

@app.route('/dest', methods=['POST'])
def add_destination():
    if not session.get('logged_in'):
        return redirect(url_for('register'))

    name = request.form['name']
    address = request.form['address']
    if ',' not in address:
        address += ", %s" % session['home_city']

    encrypted_info = encrypt(json.dumps({'name':name, 'address':address}))

    g.cursor.execute("INSERT INTO destinations (encrypted_info, user_id) VALUES(%s, %s)", (encrypted_info, g.user_id))
    return redirect(url_for('calendar')) # TODO : what if they came from a previous year

@app.route('/visit', methods=['POST'])
def add_visit():
    if not session.get('logged_in'):
        return redirect(url_for('register'))

    dest_id = request.form['dest']
    date = request.form['date']
    g.cursor.execute("SELECT coalesce(max(time), 0)+1 as time FROM visits WHERE day = %s AND user_id = %s", [date, g.user_id])
    time = g.cursor.fetchone()['time']
    g.cursor.execute("INSERT INTO visits (day, dest_id, time, user_id) VALUES(%s, %s, %s, %s)", [date, dest_id, time, g.user_id])

    return 'ok' if g.db.insert_id() > 0 else 'error'

@app.route('/miles/<date>')
def miles(date):
    if not session.get('logged_in'):
        return redirect(url_for('register'))

    # look for any visits
    g.cursor.execute("SELECT * FROM visits v, destinations d WHERE v.day = %s AND v.dest_id = d.id AND v.user_id = %s ORDER BY v.time ASC", (date, g.user_id))
    visits = g.cursor.fetchall()

    if not visits:
        return jsonify(miles=0)

    gmaps = GoogleMaps(GDATA_API_KEY)

    # look for a cached count of the miles
    last_visit = None
    miles = 0.0
    for visit in visits:
        visit = decode_destination(visit)
        if last_visit is None:
            last_visit = visit
            continue
        g.cursor.execute("SELECT miles FROM miles WHERE start_dest_id = %s AND end_dest_id = %s", (last_visit['dest_id'], visit['dest_id']))
        trip_miles = g.cursor.fetchone()
        if trip_miles:
            miles += float(trip_miles['miles'])
        else:
            directions = gmaps.directions(last_visit['address'], visit['address'])
            trip_meters = directions['Directions']['Distance']['meters']
            trip_miles = int(trip_meters * (1/1609.344))
            miles += trip_miles
            g.cursor.execute("INSERT INTO miles (start_dest_id, end_dest_id, miles) VALUES(%s, %s, %s)", (last_visit['dest_id'], visit['dest_id'], trip_miles))
        last_visit = visit

    return jsonify(miles=miles)

@app.route('/report')
@app.route('/report/<year>')
def report(year=date.today().year):
    if not session.get('logged_in'):
        return redirect(url_for('register'))

    g.cursor.execute("""SELECT v1.day, SUM(m.miles) AS miles
            FROM visits v1, visits v2, miles m WHERE 
                v1.user_id = %s AND v2.user_id = v1.user_id AND
                m.start_dest_id = v1.dest_id AND m.end_dest_id = v2.dest_id AND
                v1.day = v2.day AND 
                v1.time + 1 = v2.time
            GROUP BY day ORDER BY v1.day, v1.time""", g.user_id)
    visits = g.cursor.fetchall()
    stats = {'total':0, 'week':0}
    weeks = {}
    last_visit = None
    week_num = -1
    for visit in visits:
        new_week_num = int(visit['day'].strftime("%U"))
        if new_week_num not in weeks:
            weeks[new_week_num] = {'total':int(visit['miles']), 'days':[]}
        if last_visit is not None and week_num != new_week_num:
            weeks[week_num]['total'] = stats['week']
            stats['week'] = 0
        weeks[new_week_num]['days'].append(
                {'day':visit['day'].strftime("%A, %B %d %Y"), 'miles':visit['miles']} )
        stats['week'] += visit['miles']
        stats['total'] += visit['miles']
        week_num = new_week_num
        last_visit = visit
    week_numbers = weeks.keys()
    week_numbers.sort()
    return render_template('report.html', weeks=weeks, week_numbers=week_numbers, total=stats['total'])

@app.route('/profile')
def profile():
    if not session.get('logged_in'):
        return redirect(url_for('register'))

    g.cursor.execute("SELECT * FROM users WHERE id = %s", g.user_id)
    user = g.cursor.fetchone()

    return render_template('profile.html', **user)

@app.route('/profile', methods=['POST'])
def profile_edit():
    if not session.get('logged_in'):
        return redirect(url_for('register'))

    g.cursor.execute("UPDATE users SET name = %s, home_city = %s WHERE id = %s", (request.form['name'], request.form['home_city'], g.user_id))

    flash("Changes have been saved.")
    return redirect(url_for('profile'))

@app.route('/delete/<model>/<id>')
def delete_model(model, the_id):
    if not session.get('logged_in'):
        return redirect(url_for('register'))

    if model == 'dest':
        tablename = "destinations"
        redir = ""
    elif model == 'visit':
        tablename = "visits"
        g.cursor.execute("SELECT day FROM visits WHERE id = %s", the_id)
        redir = "#%s" % g.cursor.fetchone()['day']
    else:
        abort(404, "invalid model")
    g.cursor.execute("DELETE FROM %s WHERE id = %%s" % tablename, the_id)
    g.cursor.execute("DELETE FROM miles WHERE miles = 0") #i don't remember why this is in here

    return redirect(url_for('calendar') + redir)

@app.after_request
def close_db(response):
    g.cursor.close()
    g.db.commit()
    g.db.close()
    return response

###########################################################
if __name__ == '__main__':
    CONFIG = json.load(open("%s/config.json" % APP_ROOT))
    app.run(host='0.0.0.0', port=5053)

