import csv
import io
import json
import os
import uuid
from collections import Counter
from datetime import datetime

import ftplib
import ai
from engine.models import (
    make_track, make_artist, make_category, make_daypart,
    make_day_template, make_clock, make_slot, DEFAULT_DAYPARTS,
    make_announcer, make_sound_code, make_traffic_component, make_artist_group,
)
from engine.rotator import build_schedule
from engine.rules import DEFAULT_RULES, merge_rules
from engine.validator import validate_schedule, _hms
from flask import Flask, Response, jsonify, render_template, request

app = Flask(__name__)

SCHEDULES_DIR       = os.path.join(os.path.dirname(__file__), "data", "schedules")
TRACKS_DIR          = os.path.join(os.path.dirname(__file__), "data", "tracks")
CLOCKS_DIR          = os.path.join(os.path.dirname(__file__), "data", "clocks")
ARTISTS_DIR         = os.path.join(os.path.dirname(__file__), "data", "artists")
CATEGORIES_DIR      = os.path.join(os.path.dirname(__file__), "data", "categories")
DAYPARTS_DIR        = os.path.join(os.path.dirname(__file__), "data", "dayparts")
DAY_TEMPLATES_DIR   = os.path.join(os.path.dirname(__file__), "data", "day_templates")
PLAY_HISTORY_DIR    = os.path.join(os.path.dirname(__file__), "data", "play_history")
ANNOUNCERS_DIR      = os.path.join(os.path.dirname(__file__), "data", "announcers")
SOUND_CODES_DIR     = os.path.join(os.path.dirname(__file__), "data", "sound_codes")
TRAFFIC_DIR         = os.path.join(os.path.dirname(__file__), "data", "traffic")
ARTIST_GROUPS_DIR   = os.path.join(os.path.dirname(__file__), "data", "artist_groups")
RULES_FILE          = os.path.join(os.path.dirname(__file__), "data", "rules.json")

for _d in (SCHEDULES_DIR, TRACKS_DIR, CLOCKS_DIR, ARTISTS_DIR, CATEGORIES_DIR,
            DAYPARTS_DIR, DAY_TEMPLATES_DIR, PLAY_HISTORY_DIR, ANNOUNCERS_DIR,
            SOUND_CODES_DIR, TRAFFIC_DIR, ARTIST_GROUPS_DIR):
    os.makedirs(_d, exist_ok=True)


# ---------------------------------------------------------------------------
# Low-level helpers
# ---------------------------------------------------------------------------

def _load_all(directory: str) -> list:
    items = []
    for fname in os.listdir(directory):
        if fname.endswith(".json"):
            with open(os.path.join(directory, fname)) as f:
                try:
                    items.append(json.load(f))
                except json.JSONDecodeError:
                    pass
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
    music  = [t for t in track_list if t.get("type", "music") == "music"]
    artists    = Counter(t.get("artist") for t in music if t.get("artist"))
    categories = Counter(t.get("category") or "Unknown" for t in music)
    total_secs = sum((t.get("duration_seconds") or 0) for t in track_list)
    return {
        "total_tracks":           len(track_list),
        "music_tracks":           len(music),
        "unique_artists":         len(artists),
        "top_artists":            dict(artists.most_common(5)),
        "category_breakdown":     dict(categories),
        "total_duration_seconds": total_secs,
        "total_duration_hms":     _hms(total_secs),
    }


def _add_air_times(track_list: list, start_time_str: str) -> list:
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
# Play history helpers
# ---------------------------------------------------------------------------

def _play_history_path(day_str: str, hour: int) -> str:
    """Return path for a play-history file keyed by date+hour."""
    safe = day_str.replace("-", "")
    return os.path.join(PLAY_HISTORY_DIR, f"{safe}_h{hour:02d}.json")


def _load_play_history(day_str: str, hour: int) -> list:
    path = _play_history_path(day_str, hour)
    if not os.path.exists(path):
        return []
    with open(path) as f:
        return json.load(f)


def _save_play_history(day_str: str, hour: int, track_ids: list) -> None:
    path = _play_history_path(day_str, hour)
    with open(path, "w") as f:
        json.dump(track_ids, f)


# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------

@app.route("/")
def index():
    return render_template("dashboard.html")


@app.route("/generate")
def generate_page():
    return render_template("generate.html")


@app.route("/view")
def view_page():
    return render_template("view_schedule.html")


@app.route("/export")
def export_page():
    return render_template("export.html")


@app.route("/library")
def library_page():
    return render_template("index.html")


@app.route("/clocks-editor")
def clocks_editor_page():
    return render_template("index.html")


@app.route("/clock-editor/<clock_id>")
def clock_editor_page(clock_id):
    return render_template("clock_editor.html", clock_id=clock_id)


@app.route("/rules-editor")
def rules_editor_page():
    return render_template("index.html")


@app.route("/reports")
def reports_page():
    return render_template("reports.html")


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
# Artists
# ---------------------------------------------------------------------------

@app.route("/api/artists", methods=["GET"])
def list_artists():
    artists = _load_all(ARTISTS_DIR)
    search  = (request.args.get("search") or "").strip().lower()
    if search:
        artists = [a for a in artists if search in (a.get("name") or "").lower()]
    artists.sort(key=lambda a: (a.get("name") or "").lower())
    return jsonify({"total": len(artists), "artists": artists})


@app.route("/api/artists", methods=["POST"])
def create_artist():
    data = request.get_json(silent=True) or {}
    if not data.get("name"):
        return jsonify({"error": "Missing required field: name"}), 400
    artist = make_artist(data)
    _save(ARTISTS_DIR, artist)
    return jsonify(artist), 201


@app.route("/api/artists/<artist_id>", methods=["GET"])
def get_artist(artist_id):
    a = _load_one(ARTISTS_DIR, artist_id)
    if a is None:
        return jsonify({"error": "Artist not found"}), 404
    return jsonify(a)


@app.route("/api/artists/<artist_id>", methods=["PUT"])
def update_artist(artist_id):
    a = _load_one(ARTISTS_DIR, artist_id)
    if a is None:
        return jsonify({"error": "Artist not found"}), 404
    data = request.get_json(silent=True) or {}
    for k, v in data.items():
        if k not in {"id", "added_at"}:
            a[k] = v
    a["updated_at"] = _now()
    _save(ARTISTS_DIR, a)
    return jsonify(a)


@app.route("/api/artists/<artist_id>", methods=["DELETE"])
def delete_artist(artist_id):
    if not _delete(ARTISTS_DIR, artist_id):
        return jsonify({"error": "Artist not found"}), 404
    return "", 204


# ---------------------------------------------------------------------------
# Categories
# ---------------------------------------------------------------------------

@app.route("/api/categories", methods=["GET"])
def list_categories():
    cats = _load_all(CATEGORIES_DIR)
    cats.sort(key=lambda c: (c.get("priority", 0), (c.get("name") or "").lower()))
    return jsonify({"total": len(cats), "categories": cats})


@app.route("/api/categories", methods=["POST"])
def create_category():
    data = request.get_json(silent=True) or {}
    if not data.get("name"):
        return jsonify({"error": "Missing required field: name"}), 400
    cat = make_category(data)
    _save(CATEGORIES_DIR, cat)
    return jsonify(cat), 201


@app.route("/api/categories/<cat_id>", methods=["GET"])
def get_category(cat_id):
    cat = _load_one(CATEGORIES_DIR, cat_id)
    if cat is None:
        return jsonify({"error": "Category not found"}), 404
    return jsonify(cat)


@app.route("/api/categories/<cat_id>", methods=["PUT"])
def update_category(cat_id):
    cat = _load_one(CATEGORIES_DIR, cat_id)
    if cat is None:
        return jsonify({"error": "Category not found"}), 404
    data = request.get_json(silent=True) or {}
    for k, v in data.items():
        if k not in {"id", "added_at"}:
            cat[k] = v
    cat["updated_at"] = _now()
    _save(CATEGORIES_DIR, cat)
    return jsonify(cat)


