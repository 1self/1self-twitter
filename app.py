from flask import Flask, render_template, request, session, redirect, url_for
from birdy.twitter import UserClient
from datetime import datetime
from pymongo import MongoClient
import requests, json
import thread

app = Flask(__name__)
app.config.from_object('config')

CONSUMER_KEY = app.config['CONSUMER_KEY']
CONSUMER_SECRET = app.config['CONSUMER_SECRET']
HOST_ADDRESS = app.config['HOST_ADDRESS']
PORT=app.config['PORT']
CALLBACK_URL = app.config['CALLBACK_URL'] or HOST_ADDRESS + ":" + str(PORT) + "/callback"
API_URL = app.config['API_URL']
APP_URL = app.config['APP_URL']
MONGO_URI = app.config['MONGO_URI']
app.config['DEBUG'] = False

def increment(n):
	return n + 1

def parse_created_at(created_at):
	return datetime.strptime(created_at, '%a %b %d %H:%M:%S +0000 %Y')

def load_db_users():
	client = MongoClient(MONGO_URI)
	db = client.get_default_database()
	return db.users

def load_user_data(username):
	users = load_db_users()
	data = users.find_one({"username": username})
	return data

def load_last_since_id(username):
	id = 1
	data = load_user_data(username)
	if data != None and 'since_id' in data:
		id = data['since_id']
	return id

def save_last_since_id(username, id):
	user = load_user_data(username)
	if user is None:
		user = {}
	user["username"] = username
	user["since_id"] = id
	user["datetime"] = datetime.utcnow()
	return load_db_users().update({"username": username}, user, upsert=True)

def load_oauth_tokens(username):
	data = load_user_data(username)
	if data != None and 'oauth_token' in data and 'oauth_token_secret' in data:
		return data['oauth_token'], data['oauth_token_secret']
	else:
		return None

def save_ouath_token(username, oauth_token, oauth_token_secret):
	user = load_user_data(username)
	if user is None:
		user = {}
	user["username"] = username
	user["oauth_token"] = oauth_token
	user["oauth_token_secret"] = oauth_token_secret
	user["datetime"] = datetime.utcnow()
	return load_db_users().update({"username": username}, user, upsert=True)

def client_factory(key, secret, access_token=None, access_secret=None):
	if access_token is not None and access_secret is not None:
		return UserClient(key, secret, access_token, access_secret)
	else:
		return UserClient(key, secret)

def fetch_client_username(client):
	return client.api.account.settings.get().data['screen_name']

def fetch_client_followers_count(client):
	return len(client.api.followers.ids.get().data.ids)

def fetch_client_tweets(client, since_id=1):
	return client.api.statuses.user_timeline.get(since_id=since_id).data

def register_stream(oneself_username, registration_token, callback_url=None):
	url = API_URL + "/v1/users/" + oneself_username + "/streams"
	app_id = app.config['APP_ID']
	app_secret = app.config['APP_SECRET']
	auth_string = app_id + ":" + app_secret
	body=""
	if callback_url is not None:
		body = json.dumps({"callbackUrl": callback_url})
	headers = {"Authorization": auth_string, "registration-token": registration_token, "Content-Type": "application/json"}
	r = requests.post(url, headers=headers, data=body)
	try:
		response = json.loads(r.text)
		return response, r.status_code
	except ValueError:
		return r.text, r.status_code

def create_start_sync_event(source):
	event = {"dateTime": datetime.now().isoformat(), "objectTags": ["sync"], "actionTags": ["start"], "properties": {"source": source}}
	return event

def create_sync_complete_event(source):
	event = {"dateTime": datetime.now().isoformat(), "objectTags": ["sync"], "actionTags": ["complete"], "properties": {"source": source}}
	return event

def create_sync_error_event(status):
	event = {"dateTime": datetime.now().isoformat(), "objectTags": ["sync"], "actionTags": ["Error"], "properties": {"source": "twitter", "code": status}}
	return event

def create_tweets_events(tweets):
	def zeroPadNumber(num, length):
		pad = length - len(str(num))
		return "0"*pad + str(num)
	
	if len(tweets) == 0:
		return []
	events = []

	for tweet in tweets:
		date = parse_created_at(tweet.created_at).isoformat()
		event = {}
		event['source'] = app.config['APP_NAME']
		event['version'] = app.config['APP_VERSION']
		event['actionTags'] = app.config['ACTION_TAGS']
		event['objectTags'] = app.config['OBJECT_TAGS']
		event['dateTime'] = date
		event['properties'] = {"retweets": tweet['retweet_count'], "favorites": tweet[u'favorite_count']}
		#Sort numbers as padded strings to avoid mongo precision limits
		event['latestSyncField'] = zeroPadNumber(tweet.id, 25)
		events.append(event)
	return events

