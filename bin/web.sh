#!/bin/sh

if [ "$FLASK_ENV" == "development" ]; then
        python app.py
else
        gunicorn app:app -w 3
fi