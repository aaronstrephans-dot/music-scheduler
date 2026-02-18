"""
Tests for GET /api/schedule/<id>/export
"""
import csv
import io
import json
import os

import pytest

import app as app_module
from app import app

_TRACKS = [
    {"position": 1, "title": "Song A", "artist": "Artist 1",
     "category": "Current", "duration_seconds": 180, "bpm": 120, "energy": 7},
    {"position": 2, "title": "Song B", "artist": "Artist 2",
     "category": "Gold",    "duration_seconds": 210, "bpm": 100, "energy": 5},
    {"position": 3, "title": "Song C", "artist": "Artist 3",
     "category": "Current", "duration_seconds": 195, "bpm": 130, "energy": 8},
]


@pytest.fixture(autouse=True)
def isolated_dirs(monkeypatch, tmp_path):
    for attr, subdir in [
        ("SCHEDULES_DIR", "schedules"),
        ("TRACKS_DIR",    "tracks"),
        ("CLOCKS_DIR",    "clocks"),
    ]:
        d = str(tmp_path / subdir)
        os.makedirs(d)
        monkeypatch.setattr(app_module, attr, d)


@pytest.fixture
def client():
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


@pytest.fixture
def schedule(client):
    resp = client.post(
        "/api/schedule/generate",
        data=json.dumps({"name": "Morning Show", "tracks": _TRACKS}),
        content_type="application/json",
    )
    return resp.get_json()


# ---------------------------------------------------------------------------
# CSV export
# ---------------------------------------------------------------------------

def test_export_csv_status_and_content_type(client, schedule):
    resp = client.get(f"/api/schedule/{schedule['id']}/export")
    assert resp.status_code == 200
    assert "text/csv" in resp.content_type


def test_export_csv_has_correct_rows(client, schedule):
    resp   = client.get(f"/api/schedule/{schedule['id']}/export")
    reader = csv.DictReader(io.StringIO(resp.data.decode()))
    rows   = list(reader)
    assert len(rows) == 3
    assert rows[0]["title"]  == "Song A"
    assert rows[1]["artist"] == "Artist 2"


def test_export_csv_correct_columns(client, schedule):
    resp    = client.get(f"/api/schedule/{schedule['id']}/export")
    reader  = csv.DictReader(io.StringIO(resp.data.decode()))
    columns = reader.fieldnames
    for col in ("position", "title", "artist", "category", "duration_seconds", "bpm"):
        assert col in columns, f"Missing column: {col}"


def test_export_csv_content_disposition_header(client, schedule):
    resp = client.get(f"/api/schedule/{schedule['id']}/export")
    assert "attachment" in resp.headers.get("Content-Disposition", "")


# ---------------------------------------------------------------------------
# Air time calculation
# ---------------------------------------------------------------------------

def test_export_csv_with_start_time(client, schedule):
    resp   = client.get(f"/api/schedule/{schedule['id']}/export?start_time=06:00")
    reader = csv.DictReader(io.StringIO(resp.data.decode()))
    rows   = list(reader)

    # Slot 1 → 06:00:00, slot 2 → 06:03:00 (180s later), slot 3 → 06:06:30
    assert rows[0]["air_time"] == "06:00:00"
    assert rows[1]["air_time"] == "06:03:00"
    assert rows[2]["air_time"] == "06:06:30"


def test_export_csv_midnight_rollover(client, schedule):
    """Air times past midnight should roll over correctly (no negative hours)."""
    resp   = client.get(f"/api/schedule/{schedule['id']}/export?start_time=23:59")
    reader = csv.DictReader(io.StringIO(resp.data.decode()))
    rows   = list(reader)
    # All air_time values should be parseable HH:MM:SS strings
    for row in rows:
        h, m, s = (int(x) for x in row["air_time"].split(":"))
        assert 0 <= h < 24
        assert 0 <= m < 60
        assert 0 <= s < 60


# ---------------------------------------------------------------------------
# JSON export
# ---------------------------------------------------------------------------

def test_export_json_format(client, schedule):
    resp = client.get(f"/api/schedule/{schedule['id']}/export?format=json")
    assert resp.status_code == 200
    assert "application/json" in resp.content_type
    body = resp.get_json()
    assert body["id"]    == schedule["id"]
    assert body["name"]  == "Morning Show"
    assert len(body["tracks"]) == 3


def test_export_json_with_start_time(client, schedule):
    resp   = client.get(
        f"/api/schedule/{schedule['id']}/export?format=json&start_time=09:00"
    )
    tracks = resp.get_json()["tracks"]
    assert tracks[0]["air_time"] == "09:00:00"


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------

def test_export_not_found(client):
    resp = client.get("/api/schedule/nonexistent/export")
    assert resp.status_code == 404
