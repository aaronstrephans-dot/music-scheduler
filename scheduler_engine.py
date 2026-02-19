"""
Scheduler Engine - Core scheduling logic with rule integration.
Clean architecture, UI-friendly, fully tested.
"""
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Callable, Any
from datetime import datetime, timedelta
from pathlib import Path
import json

from models import Song, Pool, Clock, Slot
from rule_framework import RuleEngine, RuleResult
from rule_loader import load_rule_engine_from_config


@dataclass
class SchedulingContext:
    """
    Context passed to rules during scheduling.
    Contains all state needed for rule evaluation.
    """
    current_time: datetime
    daypart: str
    clock_name: str
    slot_name: str
    
    # History
    history: List[Any] = field(default_factory=list)
    recent_songs: List[Song] = field(default_factory=list)
    
    # Hour state
    hour_song_count: int = 0
    hour_category_counts: Dict[str, int] = field(default_factory=dict)
    
    # Day state
    day_song_count: int = 0
    day_category_counts: Dict[str, int] = field(default_factory=dict)
    
    # Flags
    is_auto_scheduling: bool = True
    after_break: bool = False
    
    # Current song being tested
    song: Optional[Song] = None


@dataclass
class SchedulingResult:
    """Result of scheduling a time slot"""
    success: bool
    song: Optional[Song] = None
    slot_name: Optional[str] = None
    time: Optional[datetime] = None
    reason: Optional[str] = None
    rule_score: float = 0.0
    alternatives_tested: int = 0


@dataclass
class ScheduleProgress:
    """Progress update for UI"""
    current_time: datetime
    total_slots: int
    filled_slots: int
    current_slot: str
    message: str
    percentage: float


