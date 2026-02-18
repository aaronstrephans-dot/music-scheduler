import json
import os
import uuid
from datetime import datetime

import ai
from engine.rotator import build_schedule
from engine.rules import merge_rules
from flask import Flask, jsonify, request

app = Flask(__name__)

SCHEDULES_DIR = os.path.join(os.path.dirname(__file__), "data", "schedules")
TRACKS_DIR    = os.path.join(os.path.dirname(__file__), "data", "tracks")
CLOCKS_DIR    = os.path.join(os.path.dirname(__file__), "data", "clocks")

for _d in (SCHEDULES_DIR, TRACKS_DIR, CLOCKS_DIR):
    os.makedirs(_d, exist_ok=True)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _load_all(directory: str) -> list:
    items = []
    for fname in os.listdir(directory):
        if fname.endswith(".json"):
            with open(os.path.join(directory, fname)) as f:
                items.append(json.load(f))
    return items


def _load_one(directory: str, item_id: str):
    path = os.path.join(directory, f"{item_id}.json")
    if not os.path.exists(path):
        return None
    with open(path) as f:
        return json.load(f)


def _save(directory: str, item: dict) -> None:
    with open(os.path.join(directory, f"{item['id']}.json"), "w") as f:
        json.dump(item, f, indent=2)


def _delete(directory: str, item_id: str) -> bool:
    path = os.path.join(directory, f"{item_id}.json")
    if not os.path.exists(path):
        return False
    os.remove(path)
    return True


def _now() -> str:
    return datetime.utcnow().isoformat() + "Z"


# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------

@app.route("/")
def index():
    return jsonify({
        "service":      "music-scheduler",
        "status":       "ok",
        "ai_available": ai.is_available(),
    })


# ---------------------------------------------------------------------------
# Tracks
# ---------------------------------------------------------------------------

_TRACK_REQUIRED = {"title", "artist", "category"}


@app.route("/api/tracks", methods=["GET"])
def list_tracks():
    tracks   = _load_all(TRACKS_DIR)
    category = request.args.get("category")
    if category:
        tracks = [t for t in tracks if t.get("category") == category]
    return jsonify(tracks)


@app.route("/api/tracks", methods=["POST"])
def create_track():
    data    = request.get_json(silent=True) or {}
    missing = _TRACK_REQUIRED - data.keys()
    if missing:
        return jsonify({"error": f"Missing required fields: {', '.join(sorted(missing))}"}), 400

    track = {
        "id":             str(uuid.uuid4()),
        "added_at":       _now(),
        "play_count":     0,
        "last_played_at": None,
        **{k: v for k, v in data.items() if k not in {"id", "added_at"}},
    }
    _save(TRACKS_DIR, track)
    return jsonify(track), 201


@app.route("/api/tracks/<track_id>", methods=["GET"])
def get_track(track_id):
    track = _load_one(TRACKS_DIR, track_id)
    if track is None:
        return jsonify({"error": "Track not found"}), 404
    return jsonify(track)


@app.route("/api/tracks/<track_id>", methods=["PUT"])
def update_track(track_id):
    track = _load_one(TRACKS_DIR, track_id)
    if track is None:
        return jsonify({"error": "Track not found"}), 404
    data = request.get_json(silent=True) or {}
    for key, val in data.items():
        if key not in {"id", "added_at"}:
            track[key] = val
    track["updated_at"] = _now()
    _save(TRACKS_DIR, track)
    return jsonify(track)


@app.route("/api/tracks/<track_id>", methods=["DELETE"])
def delete_track(track_id):
    if not _delete(TRACKS_DIR, track_id):
        return jsonify({"error": "Track not found"}), 404
    return "", 204


# ---------------------------------------------------------------------------
# Clock templates
# ---------------------------------------------------------------------------

@app.route("/api/clocks", methods=["GET"])
def list_clocks():
    return jsonify(_load_all(CLOCKS_DIR))


@app.route("/api/clocks", methods=["POST"])
def create_clock():
    data = request.get_json(silent=True) or {}
    if not data.get("name") or not data.get("slots"):
        return jsonify({"error": "Missing required fields: name, slots"}), 400

    clock = {
        "id":         str(uuid.uuid4()),
        "created_at": _now(),
        "updated_at": _now(),
        "name":       data["name"],
        "slots":      data["slots"],
    }
    _save(CLOCKS_DIR, clock)
    return jsonify(clock), 201


@app.route("/api/clocks/<clock_id>", methods=["GET"])
def get_clock(clock_id):
    clock = _load_one(CLOCKS_DIR, clock_id)
    if clock is None:
        return jsonify({"error": "Clock not found"}), 404
    return jsonify(clock)