@app.route("/api/categories/<cat_id>", methods=["DELETE"])
def delete_category(cat_id):
    if not _delete(CATEGORIES_DIR, cat_id):
        return jsonify({"error": "Category not found"}), 404
    return "", 204


# ---------------------------------------------------------------------------
# Dayparts
# ---------------------------------------------------------------------------

@app.route("/api/dayparts", methods=["GET"])
def list_dayparts():
    dps = _load_all(DAYPARTS_DIR)
    if not dps:
        # Return default dayparts if none configured yet
        return jsonify({"total": len(DEFAULT_DAYPARTS), "dayparts": DEFAULT_DAYPARTS,
                        "default": True})
    dps.sort(key=lambda d: d.get("start_hour", 0))
    return jsonify({"total": len(dps), "dayparts": dps})


@app.route("/api/dayparts", methods=["POST"])
def create_daypart():
    data = request.get_json(silent=True) or {}
    if not data.get("name"):
        return jsonify({"error": "Missing required field: name"}), 400
    dp = make_daypart(data)
    _save(DAYPARTS_DIR, dp)
    return jsonify(dp), 201


@app.route("/api/dayparts/<dp_id>", methods=["GET"])
def get_daypart(dp_id):
    dp = _load_one(DAYPARTS_DIR, dp_id)
    if dp is None:
        return jsonify({"error": "Daypart not found"}), 404
    return jsonify(dp)


@app.route("/api/dayparts/<dp_id>", methods=["PUT"])
def update_daypart(dp_id):
    dp = _load_one(DAYPARTS_DIR, dp_id)
    if dp is None:
        return jsonify({"error": "Daypart not found"}), 404
    data = request.get_json(silent=True) or {}
    for k, v in data.items():
        if k not in {"id", "added_at"}:
            dp[k] = v
    dp["updated_at"] = _now()
    _save(DAYPARTS_DIR, dp)
    return jsonify(dp)


@app.route("/api/dayparts/<dp_id>", methods=["DELETE"])
def delete_daypart(dp_id):
    if not _delete(DAYPARTS_DIR, dp_id):
        return jsonify({"error": "Daypart not found"}), 404
    return "", 204


# ---------------------------------------------------------------------------
# Day Templates  (weekly format: maps each hour 0-23 to a clock_id)
# ---------------------------------------------------------------------------

@app.route("/api/day-templates", methods=["GET"])
def list_day_templates():
    tmpls = _load_all(DAY_TEMPLATES_DIR)
    tmpls.sort(key=lambda t: (t.get("name") or ""))
    return jsonify({"total": len(tmpls), "day_templates": tmpls})


@app.route("/api/day-templates", methods=["POST"])
def create_day_template():
    data = request.get_json(silent=True) or {}
    if not data.get("name"):
        return jsonify({"error": "Missing required field: name"}), 400
    tmpl = make_day_template(data)
    _save(DAY_TEMPLATES_DIR, tmpl)
    return jsonify(tmpl), 201


@app.route("/api/day-templates/<tmpl_id>", methods=["GET"])
def get_day_template(tmpl_id):
    tmpl = _load_one(DAY_TEMPLATES_DIR, tmpl_id)
    if tmpl is None:
        return jsonify({"error": "Day template not found"}), 404
    return jsonify(tmpl)


@app.route("/api/day-templates/<tmpl_id>", methods=["PUT"])
def update_day_template(tmpl_id):
    tmpl = _load_one(DAY_TEMPLATES_DIR, tmpl_id)
    if tmpl is None:
        return jsonify({"error": "Day template not found"}), 404
    data = request.get_json(silent=True) or {}
    incoming_hours = data.pop("hours", None)
    for k, v in data.items():
        if k not in {"id", "added_at"}:
            tmpl[k] = v
    if incoming_hours is not None:
        tmpl["hours"] = {**tmpl.get("hours", {}), **{str(k): v for k, v in incoming_hours.items()}}
    tmpl["updated_at"] = _now()
    _save(DAY_TEMPLATES_DIR, tmpl)
    return jsonify(tmpl)


@app.route("/api/day-templates/<tmpl_id>", methods=["DELETE"])
def delete_day_template(tmpl_id):
    if not _delete(DAY_TEMPLATES_DIR, tmpl_id):
        return jsonify({"error": "Day template not found"}), 404
    return "", 204


# ---------------------------------------------------------------------------
# Tracks
# ---------------------------------------------------------------------------

_TRACK_REQUIRED = {"title", "artist", "category"}


@app.route("/api/tracks", methods=["GET"])
def list_tracks():
    tracks = _load_all(TRACKS_DIR)

    category = request.args.get("category")
    if category:
        tracks = [t for t in tracks if t.get("category") == category]

    tempo = request.args.get("tempo")
    if tempo:
        try:
            tempo_val = int(tempo)
            tracks = [t for t in tracks if t.get("tempo") == tempo_val]
        except (ValueError, TypeError):
            pass

    gender = request.args.get("gender")
    if gender:
        try:
            gender_val = int(gender)
            tracks = [t for t in tracks if t.get("gender") == gender_val]
        except (ValueError, TypeError):
            pass

    mood = request.args.get("mood")
    if mood:
        try:
            mood_val = int(mood)
            tracks = [t for t in tracks if t.get("mood") == mood_val]
        except (ValueError, TypeError):
            pass

    active_filter = request.args.get("active")
    if active_filter == "true":
        tracks = [t for t in tracks if t.get("active", True)]
    elif active_filter == "false":
        tracks = [t for t in tracks if not t.get("active", True)]

    search = (request.args.get("search") or "").strip().lower()
    if search:
        tracks = [
            t for t in tracks
            if search in (t.get("title")   or "").lower()
            or search in (t.get("artist")  or "").lower()
            or search in (t.get("cart_number") or t.get("cart") or "").lower()
            or search in (t.get("genre")   or "").lower()
            or search in (t.get("album")   or "").lower()
        ]

    sort_by    = request.args.get("sort", "added_at")
    order_desc = request.args.get("order", "asc").lower() == "desc"
    _SORTABLE  = {"added_at", "title", "artist", "play_count", "last_played_at",
                  "bpm", "energy", "tempo", "mood", "gender", "cart_number", "cart",
                  "intro_seconds", "chart_position", "pct_play"}
    _NUMERIC   = {"play_count", "bpm", "energy", "tempo", "mood", "gender",
                  "intro_seconds", "chart_position", "pct_play"}
    if sort_by in _SORTABLE:
        # Always use title as a stable secondary sort key to break ties
        # (especially important when many tracks share the same added_at timestamp)
        if sort_by in _NUMERIC:
            tracks.sort(
                key=lambda t: (t.get(sort_by) is None, t.get(sort_by) or 0,
                               (t.get("title") or "").lower()),
                reverse=order_desc,
            )
        else:
            tracks.sort(
                key=lambda t: (t.get(sort_by) is None, t.get(sort_by) or "",
                               (t.get("title") or "").lower()),
                reverse=order_desc,
            )

    total = len(tracks)

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
    track = make_track(data)
    _save(TRACKS_DIR, track)
    return jsonify(track), 201


