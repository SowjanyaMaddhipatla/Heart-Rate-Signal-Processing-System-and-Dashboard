from fastapi import FastAPI, File, UploadFile, Request, Form
from fastapi.responses import HTMLResponse, JSONResponse, FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
import numpy as np
import soundfile as sf
from scipy.signal import butter, filtfilt, hilbert, find_peaks
import matplotlib.pyplot as plt
import tempfile, os, uuid, json, shutil

# uvicorn heartbeat_api:app --host 0.0.0.0 --port 8000
# --- Config ---
APP_TITLE = "Heartbeat Detection API with Dashboard (Session Folders)"
SAVE_ROOT = "results"   # root folder for sessions
os.makedirs(SAVE_ROOT, exist_ok=True)

app = FastAPI(title=APP_TITLE)

# Static + templates
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

# Utility: sanitize session id (allow hex only)
def safe_session_id(sid: str) -> str:
    if not sid or not all(c in "0123456789abcdef" for c in sid):
        raise ValueError("Invalid session id")
    return sid

# -------------------------
# Processing logic (session folder style)
# -------------------------
def process_heartbeat(file_path, session_id):
    """
    Loads WAV at file_path, processes, and writes:
      results/{session_id}/original.wav
      results/{session_id}/filtered.wav
      results/{session_id}/plot.png
      results/{session_id}/meta.json
    Returns metadata dict.
    """
    sess_folder = os.path.join(SAVE_ROOT, session_id)
    os.makedirs(sess_folder, exist_ok=True)

    y, Fs = sf.read(file_path)
    if y.ndim > 1:
        y = y[:, 0]
    # avoid all-zero
    if np.max(np.abs(y)) == 0:
        y = y + 1e-12
    y = y / np.max(np.abs(y))
    duration = len(y) / Fs

    # Save normalized original
    orig_path = os.path.join(sess_folder, "original.wav")
    sf.write(orig_path, y, Fs)

    # Bandpass filter (20–200 Hz)
    b, a = butter(2, [20, 200], btype="band", fs=Fs)
    try:
        y_filt = filtfilt(b, a, y)
    except Exception:
        # fallback: if filtfilt fails (short signal), use direct filter
        from scipy.signal import lfilter
        y_filt = lfilter(b, a, y)

    # Save filtered
    filt_path = os.path.join(sess_folder, "filtered.wav")
    sf.write(filt_path, y_filt, Fs)

    # Envelope via Hilbert transform
    env = np.abs(hilbert(y_filt))
    window_len = int(Fs * 0.05)
    if window_len < 1:
        window_len = 1
    env_smooth = np.convolve(env, np.ones(window_len) / window_len, mode="same")

    # Peak detection
    threshold = 0.3 * np.max(env_smooth)
    peaks, _ = find_peaks(env_smooth, height=threshold, distance=int(0.2 * Fs))

    # Group lub–dub pairs (keep peaks at least 0.6s apart)
    grouped = []
    for p in peaks:
        if not grouped or (p - grouped[-1]) > 0.6 * Fs:
            grouped.append(int(p))

    beats = np.array(grouped)
    bpm = len(beats) / (duration / 60) if duration > 0 else 0.0

    # Plot and save
    t = np.arange(len(y)) / Fs
    plot_path = os.path.join(sess_folder, "plot.png")

    plt.figure(figsize=(10, 6))
    plt.subplot(3, 1, 1)
    plt.plot(t, y, "gray")
    plt.title("Original Audio")
    plt.xlabel("Time [s]"); plt.ylabel("Amplitude")

    plt.subplot(3, 1, 2)
    plt.plot(t, y_filt, "b")
    plt.title("Filtered (20–200 Hz)")
    plt.xlabel("Time [s]")

    plt.subplot(3, 1, 3)
    plt.plot(t, env_smooth, "k", label="Envelope")
    if len(beats) > 0:
        plt.plot(np.array(beats)/Fs, env_smooth[beats]*1.05, "ro", label="Detected Beats")
    plt.title(f"Envelope & Beats | BPM ≈ {bpm:.1f}")
    plt.xlabel("Time [s]"); plt.ylabel("Amplitude")
    plt.legend()
    plt.tight_layout()
    plt.savefig(plot_path)
    plt.close()

    meta = {
        "Fs": int(Fs),
        "duration_sec": round(float(duration), 2),
        "threshold": float(threshold),
        "raw_peaks": int(len(peaks)),
        "beats_grouped": int(len(beats)),
        "bpm": round(float(bpm), 1),
        "files": {
            "original": "original.wav",
            "filtered": "filtered.wav",
            "plot": "plot.png"
        }
    }

    # Save meta.json
    meta_path = os.path.join(sess_folder, "meta.json")
    with open(meta_path, "w") as fh:
        json.dump(meta, fh, indent=2)

    return meta

# -------------------------
# Upload endpoint (unchanged behavior - expects multipart 'file')
# -------------------------
@app.post("/upload")
async def upload_wav(file: UploadFile = File(...)):
    if not file.filename.lower().endswith(".wav"):
        return JSONResponse(status_code=400, content={"error": "Only .wav files are supported"})

    session_id = uuid.uuid4().hex[:8]
    sess_folder = os.path.join(SAVE_ROOT, session_id)
    os.makedirs(sess_folder, exist_ok=True)

    # save raw temp in session folder
    tmp_path = os.path.join(sess_folder, "raw_upload.wav")
    with open(tmp_path, "wb") as f:
        f.write(await file.read())

    try:
        meta = process_heartbeat(tmp_path, session_id)
        # optionally remove raw_upload.wav to save space
        try:
            os.remove(tmp_path)
        except Exception:
            pass
        return {"session_id": session_id, **meta}
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})

