import json
from unittest.mock import MagicMock, patch

import pytest

from app import app


@pytest.fixture
def client():
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


@pytest.fixture
def mock_provider():
    provider = MagicMock()
    provider.analyze_flow.return_value = {
        "flow_score": 8,
        "energy_arc": "Builds steadily through the hour then eases into a cool-down",
        "issues": [],
        "suggestions": ["Consider adding a tempo break after track 3"],
    }
    provider.generate_clock.return_value = {
        "name": "Morning Drive AC",
        "slots": [
            {"position": 1, "category": "Current", "duration_seconds": 210, "notes": "Opener — high energy"},
            {"position": 2, "category": "Gold", "duration_seconds": 195, "notes": ""},
            {"position": 3, "category": "Current", "duration_seconds": 200, "notes": ""},
        ],
    }
    provider.suggest_rules.return_value = {
        "artist_separation_songs": 9,
        "title_separation_hours": 3,
        "categories": [
            {"name": "Current", "rotation_hours": 2, "weight": 40},
            {"name": "Recurrent", "rotation_hours": 4, "weight": 30},
            {"name": "Gold", "rotation_hours": 6, "weight": 30},
        ],
        "notes": ["Avoid back-to-back female vocals in morning drive"],
    }
    return provider


# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------

def test_health_no_ai(client):
    with patch("ai.get_provider", return_value=None):
        data = client.get("/api/status").get_json()
    assert data["ai_available"] is False


def test_health_with_ai(client, mock_provider):
    with patch("ai.get_provider", return_value=mock_provider):
        data = client.get("/api/status").get_json()
    assert data["ai_available"] is True


# ---------------------------------------------------------------------------
# Flow analysis
# ---------------------------------------------------------------------------

def test_analyze_flow_no_provider(client):
    with patch("ai.get_provider", return_value=None):
        resp = client.post(
            "/api/ai/schedule/analyze",
            data=json.dumps({"tracks": []}),
            content_type="application/json",
        )
    assert resp.status_code == 503
    assert resp.get_json()["ai_available"] is False


def test_analyze_flow_success(client, mock_provider):
    tracks = [
        {"title": "Song A", "artist": "Artist 1", "bpm": 128, "energy": 8, "mood": "energetic"},
        {"title": "Song B", "artist": "Artist 2", "bpm": 110, "energy": 6, "mood": "upbeat"},
    ]
    with patch("ai.get_provider", return_value=mock_provider):
        resp = client.post(
            "/api/ai/schedule/analyze",
            data=json.dumps({"tracks": tracks}),
            content_type="application/json",
        )
    assert resp.status_code == 200
    data = resp.get_json()
    assert "flow_score" in data
    assert "energy_arc" in data
    assert "suggestions" in data
    mock_provider.analyze_flow.assert_called_once_with(tracks)


def test_analyze_flow_provider_error(client, mock_provider):
    mock_provider.analyze_flow.side_effect = RuntimeError("upstream timeout")
    with patch("ai.get_provider", return_value=mock_provider):
        resp = client.post(
            "/api/ai/schedule/analyze",
            data=json.dumps({"tracks": []}),
            content_type="application/json",
        )
    assert resp.status_code == 502
    assert "error" in resp.get_json()


# ---------------------------------------------------------------------------
# Clock generation
# ---------------------------------------------------------------------------

def test_generate_clock_no_provider(client):
    with patch("ai.get_provider", return_value=None):
        resp = client.post(
            "/api/ai/clock/generate",
            data=json.dumps({"description": "morning drive"}),
            content_type="application/json",
        )
    assert resp.status_code == 503


def test_generate_clock_success(client, mock_provider):
    with patch("ai.get_provider", return_value=mock_provider):
        resp = client.post(
            "/api/ai/clock/generate",
            data=json.dumps({"description": "morning drive AC", "slots": 8}),
            content_type="application/json",
        )
    assert resp.status_code == 200
    data = resp.get_json()
    assert "slots" in data
    mock_provider.generate_clock.assert_called_once_with("morning drive AC", 8)


def test_generate_clock_defaults(client, mock_provider):
    """slots should default to 8 when not supplied."""
    with patch("ai.get_provider", return_value=mock_provider):
        client.post(
            "/api/ai/clock/generate",
            data=json.dumps({"description": "evening chill"}),
            content_type="application/json",
        )
    mock_provider.generate_clock.assert_called_once_with("evening chill", 8)


# ---------------------------------------------------------------------------
# Rule suggestions
# ---------------------------------------------------------------------------

def test_suggest_rules_no_provider(client):
    with patch("ai.get_provider", return_value=None):
        resp = client.post(
            "/api/ai/rules/suggest",
            data=json.dumps({"description": "Hot AC station"}),
            content_type="application/json",
        )
    assert resp.status_code == 503


def test_suggest_rules_success(client, mock_provider):
    with patch("ai.get_provider", return_value=mock_provider):
        resp = client.post(
            "/api/ai/rules/suggest",
            data=json.dumps({"description": "Hot AC, morning drive, female 25-44"}),
            content_type="application/json",
        )
    assert resp.status_code == 200
    data = resp.get_json()
    assert "artist_separation_songs" in data
    assert "title_separation_hours" in data
    assert "categories" in data
    mock_provider.suggest_rules.assert_called_once_with("Hot AC, morning drive, female 25-44")