@app.route("/api/tracks/import", methods=["POST"])
def import_tracks():
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
        track = make_track(item)
        _save(TRACKS_DIR, track)
        created.append(track)

    status = 201 if created else 400
    return jsonify({
        "imported":      len(created),
        "errors":        len(errors),
        "tracks":        created,
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
    """Record that a track was played. Updates play_count and play history."""
    track = _load_one(TRACKS_DIR, track_id)
    if track is None:
        return jsonify({"error": "Track not found"}), 404

    data      = request.get_json(silent=True) or {}
    played_at = data.get("played_at") or _now()
    hour      = data.get("hour")   # 0-23; optional
    day       = data.get("day")    # ISO date string; optional

    track["play_count"]     = (track.get("play_count") or 0) + 1
    track["last_played_at"] = played_at
    track["updated_at"]     = _now()
    _save(TRACKS_DIR, track)

    # Record in play history for prev-day separation
    if day is not None and hour is not None:
        try:
            hour = int(hour)
            hist = _load_play_history(day, hour)
            if track_id not in hist:
                hist.append(track_id)
            _save_play_history(day, hour, hist)
        except (ValueError, TypeError):
            pass

    return jsonify({
        "track_id":       track_id,
        "play_count":     track["play_count"],
        "last_played_at": track["last_played_at"],
    })


# ---------------------------------------------------------------------------
# Play history
# ---------------------------------------------------------------------------

@app.route("/api/play-history", methods=["GET"])
def get_play_history():
    """Return play history for a given day and optional hour."""
    day  = request.args.get("day")
    hour = request.args.get("hour")
    if not day:
        return jsonify({"error": "Missing required query param: day"}), 400
    try:
        hour_int = int(hour) if hour is not None else None
    except (ValueError, TypeError):
        return jsonify({"error": "hour must be an integer 0-23"}), 400

    if hour_int is not None:
        history = _load_play_history(day, hour_int)
        return jsonify({"day": day, "hour": hour_int, "track_ids": history})

    # Return all hours for the day
    result = {}
    for h in range(24):
        hist = _load_play_history(day, h)
        if hist:
            result[str(h)] = hist
    return jsonify({"day": day, "hours": result})


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
    # Normalise slots to full slot dicts
    data["slots"] = [make_slot(s) for s in data["slots"]]
    clock = make_clock(data)
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
    if "slots" in data:
        data["slots"] = [make_slot(s) for s in data["slots"]]
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
    schedule = _load_one(SCHEDULES_DIR, schedule_id)
    if schedule is None:
        return jsonify({"error": "Schedule not found"}), 404

    data         = request.get_json(silent=True) or {}
    stored_rules = schedule.get("rules") or {}
    override     = data.get("rules") or {}
    rules        = merge_rules({**stored_rules, **override})
    categories   = _load_all(CATEGORIES_DIR)

    result = validate_schedule(schedule.get("tracks", []), rules, categories=categories)
    return jsonify(result)


@app.route("/api/schedule/<schedule_id>/move-track", methods=["POST"])
def move_track(schedule_id):
    """Swap two adjacent tracks within a schedule by index."""
    schedule = _load_one(SCHEDULES_DIR, schedule_id)
    if schedule is None:
        return jsonify({"error": "Schedule not found"}), 404
    data        = request.get_json(silent=True) or {}
    from_idx    = data.get("from_index")
    to_idx      = data.get("to_index")
    tracks      = schedule.get("tracks", [])
    if from_idx is None or to_idx is None:
        return jsonify({"error": "from_index and to_index required"}), 400
    if not (0 <= from_idx < len(tracks) and 0 <= to_idx < len(tracks)):
        return jsonify({"error": "Index out of range"}), 400
    tracks[from_idx], tracks[to_idx] = tracks[to_idx], tracks[from_idx]
    schedule["tracks"]     = tracks
    schedule["updated_at"] = _now()
    _save(SCHEDULES_DIR, schedule)
    return jsonify({"success": True})


@app.route("/api/schedule/<schedule_id>/replace-track", methods=["POST"])
def replace_track(schedule_id):
    """Replace a track at a given index with a different song."""
    schedule = _load_one(SCHEDULES_DIR, schedule_id)
    if schedule is None:
        return jsonify({"error": "Schedule not found"}), 404
    data        = request.get_json(silent=True) or {}
    track_index = data.get("track_index")
    new_song_id = data.get("new_song_id")
    tracks      = schedule.get("tracks", [])
    if track_index is None or new_song_id is None:
        return jsonify({"error": "track_index and new_song_id required"}), 400
    if not (0 <= track_index < len(tracks)):
        return jsonify({"error": "Index out of range"}), 400
    # Load the replacement song
    song = _load_one(TRACKS_DIR, new_song_id)
    if song is None:
        return jsonify({"error": "Song not found"}), 404
    # Preserve air_time from the original slot
    old_track = tracks[track_index]
    song["air_time"] = old_track.get("air_time", "")
    song["position"] = old_track.get("position", track_index + 1)
    tracks[track_index] = song
    schedule["tracks"]     = tracks
    schedule["updated_at"] = _now()
    _save(SCHEDULES_DIR, schedule)
    return jsonify({"success": True, "track": song})


@app.route("/api/schedule/<schedule_id>/export", methods=["GET"])
def export_schedule(schedule_id):
    """
    Export a schedule.
    ?format=csv  (default) — returns a CSV file
    ?format=json           — returns enriched JSON
    ?start_time=HH:MM      — compute air times
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

    fields = [
        "position", "air_time", "type", "title", "artist", "category",
        "duration_seconds", "intro_ms", "outro_ms", "mix_in_ms", "mix_out_ms",
        "bpm", "energy", "gender", "tempo", "texture", "mood",
        "cart", "file_path", "notes",
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

    base_rules = _load_rules()
    rules      = merge_rules({**base_rules, **(data.get("rules") or {})})

    artists    = _load_all(ARTISTS_DIR)
    categories = _load_all(CATEGORIES_DIR)

    if clock_id:
        clock = _load_one(CLOCKS_DIR, clock_id)
        if clock is None:
            return jsonify({"error": "Clock not found"}), 404

        tracks         = _load_all(TRACKS_DIR)
        target_seconds = int(data.get("duration_minutes", 60)) * 60
        hour           = int(data.get("hour", 0))

        # Load prev-day play history if requested
        prev_day_plays = []
        if rules.get("check_prev_day_song") or data.get("check_prev_day"):
            from datetime import date, timedelta
            yesterday = (date.today() - timedelta(days=1)).isoformat()
            prev_day_plays = _load_play_history(yesterday, hour)

        track_list = build_schedule(
            clock, tracks, rules,
            target_seconds=target_seconds,
            hour=hour,
            artists=artists,
            categories=categories,
            prev_day_plays=prev_day_plays,
        )

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
            "hour":             hour,
            "tracks":           track_list,
            "duration_minutes": sum((t.get("duration_seconds") or 0) for t in track_list) // 60,
            "rules":            rules,
            "stats":            _schedule_stats(track_list),
        }
    else:
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
# Day-schedule generation  (full day using a day template)
# ---------------------------------------------------------------------------

@app.route("/api/schedule/generate-day", methods=["POST"])
def generate_day_schedule():
    """
    Generate a full-day schedule by iterating each hour of a day template,
    loading the clock assigned to that hour, and running the scheduler.

    Body params:
        template_id:      (required) day template ID
        name:             schedule name (optional)
        date:             ISO date string for prev-day checks (optional)
        start_hour:       first hour to schedule (default 0)
        end_hour:         last hour to schedule inclusive (default 23)
    """
    data        = request.get_json(silent=True) or {}
    template_id = data.get("template_id")
    if not template_id:
        return jsonify({"error": "Missing required field: template_id"}), 400

    tmpl = _load_one(DAY_TEMPLATES_DIR, template_id)
    if tmpl is None:
        return jsonify({"error": "Day template not found"}), 404

    base_rules = _load_rules()
    rules      = merge_rules({**base_rules, **(data.get("rules") or {})})
    artists    = _load_all(ARTISTS_DIR)
    categories = _load_all(CATEGORIES_DIR)
    tracks     = _load_all(TRACKS_DIR)

    start_hour = int(data.get("start_hour", 0))
    end_hour   = int(data.get("end_hour",  23))
    target_day = data.get("date", datetime.utcnow().date().isoformat())

    from datetime import date, timedelta
    yesterday = (date.fromisoformat(target_day) - timedelta(days=1)).isoformat()

    all_slots     = []
    position      = 1
    total_secs    = 0
    hour_clock_map = tmpl.get("hours", {})

    for hour in range(start_hour, end_hour + 1):
        clock_id = hour_clock_map.get(str(hour))
        if not clock_id:
            continue
        clock = _load_one(CLOCKS_DIR, clock_id)
        if clock is None:
            continue

        prev_day_plays = []
        if rules.get("check_prev_day_song"):
            prev_day_plays = _load_play_history(yesterday, hour)

        hour_slots = build_schedule(
            clock, tracks, rules,
            target_seconds=3600,
            hour=hour,
            artists=artists,
            categories=categories,
            prev_day_plays=prev_day_plays,
        )

        # Re-number positions sequentially across the day
        for slot in hour_slots:
            slot["position"]  = position
            slot["hour"]      = hour
            total_secs       += slot.get("duration_seconds") or 0
            position         += 1
        all_slots.extend(hour_slots)

    # Add air times starting from start_hour:00:00
    start_time = f"{start_hour:02d}:00:00"
    all_slots  = _add_air_times(all_slots, start_time)

    schedule_id = str(uuid.uuid4())
    name        = data.get("name") or f"{tmpl['name']} — {target_day}"
    schedule = {
        "id":               schedule_id,
        "created_at":       _now(),
        "name":             name,
        "template_id":      template_id,
        "template_name":    tmpl.get("name"),
        "date":             target_day,
        "start_hour":       start_hour,
        "end_hour":         end_hour,
        "tracks":           all_slots,
        "duration_minutes": total_secs // 60,
        "rules":            rules,
        "stats":            _schedule_stats(all_slots),
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


# ---------------------------------------------------------------------------
# Dashboard stats
# ---------------------------------------------------------------------------

@app.route("/api/stats")
def get_stats():
    tracks = _load_all(TRACKS_DIR)
    total  = len(tracks)
    active = sum(1 for t in tracks if t.get("active", True))
    schedules = _load_all(SCHEDULES_DIR)

    slots_filled = 0
    total_slots  = 0
    for s in schedules:
        filled = s.get("stats", {}).get("music_tracks") or len(s.get("tracks", []))
        slots_filled += filled
    total_slots = slots_filled  # approximate

    fill_rate = 0.0
    if total_slots > 0:
        fill_rate = 100.0

    from datetime import date, timedelta
    today = date.today()
    start = today - timedelta(days=today.weekday())
    end   = start + timedelta(days=6)
    week_str = f"{start.strftime('%b')} {start.day}–{end.day}"

    return jsonify({
        "total_songs":   total,
        "active_songs":  active,
        "current_week":  week_str,
        "fill_rate":     fill_rate,
        "slots_filled":  slots_filled,
        "total_slots":   total_slots,
    })


# ---------------------------------------------------------------------------
# Week generation  (called by generate.html)
# ---------------------------------------------------------------------------

@app.route("/api/generate", methods=["POST"])
def api_generate_week():
    """Generate a full week schedule via the scheduler engine."""
    data            = request.get_json(silent=True) or {}
    start_date      = data.get("start_date")
    day_template_id = data.get("day_template_id")  # optional: use this template for all 7 days
    strategy        = data.get("strategy", "standard")
    overnight_fill  = data.get("overnight_fill", True)
    # overnight_hours: list of hour ints [0-5] to include in overnight fill
    # Default: all six overnight hours (0-5)
    overnight_hours = set(data.get("overnight_hours", [0, 1, 2, 3, 4, 5]))
    if not isinstance(overnight_hours, set):
        overnight_hours = set(map(int, overnight_hours))

    try:
        from datetime import date, timedelta
        if start_date:
            target = date.fromisoformat(start_date)
        else:
            today  = date.today()
            target = today - timedelta(days=today.weekday())

        base_rules = _load_rules()
        rules      = merge_rules(base_rules)
        artists    = _load_all(ARTISTS_DIR)
        categories = _load_all(CATEGORIES_DIR)
        tracks     = _load_all(TRACKS_DIR)

        if not tracks:
            return jsonify({
                "success":      False,
                "error":        "No tracks found in library. Import tracks first.",
            }), 400

        tmpls = _load_all(DAY_TEMPLATES_DIR)
        clocks_list = _load_all(CLOCKS_DIR)

        # Resolve which day template to use for the week
        if day_template_id:
            tmpl = next((t for t in tmpls if t.get("id") == day_template_id), None)
        else:
            tmpl = next((t for t in tmpls), None)

        slots_filled = 0
        total_slots  = 0
        days_generated = 0

        for day_offset in range(7):
            day = target + timedelta(days=day_offset)
            day_str = day.isoformat()

            # Use the selected template (or first) for this day
            if tmpl is None and clocks_list:
                # No templates: just use first clock for every hour
                clock = clocks_list[0]
                from datetime import date as _date, timedelta as _td
                yesterday = (day - _td(days=1)).isoformat()
                for hour in range(6, 24):
                    prev_day_plays = _load_play_history(yesterday, hour)
                    hour_slots = build_schedule(
                        clock, tracks, rules,
                        target_seconds=3600,
                        hour=hour,
                        artists=artists,
                        categories=categories,
                        prev_day_plays=prev_day_plays,
                        sched_date=day_str,
                    )
                    slots_filled += len(hour_slots)
                    total_slots  += 18  # 6am-midnight
                days_generated += 1
                continue

            if tmpl is None:
                continue

            hour_clock_map = tmpl.get("hours", {})
            from datetime import date as _date, timedelta as _td
            yesterday = (day - _td(days=1)).isoformat()

            all_slots = []
            for hour in range(24):
                # Skip overnight hours (0-5 AM) not selected for auto-fill
                if hour < 6 and (not overnight_fill or hour not in overnight_hours):
                    continue
                clock_id = hour_clock_map.get(str(hour))
                if not clock_id:
                    total_slots += 1
                    continue
                clock = _load_one(CLOCKS_DIR, clock_id)
                if clock is None:
                    total_slots += 1
                    continue

                prev_day_plays = _load_play_history(yesterday, hour)
                hour_slots = build_schedule(
                    clock, tracks, rules,
                    target_seconds=3600,
                    hour=hour,
                    artists=artists,
                    categories=categories,
                    prev_day_plays=prev_day_plays,
                    sched_date=day_str,
                )
                for i, slot in enumerate(hour_slots):
                    slot["hour"] = hour
                    slot["air_time"] = f"{hour:02d}:{(i*4):02d}:00"
                all_slots.extend(hour_slots)
                slots_filled += len(hour_slots)
                total_slots  += max(len(hour_slots), 1)

            schedule_id = str(uuid.uuid4())
            schedule = {
                "id":          schedule_id,
                "created_at":  _now(),
                "name":        f"Week of {day_str}",
                "date":        day_str,
                "tracks":      all_slots,
                "stats":       _schedule_stats(all_slots),
            }
            _save(SCHEDULES_DIR, schedule)
            days_generated += 1

        fill_rate = (slots_filled / total_slots * 100) if total_slots > 0 else 0.0
        return jsonify({
            "success":      True,
            "message":      f"Generated {days_generated} days ({slots_filled} slots filled)",
            "slots_filled": slots_filled,
            "total_slots":  total_slots,
            "fill_rate":    fill_rate,
        })

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


# Export routes moved to bottom of file (see api_export / api_export_download / api_export_ftp)


# ---------------------------------------------------------------------------
# Date-based schedule lookup  (called by view_schedule.html)
# ---------------------------------------------------------------------------

@app.route("/api/schedule/date/<date>")
def get_schedule_by_date(date):
    """Return schedule for a specific date (YYYY-MM-DD)."""
    schedules = _load_all(SCHEDULES_DIR)

    # Find schedules matching the date
    matching = [s for s in schedules if (s.get("date") or "").startswith(date)]
    if not matching:
        return jsonify({"date": date, "schedule": [], "schedule_ids": []})

    # Merge all matching schedules' tracks, sorted by air_time
    # Track which schedule_id and local index each track came from
    all_tracks = []
    schedule_ids = [s["id"] for s in matching if s.get("id")]
    for s in matching:
        sid = s.get("id", "")
        for local_idx, t in enumerate(s.get("tracks", [])):
            all_tracks.append({**t, "_schedule_id": sid, "_local_idx": local_idx})

    all_tracks.sort(key=lambda t: t.get("air_time") or str(t.get("position") or 0).zfill(6))

    schedule = []
    for i, t in enumerate(all_tracks):
        air = t.get("air_time", "")
        hour = None
        if air:
            try:
                h, m, s2 = [int(x) for x in air.split(":")]
                suffix = "AM" if h < 12 else "PM"
                dh = h % 12 or 12
                time_str = f"{dh}:{m:02d} {suffix}"
                hour = h
            except Exception:
                time_str = air
        else:
            time_str = "—"

        dur_secs = t.get("duration_seconds") or 0
        dur_str  = f"{dur_secs // 60}:{dur_secs % 60:02d}" if dur_secs else "—"

        schedule.append({
            "position":          i + 1,
            "time":              time_str,
            "air_time":          air,
            "hour":              hour,
            "song_id":           t.get("id") or t.get("song_id") or "",
            "schedule_id":       t.get("_schedule_id", ""),
            "local_track_index": t.get("_local_idx", i),
            "title":             t.get("title") or "Unknown",
            "artist":            t.get("artist") or "",
            "category":          t.get("category") or "Uncategorized",
            "cart_number":       t.get("cart_number") or t.get("cart") or "",
            "cart":              t.get("cart") or t.get("cart_number") or "",
            "length":            dur_str,
            "duration_seconds":  dur_secs,
            "tempo":             t.get("tempo"),
            "mood":              t.get("mood"),
            "energy":            t.get("energy"),
            "gender":            t.get("gender"),
            "sound_codes":       t.get("sound_codes"),
            "has_error":         bool(t.get("has_error")),
            "has_warning":       bool(t.get("has_warning")),
            "error":             t.get("error") or "",
            "warning":           t.get("warning") or "",
        })

    return jsonify({"date": date, "schedule": schedule, "schedule_ids": schedule_ids})


# ---------------------------------------------------------------------------
# Announcers  (Music1: Jocks / Announcers table)
# ---------------------------------------------------------------------------

@app.route("/api/announcers", methods=["GET"])
def list_announcers():
    anns = _load_all(ANNOUNCERS_DIR)
    anns.sort(key=lambda a: (a.get("name") or "").lower())
    return jsonify({"total": len(anns), "announcers": anns})


@app.route("/api/announcers", methods=["POST"])
def create_announcer():
    data = request.get_json(silent=True) or {}
    if not data.get("name"):
        return jsonify({"error": "Missing required field: name"}), 400
    ann = make_announcer(data)
    _save(ANNOUNCERS_DIR, ann)
    return jsonify(ann), 201


@app.route("/api/announcers/<ann_id>", methods=["GET"])
def get_announcer(ann_id):
    ann = _load_one(ANNOUNCERS_DIR, ann_id)
    if ann is None:
        return jsonify({"error": "Announcer not found"}), 404
    return jsonify(ann)


@app.route("/api/announcers/<ann_id>", methods=["PUT"])
def update_announcer(ann_id):
    ann = _load_one(ANNOUNCERS_DIR, ann_id)
    if ann is None:
        return jsonify({"error": "Announcer not found"}), 404
    data = request.get_json(silent=True) or {}
    for k, v in data.items():
        if k not in {"id", "added_at"}:
            ann[k] = v
    ann["updated_at"] = _now()
    _save(ANNOUNCERS_DIR, ann)
    return jsonify(ann)


@app.route("/api/announcers/<ann_id>", methods=["DELETE"])
def delete_announcer(ann_id):
    if not _delete(ANNOUNCERS_DIR, ann_id):
        return jsonify({"error": "Announcer not found"}), 404
    return "", 204


# ---------------------------------------------------------------------------
# Sound Codes  (Music1: up to 30 named sound characteristics per track)
# ---------------------------------------------------------------------------

@app.route("/api/sound-codes", methods=["GET"])
def list_sound_codes():
    scs = _load_all(SOUND_CODES_DIR)
    scs.sort(key=lambda s: s.get("number", 0))
    return jsonify({"total": len(scs), "sound_codes": scs})


@app.route("/api/sound-codes", methods=["POST"])
def create_sound_code():
    data = request.get_json(silent=True) or {}
    if not data.get("name"):
        return jsonify({"error": "Missing required field: name"}), 400
    sc = make_sound_code(data)
    _save(SOUND_CODES_DIR, sc)
    return jsonify(sc), 201


@app.route("/api/sound-codes/<sc_id>", methods=["GET"])
def get_sound_code(sc_id):
    sc = _load_one(SOUND_CODES_DIR, sc_id)
    if sc is None:
        return jsonify({"error": "Sound code not found"}), 404
    return jsonify(sc)


@app.route("/api/sound-codes/<sc_id>", methods=["PUT"])
def update_sound_code(sc_id):
    sc = _load_one(SOUND_CODES_DIR, sc_id)
    if sc is None:
        return jsonify({"error": "Sound code not found"}), 404
    data = request.get_json(silent=True) or {}
    for k, v in data.items():
        if k not in {"id", "added_at"}:
            sc[k] = v
    sc["updated_at"] = _now()
    _save(SOUND_CODES_DIR, sc)
    return jsonify(sc)


@app.route("/api/sound-codes/<sc_id>", methods=["DELETE"])
def delete_sound_code(sc_id):
    if not _delete(SOUND_CODES_DIR, sc_id):
        return jsonify({"error": "Sound code not found"}), 404
    return "", 204


# ---------------------------------------------------------------------------
# Traffic / Spot Components  (Music1: Components / SpotTypes table)
# ---------------------------------------------------------------------------

@app.route("/api/traffic", methods=["GET"])
def list_traffic():
    comps = _load_all(TRAFFIC_DIR)
    type_filter = request.args.get("type")
    if type_filter:
        comps = [c for c in comps if c.get("type") == type_filter]
    active_only = request.args.get("active", "").lower() == "true"
    if active_only:
        comps = [c for c in comps if c.get("active", True)]
    comps.sort(key=lambda c: (c.get("name") or "").lower())
    return jsonify({"total": len(comps), "components": comps})


@app.route("/api/traffic", methods=["POST"])
def create_traffic():
    data = request.get_json(silent=True) or {}
    if not data.get("name"):
        return jsonify({"error": "Missing required field: name"}), 400
    tc = make_traffic_component(data)
    _save(TRAFFIC_DIR, tc)
    return jsonify(tc), 201


@app.route("/api/traffic/<comp_id>", methods=["GET"])
def get_traffic(comp_id):
    tc = _load_one(TRAFFIC_DIR, comp_id)
    if tc is None:
        return jsonify({"error": "Component not found"}), 404
    return jsonify(tc)


@app.route("/api/traffic/<comp_id>", methods=["PUT"])
def update_traffic(comp_id):
    tc = _load_one(TRAFFIC_DIR, comp_id)
    if tc is None:
        return jsonify({"error": "Component not found"}), 404
    data = request.get_json(silent=True) or {}
    for k, v in data.items():
        if k not in {"id", "added_at"}:
            tc[k] = v
    tc["updated_at"] = _now()
    _save(TRAFFIC_DIR, tc)
    return jsonify(tc)


@app.route("/api/traffic/<comp_id>", methods=["DELETE"])
def delete_traffic(comp_id):
    if not _delete(TRAFFIC_DIR, comp_id):
        return jsonify({"error": "Component not found"}), 404
    return "", 204


# ---------------------------------------------------------------------------
# Artist Groups  (shared separation pool for group members)
# ---------------------------------------------------------------------------

@app.route("/api/artist-groups", methods=["GET"])
def list_artist_groups():
    groups = _load_all(ARTIST_GROUPS_DIR)
    groups.sort(key=lambda g: (g.get("name") or "").lower())
    # Annotate each group with member count
    artists = _load_all(ARTISTS_DIR)
    for grp in groups:
        grp["member_count"] = sum(1 for a in artists if a.get("group_id") == grp["id"])
    return jsonify({"total": len(groups), "artist_groups": groups})


@app.route("/api/artist-groups", methods=["POST"])
def create_artist_group():
    data = request.get_json(silent=True) or {}
    if not data.get("name"):
        return jsonify({"error": "Missing required field: name"}), 400
    grp = make_artist_group(data)
    _save(ARTIST_GROUPS_DIR, grp)
    return jsonify(grp), 201


@app.route("/api/artist-groups/<grp_id>", methods=["GET"])
def get_artist_group(grp_id):
    grp = _load_one(ARTIST_GROUPS_DIR, grp_id)
    if grp is None:
        return jsonify({"error": "Artist group not found"}), 404
    artists = _load_all(ARTISTS_DIR)
    grp["members"] = [a for a in artists if a.get("group_id") == grp_id]
    return jsonify(grp)


@app.route("/api/artist-groups/<grp_id>", methods=["PUT"])
def update_artist_group(grp_id):
    grp = _load_one(ARTIST_GROUPS_DIR, grp_id)
    if grp is None:
        return jsonify({"error": "Artist group not found"}), 404
    data = request.get_json(silent=True) or {}
    for k, v in data.items():
        if k not in {"id", "added_at"}:
            grp[k] = v
    grp["updated_at"] = _now()
    _save(ARTIST_GROUPS_DIR, grp)
    return jsonify(grp)


@app.route("/api/artist-groups/<grp_id>", methods=["DELETE"])
def delete_artist_group(grp_id):
    if not _delete(ARTIST_GROUPS_DIR, grp_id):
        return jsonify({"error": "Artist group not found"}), 404
    return "", 204


# ---------------------------------------------------------------------------
# Bulk track operations  (activate/deactivate/re-categorize/delete)
# ---------------------------------------------------------------------------

@app.route("/api/tracks/bulk-action", methods=["POST"])
def bulk_track_action():
    """
    Body:
        action:   "activate" | "deactivate" | "recategorize" | "delete" | "set_field"
        track_ids: list of track IDs to operate on (empty = all)
        filters:  optional {category, tempo, gender, search} to select tracks
        value:    new value (for recategorize / set_field)
        field:    field name (for set_field)
    """
    data     = request.get_json(silent=True) or {}
    action   = data.get("action")
    ids      = set(data.get("track_ids") or [])
    filters  = data.get("filters") or {}
    value    = data.get("value")
    field    = data.get("field")

    valid_actions = {"activate", "deactivate", "recategorize", "delete", "set_field"}
    if action not in valid_actions:
        return jsonify({"error": f"action must be one of {sorted(valid_actions)}"}), 400

    tracks = _load_all(TRACKS_DIR)

    # Apply filters if no explicit IDs given
    if not ids and filters:
        if filters.get("category"):
            tracks = [t for t in tracks if t.get("category") == filters["category"]]
        if filters.get("tempo"):
            try:
                tv = int(filters["tempo"])
                tracks = [t for t in tracks if t.get("tempo") == tv]
            except (ValueError, TypeError):
                pass
        if filters.get("gender"):
            try:
                gv = int(filters["gender"])
                tracks = [t for t in tracks if t.get("gender") == gv]
            except (ValueError, TypeError):
                pass
        if filters.get("search"):
            q = filters["search"].strip().lower()
            tracks = [t for t in tracks if q in (t.get("title") or "").lower()
                      or q in (t.get("artist") or "").lower()]
        ids = {t["id"] for t in tracks}

    affected = 0
    for t in _load_all(TRACKS_DIR):
        if t["id"] not in ids:
            continue
        if action == "activate":
            t["active"] = True
        elif action == "deactivate":
            t["active"] = False
        elif action == "recategorize":
            if value is None:
                continue
            t["category"] = value
        elif action == "set_field":
            if not field:
                continue
            t[field] = value
        elif action == "delete":
            _delete(TRACKS_DIR, t["id"])
            affected += 1
            continue
        t["updated_at"] = _now()
        _save(TRACKS_DIR, t)
        affected += 1

    return jsonify({"success": True, "affected": affected})


# ---------------------------------------------------------------------------
# Schedule clone
# ---------------------------------------------------------------------------

@app.route("/api/schedule/<schedule_id>/clone", methods=["POST"])
def clone_schedule(schedule_id):
    """Clone an existing schedule to a new date or with a new name."""
    original = _load_one(SCHEDULES_DIR, schedule_id)
    if original is None:
        return jsonify({"error": "Schedule not found"}), 404
    data     = request.get_json(silent=True) or {}
    new_id   = str(uuid.uuid4())
    cloned   = {**original, "id": new_id, "created_at": _now()}
    if "name" in data:
        cloned["name"] = data["name"]
    else:
        cloned["name"] = (original.get("name") or "Schedule") + " (copy)"
    if "date" in data:
        cloned["date"] = data["date"]
    _save(SCHEDULES_DIR, cloned)
    return jsonify(cloned), 201


# ---------------------------------------------------------------------------
# Reports
# ---------------------------------------------------------------------------

@app.route("/api/reports/rotation", methods=["GET"])
def report_rotation():
    """
    Rotation report: play counts, last-played timestamps, and rotation depth
    for all tracks, optionally filtered by category.

    Query params:
        category:    filter to a single category name
        sort:        play_count | last_played_at | title | artist (default: play_count)
        order:       asc | desc (default: desc)
        limit:       max tracks to return (default 200)
    """
    tracks   = _load_all(TRACKS_DIR)
    category = request.args.get("category")
    if category:
        tracks = [t for t in tracks if t.get("category") == category]

    sort_by = request.args.get("sort", "play_count")
    desc    = request.args.get("order", "desc").lower() == "desc"
    limit   = int(request.args.get("limit", 200))

    _NUM = {"play_count"}
    if sort_by in _NUM:
        tracks.sort(key=lambda t: (t.get(sort_by) or 0), reverse=desc)
    else:
        tracks.sort(key=lambda t: (t.get(sort_by) or ""), reverse=desc)

    tracks = tracks[:limit]

    report = []
    for t in tracks:
        report.append({
            "id":             t.get("id"),
            "title":          t.get("title"),
            "artist":         t.get("artist"),
            "category":       t.get("category"),
            "play_count":     t.get("play_count", 0),
            "last_played_at": t.get("last_played_at"),
            "active":         t.get("active", True),
            "cart":           t.get("cart", ""),
        })

    # Summary
    total      = len(_load_all(TRACKS_DIR)) if not category else len(
        [t for t in _load_all(TRACKS_DIR) if t.get("category") == category])
    played     = sum(1 for r in report if r["play_count"] > 0)
    never      = sum(1 for r in report if r["play_count"] == 0)
    avg_plays  = (sum(r["play_count"] for r in report) / len(report)) if report else 0

    return jsonify({
        "category":    category,
        "total":       total,
        "played":      played,
        "never_played": never,
        "avg_plays":   round(avg_plays, 2),
        "tracks":      report,
    })


@app.route("/api/reports/artist-separation", methods=["GET"])
def report_artist_separation():
    """Report showing artist play frequency and separation compliance."""
    tracks  = _load_all(TRACKS_DIR)
    artists = _load_all(ARTISTS_DIR)
    art_map = {(a.get("name") or "").lower(): a for a in artists}

    from collections import defaultdict
    by_artist = defaultdict(list)
    for t in tracks:
        key = (t.get("artist") or "").strip().lower()
        if key:
            by_artist[key].append(t)

    rows = []
    for artist_key, artist_tracks in sorted(by_artist.items()):
        art_rec     = art_map.get(artist_key, {})
        total_plays = sum(t.get("play_count", 0) for t in artist_tracks)
        last_played = max(
            (t.get("last_played_at") or "" for t in artist_tracks), default=""
        )
        rows.append({
            "artist":        artist_tracks[0].get("artist") if artist_tracks else artist_key,
            "track_count":   len(artist_tracks),
            "total_plays":   total_plays,
            "last_played_at": last_played or None,
            "separation_ms": art_rec.get("separation_ms", 5400000),
            "group_id":      art_rec.get("group_id"),
        })

    rows.sort(key=lambda r: r["total_plays"], reverse=True)
    return jsonify({"total_artists": len(rows), "rows": rows})


@app.route("/api/reports/category-analysis", methods=["GET"])
def report_category_analysis():
    """Category-level analysis: track count, play count, avg tempo/energy."""
    tracks     = _load_all(TRACKS_DIR)
    categories = _load_all(CATEGORIES_DIR)
    cat_names  = {c["id"]: c["name"] for c in categories}

    from collections import defaultdict
    by_cat = defaultdict(list)
    for t in tracks:
        by_cat[t.get("category") or "Uncategorized"].append(t)

    rows = []
    for cat_name, cat_tracks in sorted(by_cat.items()):
        active    = [t for t in cat_tracks if t.get("active", True)]
        plays     = [t.get("play_count", 0) for t in active]
        tempos    = [t.get("tempo", 0) for t in active if t.get("tempo")]
        rows.append({
            "category":     cat_name,
            "total_tracks": len(cat_tracks),
            "active_tracks": len(active),
            "total_plays":  sum(plays),
            "avg_plays":    round(sum(plays) / len(plays), 2) if plays else 0,
            "avg_tempo":    round(sum(tempos) / len(tempos), 2) if tempos else 0,
            "never_played": sum(1 for p in plays if p == 0),
        })
    rows.sort(key=lambda r: r["total_tracks"], reverse=True)
    return jsonify({"total_categories": len(rows), "rows": rows})


@app.route("/api/reports/compliance", methods=["GET"])
def report_compliance():
    """
    ASCAP/BMI-style compliance report for a date range.

    Query params:
        start_date:  ISO date (default: 7 days ago)
        end_date:    ISO date (default: today)
        format:      json | csv (default: json)
    """
    from datetime import date, timedelta
    today      = date.today()
    start_str  = request.args.get("start_date", (today - timedelta(days=7)).isoformat())
    end_str    = request.args.get("end_date", today.isoformat())
    fmt        = request.args.get("format", "json")

    schedules  = _load_all(SCHEDULES_DIR)
    in_range   = [
        s for s in schedules
        if s.get("date") and start_str <= s["date"][:10] <= end_str
    ]
    in_range.sort(key=lambda s: s.get("date", ""))

    rows = []
    for sched in in_range:
        for t in sched.get("tracks", []):
            if t.get("type", "music") != "music":
                continue
            rows.append({
                "date":           sched.get("date", ""),
                "air_time":       t.get("air_time", ""),
                "title":          t.get("title", ""),
                "artist":         t.get("artist", ""),
                "album":          t.get("album", ""),
                "duration_s":     t.get("duration_seconds", 0),
                "isrc_code":      t.get("isrc_code", ""),
                "publisher":      t.get("publisher", ""),
                "composer":       t.get("composer", ""),
                "record_label":   t.get("record_label", ""),
                "cart":           t.get("cart", ""),
                "category":       t.get("category", ""),
            })

    if fmt == "csv":
        buf    = io.StringIO()
        fields = ["date", "air_time", "title", "artist", "album",
                  "duration_s", "isrc_code", "publisher", "composer",
                  "record_label", "cart", "category"]
        w = csv.DictWriter(buf, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
        return Response(
            buf.getvalue(),
            mimetype="text/csv",
            headers={"Content-Disposition":
                     f"attachment; filename=compliance_{start_str}_{end_str}.csv"},
        )

    return jsonify({
        "start_date":    start_str,
        "end_date":      end_str,
        "total_entries": len(rows),
        "plays":         rows,
    })


@app.route("/api/reports/never-played", methods=["GET"])
def report_never_played():
    """Tracks that have never been scheduled (play_count == 0)."""
    tracks   = _load_all(TRACKS_DIR)
    category = request.args.get("category")
    if category:
        tracks = [t for t in tracks if t.get("category") == category]

    never = [
        {
            "id":       t.get("id"),
            "title":    t.get("title"),
            "artist":   t.get("artist"),
            "category": t.get("category"),
            "added_at": t.get("added_at"),
            "active":   t.get("active", True),
        }
        for t in tracks if not t.get("play_count")
    ]
    never.sort(key=lambda t: t.get("added_at") or "")
    return jsonify({"total": len(never), "tracks": never})


# ---------------------------------------------------------------------------
# Export enhancements  (Music1 .txt log, ASCAP/BMI log)
# ---------------------------------------------------------------------------

def _export_music1_txt(track_list: list, date_str: str) -> str:
    """
    Generate a Music1-style text log.
    Format: fixed-width columns matching Music1's exported .txt log.
    Fields: Cart | AirTime | Title | Artist | Category | Length | Intro | Outro
    """
    lines = [
        f"Music1 Log — {date_str}",
        f"{'Cart':<8} {'Time':>7} {'Title':<35} {'Artist':<30} {'Cat':<12} {'Len':>5} {'Intro':>5} {'Outro':>5}",
        "-" * 108,
    ]
    for t in track_list:
        if t.get("type", "music") != "music":
            continue
        dur_s = int(t.get("duration_seconds") or 0)
        mm, ss = divmod(dur_s, 60)
        intro_s = int((t.get("intro_ms") or 0) / 1000)
        outro_s = int((t.get("outro_ms") or 0) / 1000)
        lines.append(
            f"{str(t.get('cart','')):<8} "
            f"{str(t.get('air_time',''))[:5]:>7} "
            f"{str(t.get('title',''))[:35]:<35} "
            f"{str(t.get('artist',''))[:30]:<30} "
            f"{str(t.get('category',''))[:12]:<12} "
            f"{mm:02d}:{ss:02d} "
            f"{intro_s:>5} "
            f"{outro_s:>5}"
        )
    return "\n".join(lines) + "\n"


def _export_ascap_log(track_list: list, date_str: str) -> str:
    """ASCAP/BMI broadcast log (pipe-delimited)."""
    lines = ["DATE|AIRTIME|TITLE|ARTIST|ALBUM|DURATION|ISRC|PUBLISHER|COMPOSER"]
    for t in track_list:
        if t.get("type", "music") != "music":
            continue
        dur_s = int(t.get("duration_seconds") or 0)
        mm, ss = divmod(dur_s, 60)
        lines.append("|".join([
            date_str,
            str(t.get("air_time", "")),
            str(t.get("title", "")),
            str(t.get("artist", "")),
            str(t.get("album", "")),
            f"{mm:02d}:{ss:02d}",
            str(t.get("isrc_code", "")),
            str(t.get("publisher", "")),
            str(t.get("composer", "")),
        ]))
    return "\n".join(lines) + "\n"


@app.route("/api/export", methods=["POST"])
def api_export():
    data      = request.get_json(silent=True) or {}
    formats   = data.get("formats", ["zetta-log"])

    try:
        schedules  = _load_all(SCHEDULES_DIR)
        if not schedules:
            return jsonify({"success": False,
                            "error": "No schedules to export. Generate a schedule first."}), 400

        # Date-range filter
        start_date = data.get("start_date")
        end_date   = data.get("end_date")
        if start_date or end_date:
            filtered = []
            for s in schedules:
                d = (s.get("date") or s.get("created_at") or "")[:10]
                if start_date and d < start_date:
                    continue
                if end_date and d > end_date:
                    continue
                filtered.append(s)
            schedules = filtered

        if not schedules:
            return jsonify({"success": False,
                            "error": "No schedules found in the specified date range."}), 400

        schedules.sort(key=lambda s: s.get("date") or s.get("created_at") or "")
        # Default: most recent 7
        if not (start_date or end_date):
            schedules = schedules[-7:]

        export_dir = os.path.join(os.path.dirname(__file__), "data", "exports")
        os.makedirs(export_dir, exist_ok=True)

        files_created = 0
        file_names    = []
        for sched in schedules:
            track_list = sched.get("tracks", [])
            date_str   = sched.get("date") or sched.get("created_at", "unknown")[:10]

            for fmt in formats:
                try:
                    if fmt == "csv":
                        fields = ["position", "air_time", "title", "artist",
                                  "category", "duration_seconds", "cart", "album"]
                        buf = io.StringIO()
                        w = csv.DictWriter(buf, fieldnames=fields, extrasaction="ignore")
                        w.writeheader()
                        for i, t in enumerate(track_list):
                            t["position"] = i + 1
                            w.writerow({f: t.get(f, "") for f in fields})
                        base = f"{date_str}.csv"
                        with open(os.path.join(export_dir, base), "w", newline="") as f:
                            f.write(buf.getvalue())
                        files_created += 1
                        file_names.append(base)

                    elif fmt == "music1":
                        base = f"{date_str}_music1.txt"
                        with open(os.path.join(export_dir, base), "w") as f:
                            f.write(_export_music1_txt(track_list, date_str))
                        files_created += 1
                        file_names.append(base)

                    elif fmt == "ascap":
                        base = f"{date_str}_ascap.log"
                        with open(os.path.join(export_dir, base), "w") as f:
                            f.write(_export_ascap_log(track_list, date_str))
                        files_created += 1
                        file_names.append(base)

                    elif fmt == "zetta-log":
                        # Proper Zetta .LOG fixed-width format:
                        # CartID (16 chars, left-justified) + HH:MM:SS + Title (no separator)
                        base = f"{date_str}_zetta.LOG"
                        running_secs = 0
                        with open(os.path.join(export_dir, base), "w", newline="") as f:
                            for t in track_list:
                                air = t.get("air_time") or ""
                                # Normalize to HH:MM:SS
                                parts = air.split(":")
                                if len(parts) == 2:
                                    air = air + ":00"
                                elif len(parts) != 3 or not air:
                                    h, rem = divmod(running_secs, 3600)
                                    m, s   = divmod(rem, 60)
                                    air    = f"{h:02d}:{m:02d}:{s:02d}"
                                cart = str(t.get("cart") or t.get("cart_number") or t.get("id", "")[:8])
                                f.write(f"{cart.ljust(16)}{air}{t.get('title','')}\n")
                                running_secs += int(t.get("duration_seconds") or 0)
                        files_created += 1
                        file_names.append(base)

                    elif fmt == "wideorbit":
                        # WideOrbit/Selector SS32: HHMMSS\tType\tCart\tTitle\tArtist\tLengthSecs
                        base = f"{date_str}_wideorbit.txt"
                        running_secs = 0
                        with open(os.path.join(export_dir, base), "w", newline="") as f:
                            for t in track_list:
                                air = t.get("air_time") or ""
                                parts = air.split(":")
                                if len(parts) == 3:
                                    time_compact = air.replace(":", "")[:6]
                                elif len(parts) == 2:
                                    time_compact = air.replace(":", "") + "00"
                                else:
                                    h, rem = divmod(running_secs, 3600)
                                    m, s   = divmod(rem, 60)
                                    time_compact = f"{h:02d}{m:02d}{s:02d}"
                                dur_s = int(t.get("duration_seconds") or 0)
                                cart  = str(t.get("cart") or t.get("cart_number") or "")
                                title  = str(t.get("title", "")).replace("\t", " ")
                                artist = str(t.get("artist", "")).replace("\t", " ")
                                f.write(f"{time_compact}\tM\t{cart}\t{title}\t{artist}\t{dur_s}\n")
                                running_secs += dur_s
                        files_created += 1
                        file_names.append(base)

                    elif fmt == "enco":
                        # ENCO DAD: MM/DD/YYYY,HH:MM:SS,SONG,Cart,Title,Artist,LengthSecs
                        base = f"{date_str}_enco.csv"
                        running_secs = 0
                        with open(os.path.join(export_dir, base), "w", newline="") as f:
                            for t in track_list:
                                air = t.get("air_time") or ""
                                parts = air.split(":")
                                if len(parts) == 2:
                                    air = air + ":00"
                                elif len(parts) != 3 or not air:
                                    h, rem = divmod(running_secs, 3600)
                                    m, s   = divmod(rem, 60)
                                    air    = f"{h:02d}:{m:02d}:{s:02d}"
                                try:
                                    from datetime import datetime as _dt
                                    d_obj = _dt.strptime(date_str, "%Y-%m-%d")
                                    date_fmt = d_obj.strftime("%m/%d/%Y")
                                except Exception:
                                    date_fmt = date_str
                                dur_s  = int(t.get("duration_seconds") or 0)
                                cart   = str(t.get("cart") or t.get("cart_number") or "").replace(",", " ")
                                title  = str(t.get("title", "")).replace(",", " ")
                                artist = str(t.get("artist", "")).replace(",", " ")
                                f.write(f"{date_fmt},{air},SONG,{cart},{title},{artist},{dur_s}\n")
                                running_secs += dur_s
                        files_created += 1
                        file_names.append(base)

                except Exception:
                    pass

        return jsonify({
            "success":       True,
            "message":       f"Exported {len(schedules)} schedule(s)",
            "files_created": files_created,
            "file_names":    file_names,
        })

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/export/download/<path:filename>")
def api_export_download(filename):
    """Serve an exported file as a download."""
    from flask import send_file
    export_dir = os.path.join(os.path.dirname(__file__), "data", "exports")
    safe_path  = os.path.normpath(os.path.join(export_dir, filename))
    if not safe_path.startswith(os.path.normpath(export_dir)):
        return jsonify({"error": "Invalid path"}), 400
    if not os.path.exists(safe_path):
        return jsonify({"error": "File not found"}), 404
    return send_file(safe_path, as_attachment=True,
                     download_name=os.path.basename(safe_path))


@app.route("/api/export/ftp", methods=["POST"])
def api_export_ftp():
    """
    Upload one or more exported files to an FTP server.

    Body:
        host:       FTP hostname
        port:       FTP port (default 21)
        username:   FTP username
        password:   FTP password
        remote_dir: remote directory path (default "/")
        filenames:  list of filenames (from data/exports/) to upload
    """
    data       = request.get_json(silent=True) or {}
    host       = data.get("host")
    port       = int(data.get("port", 21))
    username   = data.get("username", "")
    password   = data.get("password", "")
    remote_dir = data.get("remote_dir", "/")
    filenames  = data.get("filenames") or []

    if not host:
        return jsonify({"error": "Missing required field: host"}), 400
    if not filenames:
        return jsonify({"error": "Missing required field: filenames"}), 400

    export_dir = os.path.join(os.path.dirname(__file__), "data", "exports")
    uploaded   = []
    errors     = []

    try:
        ftp = ftplib.FTP()
        ftp.connect(host, port, timeout=30)
        ftp.login(username, password)
        try:
            ftp.cwd(remote_dir)
        except ftplib.error_perm:
            pass  # directory may not exist; best-effort

        for fname in filenames:
            safe = os.path.normpath(os.path.join(export_dir, fname))
            if not safe.startswith(os.path.normpath(export_dir)):
                errors.append({"file": fname, "error": "Invalid path"})
                continue
            if not os.path.exists(safe):
                errors.append({"file": fname, "error": "File not found"})
                continue
            try:
                with open(safe, "rb") as fh:
                    ftp.storbinary(f"STOR {os.path.basename(fname)}", fh)
                uploaded.append(fname)
            except Exception as exc:
                errors.append({"file": fname, "error": str(exc)})

        ftp.quit()
    except Exception as exc:
        return jsonify({"success": False, "error": str(exc),
                        "uploaded": uploaded, "errors": errors}), 502

    return jsonify({
        "success":  len(errors) == 0,
        "uploaded": uploaded,
        "errors":   errors,
    })


if __name__ == "__main__":
    app.run(debug=True)
