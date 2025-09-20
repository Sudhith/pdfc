#!/bin/bash

# Run gunicorn to serve the Flask app
exec gunicorn -b 0.0.0.0:$PORT app:app