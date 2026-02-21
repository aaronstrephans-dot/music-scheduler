import json
import os

import pytest

import app as app_module
from app import app


@pytest.fixture(autouse=True)
def isolated_schedules_dir(monkeypatch, tmp_path):
    tmp_dir = str(tmp_path / "schedules")
    os.makedirs(tmp_dir)
    monkeypatch.setattr(app_module, "SCHEDULES_DIR", tmp_dir)
    yield tmp_dir


@pytest.fixture
def client():
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


def test_index(client):
    resp = client.get("/api/status")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["service"] == "music-scheduler"
    assert data["status"] == "ok"


def test_generate_schedule_creates_file(client, isolated_schedules_dir):
    payload = {
        "name": "Morning Classics",
        "tracks": [
            {"title": "Track 1", "artist": "Artist A",
             "category": "Current", "duration_seconds": 210},
            {"title": "Track 2", "artist": "Artist B",
             "category": "Current", "duration_seconds": 210},
        ],
        "duration_minutes": 30,
    }
    resp = client.post(
        "/api/schedule/generate",
        data=json.dumps(payload),
        content_type="application/json",
    )
    assert resp.status_code == 201
    body = resp.get_json()
    assert body["name"] == "Morning Classics"
    assert "id" in body

    # Verify the file was actually saved
    saved_file = os.path.join(isolated_schedules_dir, f"{body['id']}.json")
    assert os.path.exists(saved_file), "Schedule file was not saved to data/schedules/"
    with open(saved_file) as f:
        saved = json.load(f)
    assert saved["id"] == body["id"]


def test_generate_schedule_defaults(client):
    resp = client.post("/api/schedule/generate", content_type="application/json")
    assert resp.status_code == 201
    body = resp.get_json()
    assert body["name"] == "Untitled Schedule"
    assert body["duration_minutes"] == 60


def test_list_schedules(client, isolated_schedules_dir):
    # Generate two schedules first
    for name in ("Schedule A", "Schedule B"):
        client.post(
            "/api/schedule/generate",
            data=json.dumps({"name": name}),
            content_type="application/json",
        )

    resp = client.get("/api/schedules")
    assert resp.status_code == 200
    schedules = resp.get_json()
    assert len(schedules) == 2
    names = {s["name"] for s in schedules}
    assert names == {"Schedule A", "Schedule B"}


def test_get_schedule(client):
    gen = client.post(
        "/api/schedule/generate",
        data=json.dumps({"name": "Specific Schedule"}),
        content_type="application/json",
    ).get_json()

    resp = client.get(f"/api/schedule/{gen['id']}")
    assert resp.status_code == 200
    assert resp.get_json()["name"] == "Specific Schedule"


def test_get_schedule_not_found(client):
    resp = client.get("/api/schedule/nonexistent-id")
    assert resp.status_code == 404


def test_update_schedule(client):
    gen = client.post(
        "/api/schedule/generate",
        data=json.dumps({"name": "Old Name"}),
        content_type="application/json",
    ).get_json()

    resp = client.put(
        f"/api/schedule/{gen['id']}",
        data=json.dumps({"name": "New Name"}),
        content_type="application/json",
    )
    assert resp.status_code == 200
    assert resp.get_json()["name"] == "New Name"


def test_delete_schedule(client):
    gen = client.post(
        "/api/schedule/generate",
        data=json.dumps({"name": "To Delete"}),
        content_type="application/json",
    ).get_json()

    resp = client.delete(f"/api/schedule/{gen['id']}")
    assert resp.status_code == 204
    assert client.get(f"/api/schedule/{gen['id']}").status_code == 404


def test_delete_schedule_not_found(client):
    assert client.delete("/api/schedule/nonexistent").status_code == 404
