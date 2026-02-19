import csv
import io
import json
import os
import uuid
from collections import Counter
from datetime import datetime

import ai
from engine.rotator import build_schedule
from engine.rules import DEFAULT_RULES, merge_rules
from engine.validator import validate_schedule, _hms
from flask import Flask, Response, jsonify, render_template, request

app = Flask(__name__)

SCHEDULES_DIR = os.path.join(os.path.dirname(__file__), "data", "schedules")
TRACKS_DIR    = os.path.join(os.path.dirname(__file__), "data", "tracks")
CLOCKS_DIR    = os.path.join(os.path.dirname(__file__), "data", "clocks")
RULES_FILE    = os.path.join(os.path.dirname(__file__), "data", "rules.json")

for _d in (SCHEDULES_DIR, TRACKS_DIR, CLOCKS_DIR):
    os.makedirs(_d, exist_ok=True)


# ---------------------------------------------------------------------------
# Low-level helpers
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
# Rules helpers
# ---------------------------------------------------------------------------

def _load_rules() -> dict:
    if not os.path.exists(RULES_FILE):
        return {**DEFAULT_RULES}
    try:
        with open(RULES_FILE) as f:
            stored = json.load(f)
        return merge_rules(stored)
    except (json.JSONDecodeError, OSError):
        return {**DEFAULT_RULES}


def _save_rules(rules: dict) -> None:
    with open(RULES_FILE, "w") as f:
        json.dump(rules, f, indent=2)


# ---------------------------------------------------------------------------
# Schedule helpers
# ---------------------------------------------------------------------------

def _schedule_stats(track_list: list) -> dict:
    artists    = Counter(t.get("artist") for t in track_list if t.get("artist"))
    categories = Counter(t.get("category") or "Unknown" for t in track_list)
    total_secs = sum((t.get("duration_seconds") or 0) for t in track_list)
    return {
        "total_tracks":           len(track_list),
        "unique_artists":         len(artists),
        "top_artists":            dict(artists.most_common(5)),
        "category_breakdown":     dict(categories),
        "total_duration_seconds": total_secs,
        "total_duration_hms":     _hms(total_secs),
    }


def _add_air_times(track_list: list, start_time_str: str) -> list:
    """Attach an air_time string to each slot given a HH:MM or HH:MM:SS start."""
    if not start_time_str:
        return track_list
    try:
        parts      = [int(p) for p in start_time_str.split(":")]
        total_secs = parts[0] * 3600 + parts[1] * 60 + (parts[2] if len(parts) > 2 else 0)
    except (ValueError, IndexError):
        return track_list

    result = []
    for slot in track_list:
        secs = total_secs % 86400
        h, m, s = secs // 3600, (secs % 3600) // 60, secs % 60
        result.append({**slot, "air_time": f"{h:02d}:{m:02d}:{s:02d}"})
        total_secs += slot.get("duration_seconds") or 0
    return result


# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/status")
def status():
    return jsonify({
        "service":      "music-scheduler",
        "status":       "ok",
        "ai_available": ai.is_available(),
    })


# ---------------------------------------------------------------------------
# Global rotation rules
# ---------------------------------------------------------------------------

@app.route("/api/rules", methods=["GET"])
def get_rules():
    return jsonify(_load_rules())


@app.route("/api/rules", methods=["PUT"])
def update_rules():
    data  = request.get_json(silent=True) or {}
    rules = merge_rules(data)
    _save_rules(rules)
    return jsonify(rules)


# ---------------------------------------------------------------------------
# Tracks
# ---------------------------------------------------------------------------

_TRACK_REQUIRED = {"title", "artist", "category"}


def _make_track(data: dict) -> dict:
    """Build a new track dict from user-supplied data, with sane defaults."""
    return {
        "id":             str(uuid.uuid4()),
        "added_at":       _now(),
        "play_count":     0,
        "last_played_at": None,
        **{k: v for k, v in data.items() if k not in {"id", "added_at"}},
    }


@app.route("/api/tracks", methods=["GET"])
def list_tracks():
    tracks = _load_all(TRACKS_DIR)

    # --- Filter ---
    category = request.args.get("category")
    if category:
        tracks = [t for t in tracks if t.get("category") == category]

    search = (request.args.get("search") or "").strip().lower()
    if search:
        tracks = [
            t for t in tracks
            if search in (t.get("title")  or "").lower()
            or search in (t.get("artist") or "").lower()
        ]

    # --- Sort ---
    sort_by    = request.args.get("sort", "added_at")
    order_desc = request.args.get("order", "asc").lower() == "desc"
    _SORTABLE  = {"added_at", "title", "artist", "play_count", "last_played_at", "bpm", "energy"}
    _NUMERIC   = {"play_count", "bpm", "energy"}
    if sort_by in _SORTABLE:
        if sort_by in _NUMERIC:
            tracks.sort(
                key=lambda t: (t.get(sort_by) is None, t.get(sort_by) or 0),
                reverse=order_desc,
            )
        else:
            tracks.sort(
                key=lambda t: (t.get(sort_by) is None, t.get(sort_by) or ""),
                reverse=order_desc,
            )

    total = len(tracks)

    # --- Paginate ---
    try:
        offset = max(0, int(request.args.get("offset", 0)))
        limit  = max(0, int(request.args.get("limit",  0)))
    except (ValueError, TypeError):
        offset, limit = 0, 0

    if offset:
        tracks = tracks[offset:]
    if limit:
        tracks = tracks[:limit]

    return jsonify({"total": total, "offset": offset, "limit": limit, "tracks": tracks})


