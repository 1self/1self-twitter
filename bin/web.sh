#!/bin/sh

if [ "$FLASK_ENV" = "development" ]
then
        env/bin/python app.py
else
        gunicorn app:app
fi
