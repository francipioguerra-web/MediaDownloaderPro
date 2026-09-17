#!/usr/bin/env python3
"""
StreamingCommunity - Standalone Dedicated Watch Party Hub
Leggero, ultra-veloce e progettato per il deploy gratuito su Render.
Gestisce esclusivamente:
- Creazione e sincronizzazione stanze Watch Party in tempo reale
- Polling inviti pendenti tra profili
- Sincronizzazione playback (play/pause/seek/cambio episodio)
- Gestione e bundle dati profili utente
"""

import os
import sys
import json
import time
import uuid
import shutil
import threading
from flask import Flask, request, jsonify, make_response, Response

app = Flask(__name__)

# Base directories
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SEED_DIR = os.path.join(BASE_DIR, "user_data_seed")
DATA_DIR = os.environ.get("DATA_DIR", os.path.join(BASE_DIR, "data"))
os.makedirs(DATA_DIR, exist_ok=True)

PROFILES_FILE = os.path.join(DATA_DIR, "profiles.json")
WATCHPARTY_FILE = os.path.join(DATA_DIR, "watchparty.json")
FAVORITES_FILE = os.path.join(DATA_DIR, "favorites.json")
HISTORY_FILE = os.path.join(DATA_DIR, "history.json")

DATA_LOCK = threading.RLock()

try:
    import seed_data
except ImportError:
    seed_data = None

def init_file_from_seed(target_path, seed_name, default_val):
    need_init = not os.path.exists(target_path) or os.path.getsize(target_path) == 0
    if not need_init:
        # Also check if it's an empty json
        try:
            with open(target_path, "r", encoding="utf-8") as f:
                content = json.load(f)
                if isinstance(content, dict) and "profiles" in content and len(content["profiles"]) == 0:
                    need_init = True
        except Exception:
            need_init = True

    if need_init:
        seed_path = os.path.join(SEED_DIR, seed_name)
        if os.path.exists(seed_path):
            try:
                shutil.copyfile(seed_path, target_path)
                return
            except Exception as e:
                print(f"Error copying seed {seed_name}: {e}")
        # Fallback to in-memory seed_data if available
        if seed_data:
            if seed_name == "profiles.json" and getattr(seed_data, "PROFILES_DATA", None):
                default_val = seed_data.PROFILES_DATA
            elif seed_name == "favorites.json" and getattr(seed_data, "FAVORITES_DATA", None):
                default_val = seed_data.FAVORITES_DATA
            elif seed_name == "history.json" and getattr(seed_data, "HISTORY_DATA", None):
                default_val = seed_data.HISTORY_DATA
            elif seed_name == "dates_cache.json" and getattr(seed_data, "DATES_CACHE_DATA", None):
                default_val = seed_data.DATES_CACHE_DATA
        try:
            with open(target_path, "w", encoding="utf-8") as f:
                json.dump(default_val, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"Error initializing {target_path}: {e}")

# Initialize files
init_file_from_seed(PROFILES_FILE, "profiles.json", {"active_profile_id": None, "profiles": []})
init_file_from_seed(WATCHPARTY_FILE, "watchparty.json", {"sessions": []})
init_file_from_seed(FAVORITES_FILE, "favorites.json", {})
init_file_from_seed(HISTORY_FILE, "history.json", [])

def read_json(path, default_val):
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return default_val