# -------------------------
# Dashboard - list sessions
# -------------------------
@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    sessions = []
    for name in sorted(os.listdir(SAVE_ROOT), reverse=True):
        folder = os.path.join(SAVE_ROOT, name)
        if os.path.isdir(folder):
            meta_file = os.path.join(folder, "meta.json")
            if os.path.exists(meta_file):
                with open(meta_file) as fh:
                    meta = json.load(fh)
            else:
                meta = {}
            sessions.append({"id": name, "meta": meta})
    return templates.TemplateResponse("dashboard.html", {"request": request, "sessions": sessions})

# -------------------------
# Session detail page
# -------------------------
@app.get("/session/{session_id}", response_class=HTMLResponse)
async def session_page(request: Request, session_id: str):
    try:
        sid = safe_session_id(session_id)
    except ValueError:
        return JSONResponse(status_code=400, content={"error": "invalid session id"})
    folder = os.path.join(SAVE_ROOT, sid)
    if not os.path.isdir(folder):
        return JSONResponse(status_code=404, content={"error": "session not found"})
    meta = {}
    meta_file = os.path.join(folder, "meta.json")
    if os.path.exists(meta_file):
        with open(meta_file) as fh:
            meta = json.load(fh)
    # file URLs
    plot_url = f"/results/{sid}/plot.png"
    orig_url = f"/results/{sid}/original.wav"
    filt_url = f"/results/{sid}/filtered.wav"
    return templates.TemplateResponse("session.html", {"request": request, "id": sid, "meta": meta,
                                                       "plot_url": plot_url, "orig_url": orig_url, "filt_url": filt_url})

# -------------------------
# Serve results folder (session subfolders) as static
# -------------------------
app.mount("/results", StaticFiles(directory=SAVE_ROOT), name="results")

# -------------------------
# Delete session
# -------------------------
@app.post("/session/{session_id}/delete")
async def delete_session(session_id: str):
    try:
        sid = safe_session_id(session_id)
    except ValueError:
        return JSONResponse(status_code=400, content={"error": "invalid session id"})
    folder = os.path.join(SAVE_ROOT, sid)
    if not os.path.isdir(folder):
        return JSONResponse(status_code=404, content={"error": "session not found"})
    try:
        shutil.rmtree(folder)
        return {"status": "deleted", "session_id": sid}
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})

# -------------------------
# Rename session (POST form: new_id)
# -------------------------
@app.post("/session/{session_id}/rename")
async def rename_session(session_id: str, new_id: str = Form(...)):
    # new_id must be hex lowercase 8 chars or we will auto-generate a hex-safe slug
    try:
        sid = safe_session_id(session_id)
    except ValueError:
        return JSONResponse(status_code=400, content={"error": "invalid session id"})
    if not new_id:
        return JSONResponse(status_code=400, content={"error": "new_id required"})
    # sanitize new_id: keep only hex chars; if not length 8, pad/truncate
    new_clean = "".join(c for c in new_id.lower() if c in "0123456789abcdef")
    if len(new_clean) < 4:
        return JSONResponse(status_code=400, content={"error": "new_id too short (need at least 4 hex chars)"})
    new_clean = (new_clean + sid)[:8]  # ensure unique-ish 8 chars
    src = os.path.join(SAVE_ROOT, sid)
    dst = os.path.join(SAVE_ROOT, new_clean)
    if os.path.exists(dst):
        return JSONResponse(status_code=400, content={"error": "target id already exists"})
    try:
        os.rename(src, dst)
        return {"status": "renamed", "old": sid, "new": new_clean}
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})

# -------------------------
# Download session as ZIP
# -------------------------
@app.get("/session/{session_id}/download")
async def download_session(session_id: str):
    try:
        sid = safe_session_id(session_id)
    except ValueError:
        return JSONResponse(status_code=400, content={"error": "invalid session id"})
    folder = os.path.join(SAVE_ROOT, sid)
    if not os.path.isdir(folder):
        return JSONResponse(status_code=404, content={"error": "session not found"})
    # create temp zip
    tmp_zip = os.path.join(tempfile.gettempdir(), f"{sid}.zip")
    if os.path.exists(tmp_zip):
        os.remove(tmp_zip)
    shutil.make_archive(os.path.join(tempfile.gettempdir(), sid), 'zip', folder)
    return FileResponse(tmp_zip, media_type="application/zip", filename=f"{sid}.zip")

# -------------------------
# Session JSON API
# -------------------------
@app.get("/session/{session_id}/json")
async def session_json(session_id: str):
    try:
        sid = safe_session_id(session_id)
    except ValueError:
        return JSONResponse(status_code=400, content={"error": "invalid session id"})
    folder = os.path.join(SAVE_ROOT, sid)
    meta_file = os.path.join(folder, "meta.json")
    if not os.path.exists(meta_file):
        return JSONResponse(status_code=404, content={"error": "meta not found"})
    with open(meta_file) as fh:
        meta = json.load(fh)
    return {"session_id": sid, **meta}
