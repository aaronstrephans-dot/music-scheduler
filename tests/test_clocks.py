import json
import os

import pytest

import app as app_module
from app import app

_CLOCK = {
    "name":  "Morning Drive",
    "slots": [
        {"position": 1, "category": "Current",   "duration_seconds": 210, "notes": "opener"},
        {"position": 2, "category": "Gold",       "duration_seconds": 195, "notes": ""},
        {"position": 3, "category": "Current",    "duration_seconds": 205, "notes": ""},
        {"position": 4, "category": "Recurrent",  "duration_seconds": 200, "notes": ""},
    ],
}

_TRACK = {
    "title":            "Test Song",
    "artist":           "Test Artist",
    "category":         "Current",
    "duration_seconds": 210,
    "bpm":              120,
    "energy":           7,
}


@pytest.fixture(autouse=True)
def isolated_clocks_dir(monkeypatch, tmp_path):
    tmp_dir = str(tmp_path / "clocks")
    os.makedirs(tmp_dir)
    monkeypatch.setattr(app_module, "CLOCKS_DIR", tmp_dir)
    yield tmp_dir


@pytest.fixture(autouse=True)
def isolated_schedules_dir(monkeypatch, tmp_path):
    tmp_dir = str(tmp_path / "schedules")
    os.makedirs(tmp_dir)
    monkeypatch.setattr(app_module, "SCHEDULES_DIR", tmp_dir)
    yield tmp_dir


@pytest.fixture(autouse=True)
def isolated_tracks_dir(monkeypatch, tmp_path):
    tmp_dir = str(tmp_path / "tracks")
    os.makedirs(tmp_dir)
    monkeypatch.setattr(app_module, "TRACKS_DIR", tmp_dir)
    yield tmp_dir


@pytest.fixture
def client():
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


# ---------------------------------------------------------------------------
# Create
# ---------------------------------------------------------------------------

def test_create_clock(client):
    resp = client.post("/api/clocks", data=json.dumps(_CLOCK), content_type="application/json")
    assert resp.status_code == 201
    data = resp.get_json()
    assert data["name"]       == "Morning Drive"
    assert len(data["slots"]) == 4
    assert "id"               in data
    assert "created_at"       in data


def test_create_clock_missing_name(client):
    resp = client.post("/api/clocks",
                       data=json.dumps({"slots": _CLOCK["slots"]}),
                       content_type="application/json")
    assert resp.status_code == 400


def test_create_clock_missing_slots(client):
    resp = client.post("/api/clocks",
                       data=json.dumps({"name": "No Slots"}),
                       content_type="application/json")
    assert resp.status_code == 400


# ---------------------------------------------------------------------------
# Read
# ---------------------------------------------------------------------------

def test_get_clock(client):
    created = client.post("/api/clocks", data=json.dumps(_CLOCK),
                          content_type="application/json").get_json()
    resp = client.get(f"/api/clocks/{created['id']}")
    assert resp.status_code == 200
    assert resp.get_json()["name"] == "Morning Drive"


def test_get_clock_not_found(client):
    assert client.get("/api/clocks/nonexistent").status_code == 404


def test_list_clocks(client):
    for name in ("Morning Drive", "Evening Mix", "Overnight"):
        client.post("/api/clocks",
                    data=json.dumps({**_CLOCK, "name": name}),
                    content_type="application/json")
    resp = client.get("/api/clocks")
    assert resp.status_code == 200
    assert len(resp.get_json()) == 3


# ---------------------------------------------------------------------------
# Update
# ---------------------------------------------------------------------------

def test_update_clock_name(client):
    created = client.post("/api/clocks", data=json.dumps(_CLOCK),
                          content_type="application/json").get_json()
    resp = client.put(
        f"/api/clocks/{created['id']}",
        data=json.dumps({"name": "Updated Morning Drive"}),
        content_type="application/json",
    )
    assert resp.status_code == 200
    assert resp.get_json()["name"] == "Updated Morning Drive"
    # Slots unchanged
    assert len(resp.get_json()["slots"]) == 4


def test_update_clock_not_found(client):
    resp = client.put("/api/clocks/bad-id",
                      data=json.dumps({"name": "X"}),
                      content_type="application/json")
    assert resp.status_code == 404


def test_update_clock_cannot_change_id(client):
    created     = client.post("/api/clocks", data=json.dumps(_CLOCK),
                               content_type="application/json").get_json()
    original_id = created["id"]
    updated     = client.put(
        f"/api/clocks/{original_id}",
        data=json.dumps({"id": "hacked"}),
        content_type="application/json",
    ).get_json()
    assert updated["id"] == original_id


# ---------------------------------------------------------------------------
# Delete
# ---------------------------------------------------------------------------

def test_delete_clock(client):
    created = client.post("/api/clocks", data=json.dumps(_CLOCK),
                          content_type="application/json").get_json()
    resp = client.delete(f"/api/clocks/{created['id']}")
    assert resp.status_code == 204
    assert client.get(f"/api/clocks/{created['id']}").status_code == 404


def test_delete_clock_not_found(client):
    assert client.delete("/api/clocks/nonexistent").status_code == 404


# ---------------------------------------------------------------------------
# Rotation-mode schedule generation
# ---------------------------------------------------------------------------

def _make_tracks(client, count=6):
    """Create `count` Current tracks and return their IDs."""
    ids = []
    for i in range(count):
        t = client.post(
            "/api/tracks",
            data=json.dumps({**_TRACK, "title": f"Song {i}", "artist": f"Artist {i}"}),
            content_type="application/json",
        ).get_json()
        ids.append(t["id"])
    return ids


def test_rotation_schedule_fills_slots(client):
    _make_tracks(client, count=6)
    clock = client.post("/api/clocks", data=json.dumps({
        "name":  "Test Hour",
        "slots": [
            {"position": i + 1, "category": "Current", "duration_seconds": 210, "notes": ""}
            for i in range(4)
        ],
    }), content_type="application/json").get_json()

    resp = client.post(
        "/api/schedule/generate",
        data=json.dumps({"clock_id": clock["id"]}),
        content_type="application/json",
    )
    assert resp.status_code == 201
    schedule = resp.get_json()
    assert len(schedule["tracks"])    == 4
    assert schedule["clock_id"]       == clock["id"]
    assert all("track_id" in t for t in schedule["tracks"])
    assert all("artist"   in t for t in schedule["tracks"])


def test_rotation_schedule_bad_clock_id(client):
    resp = client.post(
        "/api/schedule/generate",
        data=json.dumps({"clock_id": "nonexistent"}),
        content_type="application/json",
    )
    assert resp.status_code == 404


def test_rotation_schedule_custom_name(client):
    _make_tracks(client, count=3)
    clock = client.post("/api/clocks", data=json.dumps({
        "name":  "Evening",
        "slots": [{"position": 1, "category": "Current", "duration_seconds": 210, "notes": ""}],
    }), content_type="application/json").get_json()

    resp = client.post(
        "/api/schedule/generate",
        data=json.dumps({"clock_id": clock["id"], "name": "My Custom Evening"}),
        content_type="application/json",
    )
    assert resp.get_json()["name"] == "My Custom Evening"
