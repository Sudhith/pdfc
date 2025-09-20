#!/bin/bash

# Ensure a sane default if PORT is not set
PORT="${PORT:-5000}"

# Run gunicorn to serve the Flask app
# exec so PID 1 is gunicorn and receives signals
exec gunicorn app:app --bind 0.0.0.0:${PORT} --workers 3