@app.route("/api/tracks", methods=["POST"])
def create_track():
    data    = request.get_json(silent=True) or {}
    missing = _TRACK_REQUIRED - data.keys()
    if missing:
        return jsonify({"error": f"Missing required fields: {', '.join(sorted(missing))}"}), 400
    track = _make_track(data)
    _save(TRACKS_DIR, track)
    return jsonify(track), 201


@app.route("/api/tracks/import", methods=["POST"])
def import_tracks():
    """Bulk-import tracks from a JSON array or {\"tracks\": [...]} body."""
    body = request.get_json(silent=True) or {}
    raw  = body if isinstance(body, list) else body.get("tracks", [])

    created, errors = [], []
    for i, item in enumerate(raw):
        missing = _TRACK_REQUIRED - item.keys()
        if missing:
            errors.append({
                "index": i,
                "error": f"Missing required fields: {', '.join(sorted(missing))}",
                "data":  item,
            })
            continue
        track = _make_track(item)
        _save(TRACKS_DIR, track)
        created.append(track)

    status = 201 if created else 400
    return jsonify({
        "imported":     len(created),
        "errors":       len(errors),
        "tracks":       created,
        "error_details": errors,
    }), status


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


@app.route("/api/tracks/<track_id>/play", methods=["POST"])
def log_play(track_id):
    """Record that a track was played: increments play_count, updates last_played_at."""
    track = _load_one(TRACKS_DIR, track_id)
    if track is None:
        return jsonify({"error": "Track not found"}), 404

    data      = request.get_json(silent=True) or {}
    played_at = data.get("played_at") or _now()

    track["play_count"]     = (track.get("play_count") or 0) + 1
    track["last_played_at"] = played_at
    track["updated_at"]     = _now()
    _save(TRACKS_DIR, track)

    return jsonify({
        "track_id":       track_id,
        "play_count":     track["play_count"],
        "last_played_at": track["last_played_at"],
    })


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


@app.route("/api/schedule/<schedule_id>/validate", methods=["POST"])
def validate_schedule_route(schedule_id):
    """Validate a stored schedule against separation rules."""
    schedule = _load_one(SCHEDULES_DIR, schedule_id)
    if schedule is None:
        return jsonify({"error": "Schedule not found"}), 404

    data         = request.get_json(silent=True) or {}
    stored_rules = schedule.get("rules") or {}
    override     = data.get("rules") or {}
    rules        = merge_rules({**stored_rules, **override})

    result = validate_schedule(schedule.get("tracks", []), rules)
    return jsonify(result)


@app.route("/api/schedule/<schedule_id>/export", methods=["GET"])
def export_schedule(schedule_id):
    """
    Export a schedule.
    ?format=csv  (default) — returns a CSV file attachment
    ?format=json           — returns enriched JSON
    ?start_time=HH:MM      — compute and add air times to each slot
    """
    schedule = _load_one(SCHEDULES_DIR, schedule_id)
    if schedule is None:
        return jsonify({"error": "Schedule not found"}), 404

    fmt        = request.args.get("format", "csv").lower()
    start_time = request.args.get("start_time") or schedule.get("start_time")
    tracks     = schedule.get("tracks", [])

    if start_time:
        tracks = _add_air_times(tracks, start_time)

    if fmt == "json":
        return jsonify({**schedule, "tracks": tracks})

    # CSV export
    fields = [
        "position", "air_time", "title", "artist", "category",
        "duration_seconds", "bpm", "energy", "mood", "notes",
    ]
    buf = io.StringIO()
    w   = csv.DictWriter(buf, fieldnames=fields, extrasaction="ignore")
    w.writeheader()
    for t in tracks:
        w.writerow({f: (t.get(f) if t.get(f) is not None else "") for f in fields})

    safe_name = "".join(
        c for c in (schedule.get("name") or schedule_id) if c.isalnum() or c in " -_"
    ).strip() or schedule_id

    return Response(
        buf.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{safe_name}.csv"'},
    )


@app.route("/api/schedule/generate", methods=["POST"])
def generate_schedule():
    data     = request.get_json(silent=True) or {}
    clock_id = data.get("clock_id")

    # Global rules as base, then per-request overrides
    base_rules = _load_rules()
    rules      = merge_rules({**base_rules, **(data.get("rules") or {})})

    if clock_id:
        # --- Rotation mode ---
        clock = _load_one(CLOCKS_DIR, clock_id)
        if clock is None:
            return jsonify({"error": "Clock not found"}), 404

        tracks         = _load_all(TRACKS_DIR)
        target_seconds = int(data.get("duration_minutes", 60)) * 60
        track_list     = build_schedule(clock, tracks, rules, target_seconds=target_seconds)

        start_time = data.get("start_time")
        if start_time:
            track_list = _add_air_times(track_list, start_time)

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
            "start_time":       start_time,
            "tracks":           track_list,
            "duration_minutes": sum((t.get("duration_seconds") or 0) for t in track_list) // 60,
            "rules":            rules,
            "stats":            _schedule_stats(track_list),
        }
    else:
        # --- Manual / backwards-compatible mode ---
        track_list  = data.get("tracks", [])
        schedule_id = str(uuid.uuid4())
        schedule = {
            "id":               schedule_id,
            "created_at":       _now(),
            "name":             data.get("name", "Untitled Schedule"),
            "tracks":           track_list,
            "duration_minutes": data.get("duration_minutes", 60),
            "stats":            _schedule_stats(track_list),
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
