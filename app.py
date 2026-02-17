import json
import os
import uuid
from datetime import datetime

from flask import Flask, jsonify, request

app = Flask(__name__)

SCHEDULES_DIR = os.path.join(os.path.dirname(__file__), "data", "schedules")


def ensure_schedules_dir():
    """Create data/schedules/ directory if it does not exist."""
    os.makedirs(SCHEDULES_DIR, exist_ok=True)


@app.route("/")
def index():
    return jsonify({"service": "music-scheduler", "status": "ok"})


@app.route("/api/schedules", methods=["GET"])
def list_schedules():
    ensure_schedules_dir()
    schedules = []
    for filename in os.listdir(SCHEDULES_DIR):
        if filename.endswith(".json"):
            filepath = os.path.join(SCHEDULES_DIR, filename)
            with open(filepath) as f:
                schedules.append(json.load(f))
    return jsonify(schedules)


@app.route("/api/schedule/<schedule_id>", methods=["GET"])
def get_schedule(schedule_id):
    ensure_schedules_dir()
    filepath = os.path.join(SCHEDULES_DIR, f"{schedule_id}.json")
    if not os.path.exists(filepath):
        return jsonify({"error": "Schedule not found"}), 404
    with open(filepath) as f:
        return jsonify(json.load(f))


@app.route("/api/schedule/generate", methods=["POST"])
def generate_schedule():
    """Generate a music schedule and save it to data/schedules/."""
    data = request.get_json(silent=True) or {}

    schedule_id = str(uuid.uuid4())
    schedule = {
        "id": schedule_id,
        "created_at": datetime.utcnow().isoformat() + "Z",
        "name": data.get("name", "Untitled Schedule"),
        "tracks": data.get("tracks", []),
        "duration_minutes": data.get("duration_minutes", 60),
    }

    # Bug fix: ensure directory exists before writing
    ensure_schedules_dir()

    filepath = os.path.join(SCHEDULES_DIR, f"{schedule_id}.json")
    with open(filepath, "w") as f:
        json.dump(schedule, f, indent=2)

    return jsonify(schedule), 201


if __name__ == "__main__":
    app.run(debug=True)
