from flask import Flask, render_template, views, request, redirect
from birdy.twitter import UserClient
from datetime import datetime
from pymongo import MongoClient
import requests, json

app = Flask(__name__)
app.config.from_object('config')

CONSUMER_KEY = app.config['CONSUMER_KEY']
CONSUMER_SECRET = app.config['CONSUMER_SECRET']
CALLBACK_URL = app.config['CALLBACK_URL']

def parse_created_at(created_at):
	return datetime.strptime(created_at, '%a %b %d %H:%M:%S +0000 %Y')

def fetch_db_docs():
	client = MongoClient()
	db = client['1self-twitter']
	return db.docs

def fetch_user_data(username):
	docs = fetch_db_docs()
	data = docs.find_one({"username": username})
	return data

def get_last_since_id(username):
	id = 1
	data = fetch_user_data(username)
	if data != None and 'since_id' in data:
		id = data['since_id']
	return id

def set_last_since_id(username, id):
	doc = fetch_user_data(username)
	if doc == None:
		doc = {}
	doc["username"] = username
	doc["since_id"] = id
	doc["datetime"] = datetime.utcnow()
	return docs.update({"username": username}, doc, upsert=True)

def fetch_oauth_tokens(username):
	data = fetch_user_data(username)
	if data != None and 'oauth_token' in data and 'oauth_token_secret' in data:
		return data['oauth_token'], data['oauth_token_secret']
	else:
		return None

def save_ouath_token(username, oauth_token, oauth_token_secret):
	doc = fetch_user_data(username)
	if doc == None:
		doc = {}
	doc["username"] = username
	doc["oauth_token"] = oauth_token
	doc["oauth_token_secret"] = oauth_token_secret
	doc["datetime"] = datetime.utcnow()
	return fetch_db_docs().update({"username": username}, doc, upsert=True)

def register_stream():
	url = app.config['API_URL'] + "/v1/streams"
	app_id = app.config['APP_ID']
	app_secret = app.config['APP_SECRET']
	auth_string = app_id + ":" + app_secret
	headers = {"Authorization": auth_string}
	r = requests.post(url, headers=headers)
	try:
		response = json.loads(r.text)
		return response, r.status_code
	except ValueError:
		return r.text, r.status_code

def build_events(counts):
	if len(counts) == 0:
		return []
	events = []

	for key in counts:
		date = key.isoformat()
		event = {}
		event['source'] = app.config['APP_NAME']
		event['version'] = app.config['APP_VERSION']
		event['actionTags'] = app.config['ACTION_TAGS']
		event['objectTags'] = app.config['OBJECT_TAGS']
		event['dateTime'] = date
		event['properties'] = {"count": counts[key]}
		events.append(event)
	return events

def send_batch_events(events, stream):
	if len(events) == 0:
		return None
	url = app.config['API_URL'] + "/v1/streams/" + stream['streamid'] + "/events/batch"
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

	url = app.config['API_URL'] + u"/v1/streams/" + stream['streamid'] + "/events/tweets/tweet/sum(count)/daily/barchart?readToken=" + stream['readToken'] + "&bgColor=00acee";

	return url

def increment(n):
	return n + 1

@app.route("/")
def index():
	return render_template("index.html")

@app.route('/login', methods=['GET', 'POST'])
def login():
	client = UserClient(CONSUMER_KEY, CONSUMER_SECRET)
	token = client.get_signin_token(CALLBACK_URL)
	app.config['ACCESS_TOKEN'] = token.oauth_token
	app.config['ACCESS_TOKEN_SECRET'] = token.oauth_token_secret
	return redirect(token.auth_url)

@app.route('/callback')
def callback():
	OAUTH_VERIFIER = request.args.get('oauth_verifier')
	client = UserClient(CONSUMER_KEY, CONSUMER_SECRET,
		app.config['ACCESS_TOKEN'], app.config['ACCESS_TOKEN_SECRET'])
	token = client.get_access_token(OAUTH_VERIFIER)

	username = client.api.account.settings.get().data['screen_name']
	save_ouath_token(username, token.oauth_token, token.oauth_token_secret)
	
	response = client.api.statuses.user_timeline.get(since_id=get_last_since_id(username))
	dates = [parse_created_at(tweet.created_at).date() for tweet in response.data]
	ids = [int(tweet.id) for tweet in response.data]
	if len(ids) > 0:
		set_last_since_id(username, max(ids))

	counts = {}
	for date in dates:
		if date in counts:
			counts[date] = increment(counts[date])
		else:
			counts[date] = 1

	stream, status = register_stream()
	print(send_batch_events(build_events(counts), stream))
	print(fetch_oauth_tokens(username))

	return render_template("tweets.html", counts=counts, username=username, url=build_graph_url(stream))

if __name__ == "__main__":
    app.run()