@app.route("/api/clocks/<clock_id>", methods=["PUT"])
def update_clock(clock_id):
    clock = _load_one(CLOCKS_DIR, clock_id)
    if clock is None:
        return jsonify({"error": "Clock not found"}), 404
    data = request.get_json(silent=True) or {}
    for key, val in data.items():
        if key not in {"id", "created_at"}:
            clock[key] = val
    clock["updated_at"] = _now()
    _save(CLOCKS_DIR, clock)
    return jsonify(clock)


@app.route("/api/clocks/<clock_id>", methods=["DELETE"])
def delete_clock(clock_id):
    if not _delete(CLOCKS_DIR, clock_id):
        return jsonify({"error": "Clock not found"}), 404
    return "", 204


# ---------------------------------------------------------------------------
# Schedules
# ---------------------------------------------------------------------------

@app.route("/api/schedules", methods=["GET"])
def list_schedules():
    return jsonify(_load_all(SCHEDULES_DIR))


@app.route("/api/schedule/<schedule_id>", methods=["GET"])
def get_schedule(schedule_id):
    schedule = _load_one(SCHEDULES_DIR, schedule_id)
    if schedule is None:
        return jsonify({"error": "Schedule not found"}), 404
    return jsonify(schedule)


@app.route("/api/schedule/<schedule_id>", methods=["PUT"])
def update_schedule(schedule_id):
    schedule = _load_one(SCHEDULES_DIR, schedule_id)
    if schedule is None:
        return jsonify({"error": "Schedule not found"}), 404
    data = request.get_json(silent=True) or {}
    for key, val in data.items():
        if key not in {"id", "created_at"}:
            schedule[key] = val
    schedule["updated_at"] = _now()
    _save(SCHEDULES_DIR, schedule)
    return jsonify(schedule)


@app.route("/api/schedule/<schedule_id>", methods=["DELETE"])
def delete_schedule(schedule_id):
    if not _delete(SCHEDULES_DIR, schedule_id):
        return jsonify({"error": "Schedule not found"}), 404
    return "", 204


@app.route("/api/schedule/generate", methods=["POST"])
def generate_schedule():
    data     = request.get_json(silent=True) or {}
    clock_id = data.get("clock_id")

    if clock_id:
        # --- Rotation mode: build from clock template + track library ---
        clock = _load_one(CLOCKS_DIR, clock_id)
        if clock is None:
            return jsonify({"error": "Clock not found"}), 404

        tracks     = _load_all(TRACKS_DIR)
        rules      = merge_rules(data.get("rules") or {})
        track_list = build_schedule(clock, tracks, rules)

        schedule_id = str(uuid.uuid4())
        name        = (
            data.get("name")
            or f"{clock['name']} — {datetime.utcnow().strftime('%a %b %d')}"
        )
        schedule = {
            "id":               schedule_id,
            "created_at":       _now(),
            "name":             name,
            "clock_id":         clock_id,
            "clock_name":       clock.get("name"),
            "tracks":           track_list,
            "duration_minutes": sum((t.get("duration_seconds") or 0) for t in track_list) // 60,
            "rules":            rules,
        }
    else:
        # --- Manual mode (backwards-compatible) ---
        schedule_id = str(uuid.uuid4())
        schedule = {
            "id":               schedule_id,
            "created_at":       _now(),
            "name":             data.get("name", "Untitled Schedule"),
            "tracks":           data.get("tracks", []),
            "duration_minutes": data.get("duration_minutes", 60),
        }

    _save(SCHEDULES_DIR, schedule)
    return jsonify(schedule), 201


# ---------------------------------------------------------------------------
# AI-assisted routes (optional — require AI_PROVIDER env var)
# ---------------------------------------------------------------------------

def _no_ai():
    return jsonify({"error": "AI provider not configured", "ai_available": False}), 503


@app.route("/api/ai/schedule/analyze", methods=["POST"])
def ai_analyze_flow():
    provider = ai.get_provider()
    if provider is None:
        return _no_ai()
    data = request.get_json(silent=True) or {}
    try:
        result = provider.analyze_flow(data.get("tracks", []))
    except Exception as exc:
        return jsonify({"error": str(exc)}), 502
    return jsonify(result)


@app.route("/api/ai/clock/generate", methods=["POST"])
def ai_generate_clock():
    provider = ai.get_provider()
    if provider is None:
        return _no_ai()
    data = request.get_json(silent=True) or {}
    try:
        result = provider.generate_clock(
            data.get("description", ""),
            data.get("slots", 8),
        )
    except Exception as exc:
        return jsonify({"error": str(exc)}), 502
    return jsonify(result)


@app.route("/api/ai/rules/suggest", methods=["POST"])
def ai_suggest_rules():
    provider = ai.get_provider()
    if provider is None:
        return _no_ai()
    data = request.get_json(silent=True) or {}
    try:
        result = provider.suggest_rules(data.get("description", ""))
    except Exception as exc:
        return jsonify({"error": str(exc)}), 502
    return jsonify(result)


if __name__ == "__main__":
    app.run(debug=True)
