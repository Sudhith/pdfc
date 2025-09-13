#!/bin/bash
export FLASK_APP=app.py
export FLASK_ENV=production

# Run Flask app with Gunicorn (production-ready)
gunicorn app:app --bind 0.0.0.0:${PORT:-5000} --workers 3
