"""
Data models for music scheduling.
"""
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class Song:
    """A song in the library"""
    song_id: str
    title: str
    artists: List[str]
    primary_artist: str
    length_seconds: int
    intro_seconds: int = 0
    active: bool = True
    rotation: Optional[str] = None
    song_type: Optional[str] = None
    tempo: Optional[str] = None
    tags: List[str] = field(default_factory=list)
    m1_metadata: Optional[Dict[str, Any]] = None


@dataclass
class Pool:
    """A pool of songs defined by criteria"""
    pool_id: str
    name: str
    include: Dict[str, List[str]] = field(default_factory=dict)
    exclude: Dict[str, List[str]] = field(default_factory=dict)
    include_pools: List[str] = field(default_factory=list)
    exclude_pools: List[str] = field(default_factory=list)
    active: bool = True


@dataclass
class SlotFallback:
    """Fallback option for a slot if primary pool is exhausted"""
    pool: Optional[str] = None
    require_song_type: Optional[str] = None


@dataclass
class Slot:
    """A slot in a clock that needs to be filled"""
    slot_id: str
    name: str
    primary_pool: str
    require_song_type: Optional[str] = None
    terminal: bool = False
    fallbacks: List[SlotFallback] = field(default_factory=list)


@dataclass
class Clock:
    """A clock template defining the structure of an hour or half-hour"""
    clock_id: str
    name: str
    duration_minutes: int
    slots: List[Slot]


@dataclass
class PickExplanation:
    """Explanation of why a song was chosen (or not chosen)"""
    slot_name: str
    chosen_song: Optional[Song]
    reason: str
    rejected: List[str] = field(default_factory=list)
    used_fallback: Optional[str] = None