def write_json_safe(path, data):
    try:
        temp_path = f"{path}.tmp"
        with open(temp_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(temp_path, path)
    except Exception as e:
        print(f"Error writing to {path}: {e}")

# ----------------- CORS SUPPORT -----------------
@app.after_request
def add_cors_headers(response):
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, DELETE, OPTIONS"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization, X-Requested-With"
    return response

@app.route('/', defaults={'path': ''}, methods=['OPTIONS'])
@app.route('/<path:path>', methods=['OPTIONS'])
def options_preflight(path):
    res = Response("", status=204)
    res.headers["Access-Control-Allow-Origin"] = "*"
    res.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, DELETE, OPTIONS"
    res.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization, X-Requested-With"
    return res

# ----------------- CLEANUP HELPERS -----------------
def cleanup_old_sessions(data):
    now = time.time() * 1000
    max_age = 3600000 * 3  # 3 ore
    data["sessions"] = [s for s in data.get("sessions", []) if (now - s.get("created_at", 0)) < max_age]
    return data

# ----------------- HOME & HEALTH -----------------
@app.route('/')
def home():
    accept = request.headers.get("Accept", "")
    data = read_json(WATCHPARTY_FILE, {"sessions": []})
    active_count = len([s for s in data.get("sessions", []) if s.get("status") in ("waiting", "active")])
    profiles_data = read_json(PROFILES_FILE, {"profiles": []})
    prof_names = [p.get("name", "Profilo") for p in profiles_data.get("profiles", [])]

    if "application/json" in accept and "text/html" not in accept:
        return jsonify({
            "status": "ok",
            "service": "StreamingCommunity WatchParty Hub",
            "version": "2.0.0",
            "active_rooms": active_count,
            "profiles": prof_names,
            "timestamp": int(time.time() * 1000)
        })

    # Dark-themed status dashboard
    profiles_badges = "".join([f'<span class="badge">{name}</span>' for name in prof_names]) or '<span class="badge">Nessun profilo caricato</span>'
    html = f"""<!DOCTYPE html>
<html lang="it">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>StreamingCommunity — Watch Party Hub</title>
  <style>
    :root {{
      --bg: #0b0d14;
      --card-bg: rgba(22, 27, 46, 0.7);
      --primary: #6366f1;
      --accent: #10b981;
      --text: #f3f4f6;
      --text-dim: #9ca3af;
      --border: rgba(255, 255, 255, 0.08);
    }}
    * {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
      background: var(--bg);
      color: var(--text);
      min-height: 100vh;
      display: flex;
      flex-direction: column;
      align-items: center;
      justify-content: center;
      padding: 20px;
      background-image: radial-gradient(circle at 50% 20%, rgba(99, 102, 241, 0.15), transparent 60%);
    }}
    .card {{
      background: var(--card-bg);
      border: 1px solid var(--border);
      border-radius: 20px;
      padding: 36px;
      max-width: 540px;
      width: 100%;
      box-shadow: 0 20px 40px rgba(0, 0, 0, 0.5);
      backdrop-filter: blur(16px);
      text-align: center;
    }}
    .pulse-dot {{
      display: inline-block;
      width: 12px;
      height: 12px;
      background: var(--accent);
      border-radius: 50%;
      margin-right: 8px;
      box-shadow: 0 0 12px var(--accent);
      animation: pulse 2s infinite;
    }}
    @keyframes pulse {{
      0% {{ transform: scale(0.95); opacity: 0.8; }}
      50% {{ transform: scale(1.2); opacity: 1; }}
      100% {{ transform: scale(0.95); opacity: 0.8; }}
    }}
    h1 {{ font-size: 1.6rem; font-weight: 700; margin-bottom: 8px; letter-spacing: -0.5px; }}
    p.subtitle {{ color: var(--text-dim); font-size: 0.95rem; margin-bottom: 24px; }}
    .stats-grid {{
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 16px;
      margin-bottom: 24px;
    }}
    .stat-box {{
      background: rgba(255, 255, 255, 0.03);
      border: 1px solid var(--border);
      border-radius: 12px;
      padding: 16px;
    }}
    .stat-box .num {{ font-size: 1.8rem; font-weight: bold; color: var(--text); }}
    .stat-box .label {{ font-size: 0.8rem; color: var(--text-dim); text-transform: uppercase; margin-top: 4px; }}
    .section-title {{ font-size: 0.85rem; text-transform: uppercase; color: var(--text-dim); margin-bottom: 10px; font-weight: 600; text-align: left; }}
    .badge-container {{ display: flex; flex-wrap: wrap; gap: 8px; justify-content: center; margin-bottom: 24px; }}
    .badge {{
      background: rgba(99, 102, 241, 0.15);
      color: #a5b4fc;
      border: 1px solid rgba(99, 102, 241, 0.3);
      padding: 6px 14px;
      border-radius: 20px;
      font-size: 0.85rem;
      font-weight: 500;
    }}
    .footer {{ font-size: 0.8rem; color: var(--text-dim); }}
  </style>
</head>
<body>
  <div class="card">
    <div style="display: flex; align-items: center; justify-content: center; margin-bottom: 12px;">
      <span class="pulse-dot"></span>
      <span style="font-size: 0.85rem; color: var(--accent); font-weight: 600; text-transform: uppercase; letter-spacing: 1px;">Server Attivo & Operativo</span>
    </div>
    <h1>StreamingCommunity</h1>
    <p class="subtitle">Hub Dedicato Watch Party & Sincronizzazione</p>

    <div class="stats-grid">
      <div class="stat-box">
        <div class="num">{active_count}</div>
        <div class="label">Stanze Attive</div>
      </div>
      <div class="stat-box">
        <div class="num">{len(prof_names)}</div>
        <div class="label">Profili Sincronizzati</div>
      </div>
    </div>

    <div class="section-title">Profili Riconosciuti</div>
    <div class="badge-container">
      {profiles_badges}
    </div>

    <p class="footer">Questo server gestisce in tempo reale la sincronizzazione video e la chat di gruppo per l'app desktop e Android.</p>
  </div>
</body>
</html>
"""
    return html

@app.route('/health')
def health():
    return jsonify({"status": "ok", "service": "watchparty-hub", "timestamp": int(time.time() * 1000)})

# ----------------- PROFILES API -----------------
@app.route('/api/profiles', methods=['GET'])
def get_profiles():
    with DATA_LOCK:
        data = read_json(PROFILES_FILE, {"active_profile_id": None, "profiles": []})
        if (not data.get("profiles") or len(data.get("profiles", [])) < 2) and seed_data and getattr(seed_data, "PROFILES_DATA", None):
            data = dict(seed_data.PROFILES_DATA)
            write_json_safe(PROFILES_FILE, data)
        
        sanitized = []
        for p in data.get("profiles", []):
            sp = dict(p)
            sp["has_pin"] = bool(sp.get("pin"))
            sp.pop("pin", None)
            sp.pop("history", None)
            sp.pop("favorites", None)
            sanitized.append(sp)

        return jsonify({
            "active_profile_id": data.get("active_profile_id"),
            "profiles": sanitized
        })

# ----------------- WATCHPARTY ENDPOINTS -----------------
@app.route('/api/watchparty/create', methods=['POST'])
def watchparty_create():
    req = request.get_json(silent=True) or {}
    host_profile_id = req.get("host_profile_id")
    guest_profile_id = req.get("guest_profile_id")
    item = req.get("item")

    if not host_profile_id or not guest_profile_id or not item:
        return jsonify({"success": False, "error": "Parametri mancanti (host_profile_id, guest_profile_id, item)"}), 400

    profiles_data = read_json(PROFILES_FILE, {"profiles": []})
    if (not profiles_data.get("profiles") or len(profiles_data.get("profiles", [])) < 2) and seed_data and getattr(seed_data, "PROFILES_DATA", None):
        profiles_data = dict(seed_data.PROFILES_DATA)
        write_json_safe(PROFILES_FILE, profiles_data)

    profs = {p.get("id"): p for p in profiles_data.get("profiles", [])}
    if seed_data and getattr(seed_data, "PROFILES_DATA", None):
        for sp in seed_data.PROFILES_DATA.get("profiles", []):
            if sp.get("id") not in profs:
                profs[sp.get("id")] = sp

    host_prof = profs.get(host_profile_id, {})
    guest_prof = profs.get(guest_profile_id, {})

    host_name = req.get("host_name") or host_prof.get("name", "Host")
    host_avatar = req.get("host_avatar") or host_prof.get("avatar", "")
    guest_name = req.get("guest_name") or guest_prof.get("name", "Guest")
    guest_avatar = req.get("guest_avatar") or guest_prof.get("avatar", "")

    session_id = f"wp_{int(time.time())}_{uuid.uuid4().hex[:8]}"

    with DATA_LOCK:
        data = cleanup_old_sessions(read_json(WATCHPARTY_FILE, {"sessions": []}))

        # Chiudi vecchie sessioni attive dello stesso host
        for s in data["sessions"]:
            if s.get("host_profile_id") == host_profile_id and s.get("status") in ("waiting", "active"):
                s["status"] = "ended"

        initial_time = 0.0
        try:
            initial_time = float(item.get("currentTime") or item.get("current_time") or 0)
        except Exception:
            initial_time = 0.0

        session = {
            "session_id": session_id,
            "host_profile_id": host_profile_id,
            "host_name": host_name,
            "host_avatar": host_avatar,
            "guest_profile_id": guest_profile_id,
            "guest_name": guest_name,
            "guest_avatar": guest_avatar,
            "item": item,
            "status": "waiting",
            "current_time": initial_time,
            "paused": True,
            "last_action": "create",
            "last_sync": int(time.time() * 1000),
            "created_at": int(time.time() * 1000)
        }

        data["sessions"].append(session)
        write_json_safe(WATCHPARTY_FILE, data)

    return jsonify({"success": True, "session_id": session_id, "session": session})

@app.route('/api/watchparty/pending', methods=['GET'])
def watchparty_pending():
    profile_id = request.args.get("profile_id")
    if not profile_id:
        return jsonify({"sessions": []})

    with DATA_LOCK:
        data = cleanup_old_sessions(read_json(WATCHPARTY_FILE, {"sessions": []}))
        pending = [s for s in data.get("sessions", [])
                   if s.get("guest_profile_id") == profile_id and s.get("status") == "waiting"]

    return jsonify({"sessions": pending})

@app.route('/api/watchparty/accept', methods=['POST'])
def watchparty_accept():
    req = request.get_json(silent=True) or {}
    session_id = req.get("session_id")
    if not session_id:
        return jsonify({"success": False, "error": "session_id mancante"}), 400

    with DATA_LOCK:
        data = read_json(WATCHPARTY_FILE, {"sessions": []})
        for s in data.get("sessions", []):
            if s.get("session_id") == session_id and s.get("status") == "waiting":
                s["status"] = "active"
                s["last_sync"] = int(time.time() * 1000)
                write_json_safe(WATCHPARTY_FILE, data)
                return jsonify({"success": True, "session": s})

    return jsonify({"success": False, "error": "Sessione non trovata"}), 404

@app.route('/api/watchparty/decline', methods=['POST'])
def watchparty_decline():
    req = request.get_json(silent=True) or {}
    session_id = req.get("session_id")
    if not session_id:
        return jsonify({"success": False, "error": "session_id mancante"}), 400

    with DATA_LOCK:
        data = read_json(WATCHPARTY_FILE, {"sessions": []})
        for s in data.get("sessions", []):
            if s.get("session_id") == session_id and s.get("status") == "waiting":
                s["status"] = "declined"
                write_json_safe(WATCHPARTY_FILE, data)
                return jsonify({"success": True})

    return jsonify({"success": False, "error": "Sessione non trovata"}), 404

@app.route('/api/watchparty/sync', methods=['POST'])
def watchparty_sync():
    req = request.get_json(silent=True) or {}
    session_id = req.get("session_id")
    if not session_id:
        return jsonify({"success": False, "error": "session_id mancante"}), 400

    with DATA_LOCK:
        data = read_json(WATCHPARTY_FILE, {"sessions": []})
        for s in data.get("sessions", []):
            if s.get("session_id") == session_id and s.get("status") == "active":
                if "current_time" in req:
                    s["current_time"] = max(0, float(req["current_time"]))
                if "paused" in req:
                    s["paused"] = bool(req["paused"])
                if req.get("stream_url"):
                    s["stream_url"] = str(req["stream_url"])[:2000]
                if isinstance(req.get("item"), dict):
                    allowed = ("id", "name", "title", "slug", "type", "poster",
                               "backdrop", "cover", "current_watch_url",
                               "current_episode_id", "current_episode_number",
                               "current_season_number", "current_ep_name",
                               "current_ep_title")
                    s["item"] = {k: req["item"].get(k) for k in allowed}
                s["last_action"] = req.get("action", req.get("last_action", "sync"))
                s["last_sync"] = int(time.time() * 1000)
                write_json_safe(WATCHPARTY_FILE, data)
                return jsonify({"success": True, "session": s})

    return jsonify({"success": False, "error": "Sessione non trovata o non attiva"}), 404

@app.route('/api/watchparty/state', methods=['GET'])
def watchparty_state():
    session_id = request.args.get("session_id")
    if not session_id:
        return jsonify({"success": False, "error": "session_id mancante"}), 400

    with DATA_LOCK:
        data = read_json(WATCHPARTY_FILE, {"sessions": []})
        for s in data.get("sessions", []):
            if s.get("session_id") == session_id:
                return jsonify({"success": True, "session": s})

    return jsonify({"success": False, "error": "Sessione non trovata"}), 404

@app.route('/api/watchparty/end', methods=['POST'])
def watchparty_end():
    req = request.get_json(silent=True) or {}
    session_id = req.get("session_id")
    if not session_id:
        return jsonify({"success": False, "error": "session_id mancante"}), 400

    with DATA_LOCK:
        data = read_json(WATCHPARTY_FILE, {"sessions": []})
        for s in data.get("sessions", []):
            if s.get("session_id") == session_id:
                s["status"] = "ended"
                write_json_safe(WATCHPARTY_FILE, data)
                return jsonify({"success": True})

    return jsonify({"success": False, "error": "Sessione non trovata"}), 404

# ----------------- USER DATA BUNDLE SYNC -----------------
@app.route('/api/user_data/bundle', methods=['GET'])
def get_user_data_bundle():
    try:
        profiles = read_json(PROFILES_FILE, {"profiles": []})
        if (not profiles.get("profiles") or len(profiles.get("profiles", [])) < 2) and seed_data and getattr(seed_data, "PROFILES_DATA", None):
            profiles = dict(seed_data.PROFILES_DATA)
            write_json_safe(PROFILES_FILE, profiles)

        favorites = read_json(FAVORITES_FILE, {})
        if not favorites and seed_data and getattr(seed_data, "FAVORITES_DATA", None):
            favorites = dict(seed_data.FAVORITES_DATA)
            write_json_safe(FAVORITES_FILE, favorites)

        history = read_json(HISTORY_FILE, [])
        if not history and seed_data and getattr(seed_data, "HISTORY_DATA", None):
            history = list(seed_data.HISTORY_DATA)
            write_json_safe(HISTORY_FILE, history)

        return jsonify({
            "success": True,
            "profiles": profiles,
            "favorites": favorites,
            "history": history
        })
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@app.route('/api/user_data/sync', methods=['POST'])
def sync_user_data():
    try:
        data = request.get_json() or {}
        with DATA_LOCK:
            if "profiles" in data and isinstance(data["profiles"], dict):
                write_json_safe(PROFILES_FILE, data["profiles"])
            if "favorites" in data and isinstance(data["favorites"], dict):
                write_json_safe(FAVORITES_FILE, data["favorites"])
            if "history" in data and isinstance(data["history"], list):
                write_json_safe(HISTORY_FILE, data["history"])
        return jsonify({"success": True, "message": "Dati utente sincronizzati con successo."})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5555))
    print(f"🚀 WatchParty Hub avviato su http://0.0.0.0:{port}")
    app.run(host="0.0.0.0", port=port, debug=False)