def send_event(event, stream):
	url = API_URL + "/v1/streams/" + stream['streamid'] + "/events"
	headers = {"Authorization": stream['writeToken'], "Content-Type": "application/json"}
	r = requests.post(url, data=json.dumps(event), headers=headers)
	try:
		response = json.loads(r.text)
		return response, r.status_code
	except ValueError:
		return r.text, r.status_code

def send_batch_events(events, stream):
	if len(events) == 0:
		return None
	url = API_URL + "/v1/streams/" + stream['streamid'] + "/events/batch"
	headers = {"Authorization": stream['writeToken'], "Content-Type": "application/json"}
	r = requests.post(url, data=json.dumps(events), headers=headers)
	try:
		response = json.loads(r.text)
		return response, r.status_code
	except ValueError:
		return r.text, r.status_code

def build_graph_url(stream):
	objectTags = app.config['OBJECT_TAGS']
	actionTags = app.config['ACTION_TAGS']
	def strigify_tags(tags):
		return str(",".join(tags))

	url = API_URL + u"/v1/streams/" + stream['streamid'] + "/events/tweets/tweet/count/daily/barchart?readToken=" + stream['readToken'] + "&bgColor=00acee";
	return url

@app.route("/")
def index():
	oneself_username = request.args.get('username')
	registration_token = request.args.get('token')
	session['oneself_username'] = oneself_username
	session['registration_token'] = registration_token
	client = client_factory(CONSUMER_KEY, CONSUMER_SECRET)
	token = client.get_signin_token(CALLBACK_URL)
	app.config['ACCESS_TOKEN'] = token.oauth_token
	app.config['ACCESS_TOKEN_SECRET'] = token.oauth_token_secret
	return redirect(token.auth_url)

@app.route('/callback')
def callback():
	return redirect(url_for('setup', **request.args))

def sync(username, lastSyncId, stream):
	try:
		token, secret = load_oauth_tokens(username)
	except TypeError:
		errorEvent = create_sync_error_event(401)
		send_event(errorEvent, stream)
		return 401

	client = client_factory(CONSUMER_KEY, CONSUMER_SECRET, token, secret)

	startEvent = create_start_sync_event(source="twitter")
	send_event(startEvent, stream)
	tweets = fetch_client_tweets(client, lastSyncId)
	events = create_tweets_events(tweets)
	send_batch_events(events, stream)
	endEvent = create_sync_complete_event(source="twitter")
	send_event(endEvent, stream)
	return 200

@app.route('/api/sync')
def api_sync():
	username = request.args.get('username')
	lastSyncId = request.args.get('latestSyncField')
	streamId = request.args.get('streamid')
	writeToken = request.headers.get('authorization')

	stream = {'streamid': streamId, 'writeToken': writeToken}
	
	def unpad_zero(id):
		return id.lstrip('0')

	thread.start_new_thread(sync, (username, unpad_zero(lastSyncId), stream))
	print(build_graph_url(stream))

	return "Sync", 200

@app.route('/api/setup')
def setup():
	print("in setup")
	OAUTH_VERIFIER = request.args.get('oauth_verifier')
	client = client_factory(CONSUMER_KEY, CONSUMER_SECRET,
		app.config['ACCESS_TOKEN'], app.config['ACCESS_TOKEN_SECRET'])
	token = client.get_access_token(OAUTH_VERIFIER)

	username = fetch_client_username(client)
	save_ouath_token(username, token.oauth_token, token.oauth_token_secret)

	callback_url = HOST_ADDRESS + url_for("api_sync") + "?username=" + username + "&latestSyncField={{latestSyncField}}&streamid={{streamid}}"

	oneself_username = session['oneself_username']
	registration_token = session['registration_token']
	print(oneself_username)
	print(registration_token)
	stream, status = register_stream(oneself_username, registration_token, callback_url)
	if status is not 200:
		return stream, status

	thread.start_new_thread(sync, (username, "1", stream))
	print(build_graph_url(stream))

	#return render_template("tweets.html", url=build_graph_url(stream))
	integrations_url = APP_URL + "/integrations"
	print(integrations_url)
	return redirect(integrations_url)

if __name__ == "__main__":
    app.run(port=PORT)
