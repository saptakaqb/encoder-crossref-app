#!/bin/sh
set -e
nginx -g "daemon off;" &
exec uvicorn main:app --host 127.0.0.1 --port 8000 --workers 1
