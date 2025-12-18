# Heart-Rate-Signal-Processing-System-and-Dashboard

OVERVIEW :

Collected heart rate data via a sensor and uploaded .wav recordings (Code provided in folder Arduino ). Applied Python-based signal processing (bandpass filtering, envelope extraction, and peak detection) to identify heartbeats and compute metrics such as BPM, beat intervals, and signal quality. Automatically saved processed results and generated visual plots, which are displayed interactively on a web dashboard using FastAPI and Jinja2 templates, allowing session review, download, and management.

Features

1. Upload and analyze WAV recordings of heartbeats (can be uploaded manually from dashboard also ).
2. Compute heart rate, beat durations, and signal quality (SNR).
3. Visualize results with plots per session.
4. Supports multiple sessions with easy download of results.

-----------------------

Requirements : 

1. Python 3.12+
2. Packages:
   1. numpy
   2. scipy
   3. matplotlib
   4. soundfile
   5. fastapi
   6. jinja2
   7. uvicorn
-----------------------

Install dependencies with :
pip install -r requirements.txt

-----------------------
Running the Dashboard : 
1. Start the FastAPI server: uvicorn heartbeat_api:app --reload
2. Open : http://127.0.0.1:8000

-----------------------
To upload data : 
use any .wav file given in the folder samples.
