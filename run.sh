#!/bin/bash
cd "$HOME/lark-calendar"
exec flock -n /tmp/lark-cal.lock ./venv/bin/python 자동실행.py
