import csv
import io
import json
import os
import uuid
from collections import Counter
from datetime import datetime

import ai
from engine.models import (
    make_track, make_artist, make_category, make_daypart,
    make_day_template, make_clock, make_slot, DEFAULT_DAYPARTS,
)
from engine.rotator import build_schedule
from engine.rules import DEFAULT_RULES, merge_rules
from engine.validator import validate_schedule, _hms
from flask import Flask, Response, jsonify, render_template, request

app = Flask(__name__)

SCHEDULES_DIR     = os.path.join(os.path.dirname(__file__), "data", "schedules")
TRACKS_DIR        = os.path.join(os.path.dirname(__file__), "data", "tracks")
CLOCKS_DIR        = os.path.join(os.path.dirname(__file__), "data", "clocks")
ARTISTS_DIR       = os.path.join(os.path.dirname(__file__), "data", "artists")
CATEGORIES_DIR    = os.path.join(os.path.dirname(__file__), "data", "categories")
DAYPARTS_DIR      = os.path.join(os.path.dirname(__file__), "data", "dayparts")
DAY_TEMPLATES_DIR = os.path.join(os.path.dirname(__file__), "data", "day_templates")
PLAY_HISTORY_DIR  = os.path.join(os.path.dirname(__file__), "data", "play_history")
RULES_FILE        = os.path.join(os.path.dirname(__file__), "data", "rules.json")

for _d in (SCHEDULES_DIR, TRACKS_DIR, CLOCKS_DIR, ARTISTS_DIR, CATEGORIES_DIR,
            DAYPARTS_DIR, DAY_TEMPLATES_DIR, PLAY_HISTORY_DIR):
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

    search = (request.args.get("search") or "").strip().lower()
    if search:
        tracks = [
            t for t in tracks
            if search in (t.get("title")  or "").lower()
            or search in (t.get("artist") or "").lower()
        ]

    sort_by    = request.args.get("sort", "added_at")
    order_desc = request.args.get("order", "asc").lower() == "desc"
    _SORTABLE  = {"added_at", "title", "artist", "play_count", "last_played_at",
                  "bpm", "energy", "tempo", "mood", "gender"}
    _NUMERIC   = {"play_count", "bpm", "energy", "tempo", "mood", "gender"}
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
    week_str = f"{start.strftime('%b %-d')}–{end.strftime('%-d')}"

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
    data       = request.get_json(silent=True) or {}
    start_date = data.get("start_date")
    strategy   = data.get("strategy", "standard")

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

        slots_filled = 0
        total_slots  = 0
        days_generated = 0

        for day_offset in range(7):
            day = target + timedelta(days=day_offset)
            day_str = day.isoformat()

            # Pick a day template or use first available
            tmpl = next((t for t in tmpls), None)
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


# ---------------------------------------------------------------------------
# Export  (called by export.html)
# ---------------------------------------------------------------------------

@app.route("/api/export", methods=["POST"])
def api_export():
    data      = request.get_json(silent=True) or {}
    formats   = data.get("formats", ["zetta-log"])
    scope     = data.get("scope", "day")

    try:
        schedules  = _load_all(SCHEDULES_DIR)
        if not schedules:
            return jsonify({"success": False, "error": "No schedules to export. Generate a schedule first."}), 400

        # Sort by date, take most recent 7
        schedules.sort(key=lambda s: s.get("date") or s.get("created_at") or "")
        recent = schedules[-7:]

        import os
        export_dir = os.path.join(os.path.dirname(__file__), "data", "exports")
        os.makedirs(export_dir, exist_ok=True)

        files_created = 0
        for sched in recent:
            track_list = sched.get("tracks", [])
            date_str   = sched.get("date") or sched.get("created_at", "unknown")[:10]

            for fmt in formats:
                try:
                    if fmt == "csv":
                        import csv, io
                        fields = ["position","air_time","title","artist","category","duration_seconds"]
                        buf = io.StringIO()
                        w = csv.DictWriter(buf, fieldnames=fields, extrasaction="ignore")
                        w.writeheader()
                        for i, t in enumerate(track_list):
                            t["position"] = i + 1
                            w.writerow({f: t.get(f, "") for f in fields})
                        fname = os.path.join(export_dir, f"{date_str}.csv")
                        with open(fname, "w") as f:
                            f.write(buf.getvalue())
                        files_created += 1
                    elif fmt in ("zetta-log", "zetta-xml", "wideorbit", "enco"):
                        # Write a simple text log for now
                        fname = os.path.join(export_dir, f"{date_str}_{fmt.replace('-','_')}.txt")
                        with open(fname, "w") as f:
                            f.write(f"# {fmt.upper()} Export — {date_str}\n")
                            for t in track_list:
                                f.write(f"{t.get('air_time','')}\t{t.get('title','')}\t{t.get('artist','')}\n")
                        files_created += 1
                except Exception:
                    pass

        return jsonify({
            "success":       True,
            "message":       f"Exported {len(recent)} schedule(s)",
            "files_created": files_created,
        })

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


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
        # No exact match — return empty schedule
        return jsonify({"date": date, "schedule": []})

    # Merge all matching schedules' tracks, sorted by air_time
    all_tracks = []
    for s in matching:
        all_tracks.extend(s.get("tracks", []))

    all_tracks.sort(key=lambda t: t.get("air_time") or t.get("position") or 0)

    schedule = []
    for t in all_tracks:
        air = t.get("air_time", "")
        if air:
            try:
                h, m, s2 = [int(x) for x in air.split(":")]
                suffix = "AM" if h < 12 else "PM"
                dh = h % 12 or 12
                time_str = f"{dh}:{m:02d} {suffix}"
            except Exception:
                time_str = air
        else:
            time_str = "—"

        dur_secs = t.get("duration_seconds") or 0
        dur_str  = f"{dur_secs // 60}:{dur_secs % 60:02d}" if dur_secs else "—"

        schedule.append({
            "time":        time_str,
            "song_id":     t.get("id") or t.get("song_id") or "",
            "title":       t.get("title") or "Unknown",
            "artist":      t.get("artist") or "",
            "category":    t.get("category") or "Uncategorized",
            "length":      dur_str,
            "has_error":   bool(t.get("has_error")),
            "has_warning": bool(t.get("has_warning")),
            "error":       t.get("error") or "",
            "warning":     t.get("warning") or "",
            "position":    t.get("position") or 0,
        })

    return jsonify({"date": date, "schedule": schedule})


if __name__ == "__main__":
    app.run(debug=True)
