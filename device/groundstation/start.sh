#!/usr/bin/env bash
export DISPLAY="${DISPLAY:-:0}"
source /home/pi/Desktop/venv/bin/activate
cd /home/pi/Desktop/drone_ground_station
python main.py