class SchedulerEngine:
    """
    Main scheduling engine.
    Integrates pools, strategies, and rules into cohesive scheduler.
    """
    
    def __init__(
        self,
        songs: Dict[str, Song],
        pools: Dict[str, Pool],
        rule_engine: Optional[RuleEngine] = None,
        strategy: Optional[Any] = None,
        progress_callback: Optional[Callable[[ScheduleProgress], None]] = None
    ):
        """
        Initialize scheduler engine.
        
        Args:
            songs: Dictionary of all songs {song_id: Song}
            pools: Dictionary of all pools {pool_id: Pool}
            rule_engine: Optional rule engine (loads default if None)
            strategy: Optional strategy configuration
            progress_callback: Optional callback for progress updates
        """
        self.songs = songs
        self.pools = pools
        self.rule_engine = rule_engine or RuleEngine()
        self.strategy = strategy
        self.progress_callback = progress_callback
        
        # State tracking
        self.history: List[Any] = []
        self.used_songs_today: set = set()  # Track songs used today
        
        # Statistics
        self.stats = {
            'total_slots': 0,
            'filled_slots': 0,
            'rule_violations': 0,
            'pool_exhaustions': 0,
            'category_counts_hour': {},
            'category_counts_day': {}
        }
    
    def get_pool_candidates(
        self,
        pool_id: str,
        exclude_songs: Optional[List[str]] = None
    ) -> List[Song]:
        """
        Get candidate songs from a pool.
        
        Args:
            pool_id: Pool to get candidates from
            exclude_songs: Song IDs to exclude
        
        Returns:
            List of candidate songs
        """
        pool = self.pools.get(pool_id)
        if not pool:
            return []
        
        exclude_set = set(exclude_songs or [])
        # Also exclude songs already used today
        exclude_set.update(self.used_songs_today)
        
        candidates = []
        
        # Get songs matching pool criteria
        for song_id, song in self.songs.items():
            if song_id in exclude_set:
                continue
            
            if not song.active:
                continue
            
            # Check pool inclusion criteria
            if pool.include:
                matches = True
                
                for field, values in pool.include.items():
                    song_val = getattr(song, field, None)
                    
                    if isinstance(song_val, list):
                        # Field is a list (like tags, artists)
                        if not any(v in song_val for v in values):
                            matches = False
                            break
                    else:
                        # Field is single value (like rotation)
                        if song_val not in values:
                            matches = False
                            break
                
                if not matches:
                    continue
            
            # Check pool exclusion criteria
            if pool.exclude:
                excluded = False
                
                for field, values in pool.exclude.items():
                    song_val = getattr(song, field, None)
                    
                    if isinstance(song_val, list):
                        if any(v in song_val for v in values):
                            excluded = True
                            break
                    else:
                        if song_val in values:
                            excluded = True
                            break
                
                if excluded:
                    continue
            
            candidates.append(song)
        
        return candidates
    
    def pick_best_song(
        self,
        candidates: List[Song],
        context: SchedulingContext
    ) -> Optional[Song]:
        """
        Pick best song from candidates using rule engine.
        
        Args:
            candidates: List of candidate songs
            context: Scheduling context
        
        Returns:
            Best song or None if all violate unbreakable rules
        """
        if not candidates:
            return None
        
        # Apply strategy quotas if available
        if self.strategy:
            # Filter by hour quotas
            filtered_candidates = []
            for song in candidates:
                if hasattr(song, 'rotation') and song.rotation:
                    current_count = self.stats['category_counts_hour'].get(song.rotation, 0)
                    if self.strategy.check_hour_quota(song.rotation, current_count):
                        filtered_candidates.append(song)
                else:
                    filtered_candidates.append(song)
            
            if filtered_candidates:
                candidates = filtered_candidates
        
        # Test each candidate against rules
        scored_candidates = []
        
        for song in candidates:
            # Update context with current song
            test_context = {
                'current_time': context.current_time,
                'daypart': context.daypart,
                'clock_name': context.clock_name,
                'slot_name': context.slot_name,
                'history': context.history,
                'recent_songs': context.recent_songs,
                'hour_song_count': context.hour_song_count,
                'hour_category_counts': context.hour_category_counts,
                'day_song_count': context.day_song_count,
                'day_category_counts': context.day_category_counts,
                'is_auto_scheduling': context.is_auto_scheduling,
                'after_break': context.after_break,
                'song': song
            }
            
            # Test against rules
            result = self.rule_engine.test_song(song, test_context)
            
            if result['passed']:
                scored_candidates.append((song, result['score']))
        
        if not scored_candidates:
            return None  # All violated unbreakable rules
        
        # Return highest scoring song
        best = max(scored_candidates, key=lambda x: x[1])
        return best[0]
    
    def schedule_slot(
        self,
        slot: Slot,
        time: datetime,
        context: SchedulingContext
    ) -> SchedulingResult:
        """
        Schedule a single slot.
        
        Args:
            slot: Slot to fill
            time: Time to schedule at
            context: Scheduling context
        
        Returns:
            SchedulingResult
        """
        # Try primary pool first
        candidates = self.get_pool_candidates(slot.primary_pool)
        
        # Filter by song type if required
        if slot.require_song_type:
            candidates = [
                s for s in candidates
                if s.song_type == slot.require_song_type
            ]
        
        # Pick best song
        best_song = self.pick_best_song(candidates, context)
        
        # Try fallbacks if primary failed
        if not best_song and slot.fallbacks:
            for fallback in slot.fallbacks:
                if not fallback.pool:
                    continue
                
                candidates = self.get_pool_candidates(fallback.pool)
                
                if fallback.require_song_type:
                    candidates = [
                        s for s in candidates
                        if s.song_type == fallback.require_song_type
                    ]
                
                best_song = self.pick_best_song(candidates, context)
                
                if best_song:
                    break
        
        if best_song:
            return SchedulingResult(
                success=True,
                song=best_song,
                slot_name=slot.name,
                time=time,
                reason="Scheduled successfully"
            )
        else:
            return SchedulingResult(
                success=False,
                slot_name=slot.name,
                time=time,
                reason="No valid songs available (pool exhaustion or rule violations)"
            )
    
    def schedule_hour(
        self,
        clock: Clock,
        start_time: datetime,
        daypart: str
    ) -> List[SchedulingResult]:
        """
        Schedule a single hour using a clock.
        
        Args:
            clock: Clock template to use
            start_time: Start time of hour
            daypart: Daypart name
        
        Returns:
            List of SchedulingResults
        """
        results = []
        current_time = start_time
        
        # Reset hour counts at start of new hour
        if start_time.minute == 0:
            self.stats['category_counts_hour'] = {}
        
        # Initialize hour context
        hour_category_counts = {}
        hour_song_count = 0
        
        for slot in clock.slots:
            # Build context
            context = SchedulingContext(
                current_time=current_time,
                daypart=daypart,
                clock_name=clock.name,
                slot_name=slot.name,
                history=self.history.copy(),
                recent_songs=self.history[-10:] if self.history else [],
                hour_song_count=hour_song_count,
                hour_category_counts=hour_category_counts.copy(),
                day_song_count=self.stats['filled_slots'],
                day_category_counts={},  # Would need to track this
                is_auto_scheduling=True,
                after_break=False  # Would need to detect this from clock
            )
            
            # Schedule slot
            result = self.schedule_slot(slot, current_time, context)
            results.append(result)
            
            # Update state if successful
            if result.success and result.song:
                # Add to history
                song_with_time = result.song
                song_with_time.datetime = current_time
                song_with_time.daypart = daypart
                self.history.append(song_with_time)
                
                # Track song used today
                self.used_songs_today.add(result.song.song_id)
                
                # Update counts
                hour_song_count += 1
                if result.song.rotation:
                    hour_category_counts[result.song.rotation] = \
                        hour_category_counts.get(result.song.rotation, 0) + 1
                    
                    # Update global hour counts
                    self.stats['category_counts_hour'][result.song.rotation] = \
                        self.stats['category_counts_hour'].get(result.song.rotation, 0) + 1
                    
                    # Update day counts
                    self.stats['category_counts_day'][result.song.rotation] = \
                        self.stats['category_counts_day'].get(result.song.rotation, 0) + 1
                
                # Advance time
                current_time += timedelta(seconds=result.song.length_seconds)
            
            # Progress update
            if self.progress_callback:
                self.stats['total_slots'] += 1
                if result.success:
                    self.stats['filled_slots'] += 1
                
                progress = ScheduleProgress(
                    current_time=current_time,
                    total_slots=self.stats['total_slots'],
                    filled_slots=self.stats['filled_slots'],
                    current_slot=slot.name,
                    message=f"Scheduling {daypart} - {slot.name}",
                    percentage=(self.stats['filled_slots'] / self.stats['total_slots'] * 100)
                        if self.stats['total_slots'] > 0 else 0
                )
                self.progress_callback(progress)
        
        return results
    
    def clear_history(self):
        """Clear scheduling history"""
        self.history.clear()
        self.used_songs_today.clear()
        self.stats = {
            'total_slots': 0,
            'filled_slots': 0,
            'rule_violations': 0,
            'pool_exhaustions': 0,
            'category_counts_hour': {},
            'category_counts_day': {}
        }
    
    def start_new_day(self):
        """Start a new day - reset day-specific tracking"""
        self.used_songs_today.clear()
        self.stats['category_counts_day'] = {}
    
    def save_history(self, filepath: Path):
        """Save scheduling history to file"""
        import json
        
        history_data = []
        for entry in self.history:
            history_data.append({
                'song_id': entry.song_id,
                'title': entry.title,
                'artist': entry.primary_artist,
                'datetime': entry.datetime.isoformat() if hasattr(entry, 'datetime') else None,
                'daypart': getattr(entry, 'daypart', None)
            })
        
        with open(filepath, 'w') as f:
            json.dump({
                'history': history_data,
                'stats': self.stats
            }, f, indent=2)
    
    def load_history(self, filepath: Path):
        """Load scheduling history from file"""
        import json
        
        with open(filepath, 'r') as f:
            data = json.load(f)
        
        # Rebuild history
        self.history.clear()
        for entry_data in data.get('history', []):
            song_id = entry_data['song_id']
            if song_id in self.songs:
                song = self.songs[song_id]
                if entry_data.get('datetime'):
                    from datetime import datetime
                    song.datetime = datetime.fromisoformat(entry_data['datetime'])
                if entry_data.get('daypart'):
                    song.daypart = entry_data['daypart']
                self.history.append(song)
        
        # Restore stats
        if 'stats' in data:
            self.stats.update(data['stats'])
