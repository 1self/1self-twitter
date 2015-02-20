DEBUG = True

import os
BASE_DIR = os.path.abspath(os.path.dirname(__file__))

# Application threads. A common general assumption is
# using 2 per available processor cores - to handle
# incoming requests using one and performing background
# operations using the other.
THREADS_PER_PAGE = int(os.getenv('THREADS_PER_PAGE'))

# Enable protection agains *Cross-site Request Forgery (CSRF)*
CSRF_ENABLED     = bool(os.getenv('CSRF_ENABLED'))

# Use a secure, unique and absolutely secret key for
# signing the data. 
CSRF_SESSION_KEY = os.getenv('CSRF_SESSION_KEY')

# Secret key for signing cookies
SECRET_KEY = os.getenv('SECRET_KEY')

#Hosting
HOST_ADDRESS = os.getenv('HOST_ADDRESS')

#Twitter credentials
CONSUMER_KEY = os.getenv('CONSUMER_KEY')
CONSUMER_SECRET = os.getenv('CONSUMER_SECRET')
CALLBACK_URL = os.getenv('CALLBACK_URL')

#1self credentials
APP_NAME = "1self-twitter"
APP_VERSION = "0.0.1"
ACTION_TAGS = ["tweet"]
OBJECT_TAGS = ["tweets"]

API_URL = os.getenv('API_URL')
APP_ID = os.getenv('APP_ID')
APP_SECRET = os.getenv('APP_SECRET')