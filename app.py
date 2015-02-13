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

def get_last_since_id(username):
	id = 1
	client = MongoClient()
	db = client['1self-twitter']
	posts = db.posts
	data = posts.find_one({"username": username})
	if data != None and 'since_id' in data:
		id = data['since_id']
	return id

def set_last_since_id(username, id):
	client = MongoClient()
	db = client['1self-twitter']
	posts = db.posts
	post = posts.find_one({"username": username})
	if post == None:
		post = {}
	post["username"] = username
	post["since_id"] = id
	post["datetime"] = datetime.utcnow()
	return posts.update({"username": username}, post, upsert=True)

def save_ouath_token(username, oauth_token, oauth_token_secret):
	client = MongoClient()
	db = client['1self-twitter']
	posts = db.posts
	post = posts.find_one({"username": username})
	if post == None:
		post = {}
	post["username"] = username 
	post["oauth_token"] = oauth_token
	post["oauth_token_secret"] = oauth_token_secret
	post["datetime"] = datetime.utcnow()
	return posts.update({"username": username}, post, upsert=True)

def register_stream():
	url = app.config['API_URL'] + "/v1/streams"
	app_id = app.config['APP_ID']
	app_secret = app.config['APP_SECRET']
	auth_string = app_id + ":" + app_secret
	headers = {"Authorization": auth_string}
	r = requests.post(url, headers=headers)
	return json.loads(r.text)

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
		if str(date) in counts:
			counts[str(date)] = counts[str(date)] + 1
		else:
			counts[str(date)] = 1
	print(register_stream())

	return render_template("tweets.html", counts=counts, username=username)

if __name__ == "__main__":
    app.run()