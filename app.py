import json
import os
import uuid
from datetime import datetime

import ai
from flask import Flask, jsonify, request

app = Flask(__name__)

SCHEDULES_DIR = os.path.join(os.path.dirname(__file__), "data", "schedules")
os.makedirs(SCHEDULES_DIR, exist_ok=True)


# ---------------------------------------------------------------------------
# Core routes
# ---------------------------------------------------------------------------

@app.route("/")
def index():
    return jsonify({
        "service": "music-scheduler",
        "status": "ok",
        "ai_available": ai.is_available(),
    })


@app.route("/api/schedules", methods=["GET"])
def list_schedules():
    schedules = []
    for filename in os.listdir(SCHEDULES_DIR):
        if filename.endswith(".json"):
            filepath = os.path.join(SCHEDULES_DIR, filename)
            with open(filepath) as f:
                schedules.append(json.load(f))
    return jsonify(schedules)


@app.route("/api/schedule/<schedule_id>", methods=["GET"])
def get_schedule(schedule_id):
    filepath = os.path.join(SCHEDULES_DIR, f"{schedule_id}.json")
    if not os.path.exists(filepath):
        return jsonify({"error": "Schedule not found"}), 404
    with open(filepath) as f:
        return jsonify(json.load(f))


@app.route("/api/schedule/generate", methods=["POST"])
def generate_schedule():
    data = request.get_json(silent=True) or {}

    schedule_id = str(uuid.uuid4())
    schedule = {
        "id": schedule_id,
        "created_at": datetime.utcnow().isoformat() + "Z",
        "name": data.get("name", "Untitled Schedule"),
        "tracks": data.get("tracks", []),
        "duration_minutes": data.get("duration_minutes", 60),
    }

    filepath = os.path.join(SCHEDULES_DIR, f"{schedule_id}.json")
    with open(filepath, "w") as f:
        json.dump(schedule, f, indent=2)

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
