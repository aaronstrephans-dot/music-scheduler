"""
History tracking system for the music scheduler.
Tracks when songs and artists were last played for time-based separation rules.
"""
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, Optional
import json


@dataclass
class PlayRecord:
    """Record of when something (song or artist) was played"""
    item_id: str
    played_at: datetime
    context: str = ""  # e.g., "WeekdayHalfHour-2024-01-15-10:00"
    
    def to_dict(self):
        return {
            "item_id": self.item_id,
            "played_at": self.played_at.isoformat(),
            "context": self.context
        }
    
    @classmethod
    def from_dict(cls, data):
        return cls(
            item_id=data["item_id"],
            played_at=datetime.fromisoformat(data["played_at"]),
            context=data.get("context", "")
        )


@dataclass
class HistoryTracker:
    """
    Tracks play history for songs and artists.
    Persists to JSON file for cross-run history.
    """
    song_plays: Dict[str, PlayRecord] = field(default_factory=dict)
    artist_plays: Dict[str, PlayRecord] = field(default_factory=dict)
    
    def record_play(self, song_id: str, artist: str, played_at: datetime, context: str = ""):
        """Record that a song was played"""
        self.song_plays[song_id] = PlayRecord(song_id, played_at, context)
        self.artist_plays[artist] = PlayRecord(artist, played_at, context)
    
    def last_played_song(self, song_id: str) -> Optional[datetime]:
        """When was this song last played?"""
        record = self.song_plays.get(song_id)
        return record.played_at if record else None
    
    def last_played_artist(self, artist: str) -> Optional[datetime]:
        """When was this artist last played?"""
        record = self.artist_plays.get(artist)
        return record.played_at if record else None
    
    def minutes_since_song(self, song_id: str, current_time: datetime) -> Optional[float]:
        """How many minutes since this song last played?"""
        last = self.last_played_song(song_id)
        if last is None:
            return None
        delta = current_time - last
        return delta.total_seconds() / 60
    
    def minutes_since_artist(self, artist: str, current_time: datetime) -> Optional[float]:
        """How many minutes since this artist last played?"""
        last = self.last_played_artist(artist)
        if last is None:
            return None
        delta = current_time - last
        return delta.total_seconds() / 60
    
    def save(self, filepath: Path):
        """Save history to JSON file"""
        data = {
            "song_plays": {k: v.to_dict() for k, v in self.song_plays.items()},
            "artist_plays": {k: v.to_dict() for k, v in self.artist_plays.items()}
        }
        filepath.parent.mkdir(parents=True, exist_ok=True)
        with open(filepath, 'w') as f:
            json.dump(data, f, indent=2)
    
    @classmethod
    def load(cls, filepath: Path) -> 'HistoryTracker':
        """Load history from JSON file"""
        if not filepath.exists():
            return cls()
        
        with open(filepath, 'r') as f:
            data = json.load(f)
        
        song_plays = {k: PlayRecord.from_dict(v) for k, v in data.get("song_plays", {}).items()}
        artist_plays = {k: PlayRecord.from_dict(v) for k, v in data.get("artist_plays", {}).items()}
        
        return cls(song_plays=song_plays, artist_plays=artist_plays)
    
    def clear_old_history(self, cutoff_days: int = 30):
        """Remove history older than cutoff_days to keep file manageable"""
        cutoff = datetime.now() - timedelta(days=cutoff_days)
        
        self.song_plays = {
            k: v for k, v in self.song_plays.items()
            if v.played_at > cutoff
        }
        
        self.artist_plays = {
            k: v for k, v in self.artist_plays.items()
            if v.played_at > cutoff
        }


@dataclass
class SeparationRules:
    """
    Configurable separation rules.
    All times in minutes.
    """
    # Artist separation across time
    artist_separation_minutes: int = 90
    
    # Song rest period (minimum time before replaying same song)
    song_rest_minutes: int = 1440  # 24 hours = 1440 minutes
    
    # Block-level rules (already implemented, kept for reference)
    disallow_duplicate_artist_within_block: bool = True
    disallow_duplicate_song_within_block: bool = True


def check_time_based_violations(
    song_id: str,
    artist: str,
    current_time: datetime,
    history: HistoryTracker,
    rules: SeparationRules
) -> tuple[bool, list[str]]:
    """
    Check if playing this song/artist now would violate time-based rules.
    
    Returns:
        (is_valid, list_of_violations)
    """
    violations = []
    
    # Check artist separation
    mins_since_artist = history.minutes_since_artist(artist, current_time)
    if mins_since_artist is not None:
        if mins_since_artist < rules.artist_separation_minutes:
            violations.append(
                f"Artist '{artist}' played {mins_since_artist:.0f} min ago "
                f"(need {rules.artist_separation_minutes} min)"
            )
    
    # Check song rest period
    mins_since_song = history.minutes_since_song(song_id, current_time)
    if mins_since_song is not None:
        if mins_since_song < rules.song_rest_minutes:
            violations.append(
                f"Song '{song_id}' played {mins_since_song:.0f} min ago "
                f"(need {rules.song_rest_minutes} min)"
            )
    
    return (len(violations) == 0, violations)
