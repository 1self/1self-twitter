from flask import Flask, render_template, request, redirect, url_for
from birdy.twitter import UserClient
from datetime import datetime
from pymongo import MongoClient
import requests, json
import thread

app = Flask(__name__)
app.config.from_object('config')

CONSUMER_KEY = app.config['CONSUMER_KEY']
CONSUMER_SECRET = app.config['CONSUMER_SECRET']
CALLBACK_URL = app.config['CALLBACK_URL']

def increment(n):
	return n + 1

def parse_created_at(created_at):
	return datetime.strptime(created_at, '%a %b %d %H:%M:%S +0000 %Y')

def load_db_docs():
	client = MongoClient()
	db = client['1self-twitter']
	return db.docs

def load_user_data(username):
	docs = load_db_docs()
	data = docs.find_one({"username": username})
	return data

def load_last_since_id(username):
	id = 1
	data = load_user_data(username)
	if data != None and 'since_id' in data:
		id = data['since_id']
	return id

def save_last_since_id(username, id):
	doc = load_user_data(username)
	if doc == None:
		doc = {}
	doc["username"] = username
	doc["since_id"] = id
	doc["datetime"] = datetime.utcnow()
	return load_db_docs().update({"username": username}, doc, upsert=True)

def load_oauth_tokens(username):
	data = load_user_data(username)
	if data != None and 'oauth_token' in data and 'oauth_token_secret' in data:
		return data['oauth_token'], data['oauth_token_secret']
	else:
		return None

def save_ouath_token(username, oauth_token, oauth_token_secret):
	doc = load_user_data(username)
	if doc == None:
		doc = {}
	doc["username"] = username
	doc["oauth_token"] = oauth_token
	doc["oauth_token_secret"] = oauth_token_secret
	doc["datetime"] = datetime.utcnow()
	return load_db_docs().update({"username": username}, doc, upsert=True)

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

def register_stream(callback_url=None):
	url = app.config['API_URL'] + "/v1/streams"
	app_id = app.config['APP_ID']
	app_secret = app.config['APP_SECRET']
	auth_string = app_id + ":" + app_secret
	body=""
	if callback_url is not None:
		body = {"callbackUrl": callback_url}
	headers = {"Authorization": auth_string}
	r = requests.post(url, headers=headers, data=body)
	try:
		response = json.loads(r.text)
		return response, r.status_code
	except ValueError:
		return r.text, r.status_code

def create_start_sync_event():
	event = {"dateTime": datetime.now().isoformat(), "objectTags": ["sync"], "actionTags": ["start"], "properties": {"source": "twitter"}}
	return event

def create_sync_complete_event():
	event = {"dateTime": datetime.now().isoformat(), "objectTags": ["sync"], "actionTags": ["complete"], "properties": {"source": "twitter"}}
	return event

def zeroPadNumber(num, length):
	pad = length - len(str(num))
	return "0"*pad + str(num)

def create_tweets_events(tweets):
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
	url = app.config['API_URL'] + "/v1/streams/" + stream['streamid'] + "/events"
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
	url = app.config['API_URL'] + "/v1/streams/" + stream['streamid'] + "/events/batch"
	print(url)
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

	url = app.config['API_URL'] + u"/v1/streams/" + stream['streamid'] + "/events/tweets/tweet/count/daily/barchart?readToken=" + stream['readToken'] + "&bgColor=00acee";
	return url

@app.route("/")
def index():
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
		return "Auth error", 401

	client = client_factory(CONSUMER_KEY, CONSUMER_SECRET, token, secret)

	startEvent = create_start_sync_event()
	send_event(startEvent, stream)
	tweets = fetch_client_tweets(client, lastSyncId)
	events = create_tweets_events(tweets)
	send_batch_events(events, stream)
	endEvent = create_sync_complete_event()
	send_event(endEvent, stream)

@app.route('/api/sync')
def api_sync():
	username = request.args.get('username')
	lastSyncId = request.args.get('latestSyncField')
	streamId = request.args.get('streamid')
	writeToken = request.headers.get('authorization')

	stream = {'streamid': streamId, 'writeToken': writeToken}
	sync(username, lastSyncId, stream)

	return "Sync complete", 200

@app.route('/api/setup')
def setup():
	OAUTH_VERIFIER = request.args.get('oauth_verifier')
	client = client_factory(CONSUMER_KEY, CONSUMER_SECRET,
		app.config['ACCESS_TOKEN'], app.config['ACCESS_TOKEN_SECRET'])
	token = client.get_access_token(OAUTH_VERIFIER)

	username = fetch_client_username(client)
	save_ouath_token(username, token.oauth_token, token.oauth_token_secret)

	callback_url = "http://127.0.0.1:5000" + url_for("api_sync") + "?username="+username+"&latestSyncField={{latestSyncField}}&streamid={{streamid}}"

	stream, status = register_stream(callback_url)
	sync(username, "1", stream)

	return "Setup ok", 200

if __name__ == "__main__":
    app.run()
