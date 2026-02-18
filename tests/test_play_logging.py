import json
import os

import pytest

import app as app_module
from app import app

_TRACK = {
    "title":    "Levitating",
    "artist":   "Dua Lipa",
    "category": "Current",
}


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


@pytest.fixture
def track(client):
    return client.post("/api/tracks", data=json.dumps(_TRACK),
                       content_type="application/json").get_json()


def test_log_play_increments_count(client, track):
    resp = client.post(f"/api/tracks/{track['id']}/play",
                       content_type="application/json")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["play_count"] == 1

    # Play again — count should reach 2
    resp2 = client.post(f"/api/tracks/{track['id']}/play",
                        content_type="application/json")
    assert resp2.get_json()["play_count"] == 2


def test_log_play_sets_last_played_at(client, track):
    assert track["last_played_at"] is None
    resp = client.post(f"/api/tracks/{track['id']}/play",
                       content_type="application/json")
    assert resp.get_json()["last_played_at"] is not None


def test_log_play_custom_timestamp(client, track):
    ts   = "2025-06-01T08:00:00Z"
    resp = client.post(
        f"/api/tracks/{track['id']}/play",
        data=json.dumps({"played_at": ts}),
        content_type="application/json",
    )
    assert resp.status_code == 200
    assert resp.get_json()["last_played_at"] == ts


def test_log_play_persists_to_disk(client, track):
    """After logging a play, GET /api/tracks/<id> should reflect the updated count."""
    client.post(f"/api/tracks/{track['id']}/play", content_type="application/json")
    client.post(f"/api/tracks/{track['id']}/play", content_type="application/json")
    fetched = client.get(f"/api/tracks/{track['id']}").get_json()
    assert fetched["play_count"] == 2


def test_log_play_not_found(client):
    resp = client.post("/api/tracks/nonexistent/play", content_type="application/json")
    assert resp.status_code == 404


def test_play_count_influences_rotation(client):
    """
    After many plays, the rotation engine should prefer the fresher track.
    Uses GET /api/tracks to confirm play_count is stored correctly.
    """
    # Create two tracks
    fresh = client.post("/api/tracks",
                        data=json.dumps({**_TRACK, "title": "Fresh Hit"}),
                        content_type="application/json").get_json()
    stale = client.post("/api/tracks",
                        data=json.dumps({**_TRACK, "title": "Stale Hit",
                                         "artist": "Old Artist"}),
                        content_type="application/json").get_json()

    # Log many plays for stale
    for _ in range(10):
        client.post(f"/api/tracks/{stale['id']}/play", content_type="application/json")

    # Confirm counts via the list endpoint
    tracks = client.get("/api/tracks?sort=play_count&order=desc").get_json()["tracks"]
    assert tracks[0]["id"]         == stale["id"]
    assert tracks[0]["play_count"] == 10
    assert tracks[1]["play_count"] == 0
