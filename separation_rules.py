"""
Separation rules - Artist, keyword, title, album, product, position-based.
Industry-standard separation logic from Music1, MusicMaster, PowerGold.
"""
from datetime import datetime, timedelta
from typing import Optional, Dict, List
from rule_framework import BaseRule, RuleResult, RuleType, RulePriority


class ArtistSeparationRule(BaseRule):
    """
    Artist separation - time-based spacing between same artist.
    Supports per-artist overrides (MusicMaster feature).
    """
    
    def __init__(
        self,
        separation_minutes: int = 90,
        per_artist_overrides: Optional[Dict[str, int]] = None,
        **kwargs
    ):
        super().__init__(
            name="Artist Separation",
            priority=RulePriority.CRITICAL,
            **kwargs
        )
        self.separation_minutes = separation_minutes
        self.per_artist_overrides = per_artist_overrides or {}
    
    def get_separation_for_artist(self, artist: str) -> int:
        """Get separation time for specific artist"""
        return self.per_artist_overrides.get(artist, self.separation_minutes)
    
    def test(self, song, context) -> RuleResult:
        """Test artist separation"""
        if not hasattr(song, 'primary_artist'):
            return RuleResult(True, 1.0)
        
        artist = song.primary_artist
        separation_mins = self.get_separation_for_artist(artist)
        
        history = context.get('history', [])
        current_time = context.get('current_time', datetime.now())
        
        # Check history for same artist
        for hist_entry in reversed(history):
            if not hasattr(hist_entry, 'primary_artist'):
                continue
            
            if hist_entry.primary_artist == artist:
                time_diff = (current_time - hist_entry.datetime).total_seconds() / 60
                
                if time_diff < separation_mins:
                    minutes_short = separation_mins - time_diff
                    return RuleResult(
                        False,
                        time_diff / separation_mins,  # Partial score
                        f"Artist {artist} played {int(time_diff)}min ago (need {separation_mins}min)"
                    )
                break
        
        return RuleResult(True, 1.0)


class ArtistKeywordSeparationRule(BaseRule):
    """
    MusicMaster-style artist keyword separation.
    Separates by individual keywords (handles collaborations).
    Example: "Tom Petty & The Heartbreakers" has keywords: ["Tom Petty", "Heartbreakers"]
    """
    
    def __init__(
        self,
        separation_minutes: int = 90,
        per_keyword_overrides: Optional[Dict[str, int]] = None,
        **kwargs
    ):
        super().__init__(
            name="Artist Keyword Separation",
            priority=RulePriority.CRITICAL,
            **kwargs
        )
        self.separation_minutes = separation_minutes
        self.per_keyword_overrides = per_keyword_overrides or {}
    
    def get_keywords(self, song) -> List[str]:
        """Extract artist keywords from song"""
        if hasattr(song, 'artist_keywords'):
            return song.artist_keywords
        
        # Fallback: use artists list
        if hasattr(song, 'artists'):
            return song.artists
        
        # Last resort: split primary artist
        if hasattr(song, 'primary_artist'):
            return [song.primary_artist]
        
        return []
    
    def test(self, song, context) -> RuleResult:
        """Test keyword separation"""
        keywords = self.get_keywords(song)
        if not keywords:
            return RuleResult(True, 1.0)
        
        history = context.get('history', [])
        current_time = context.get('current_time', datetime.now())
        
        # Check each keyword
        for keyword in keywords:
            separation_mins = self.per_keyword_overrides.get(keyword, self.separation_minutes)
            
            for hist_entry in reversed(history):
                hist_keywords = self.get_keywords(hist_entry)
                
                if keyword in hist_keywords:
                    time_diff = (current_time - hist_entry.datetime).total_seconds() / 60
                    
                    if time_diff < separation_mins:
                        return RuleResult(
                            False,
                            time_diff / separation_mins,
                            f"Keyword '{keyword}' played {int(time_diff)}min ago (need {separation_mins}min)"
                        )
                    break
        
        return RuleResult(True, 1.0)


class TitleSeparationRule(BaseRule):
    """
    Title separation - separate different versions of same song.
    Example: "White Christmas" (Bing Crosby) vs "White Christmas" (Elvis)
    """
    
    def __init__(self, separation_minutes: int = 240, **kwargs):
        super().__init__(
            name="Title Separation",
            priority=RulePriority.HIGH,
            **kwargs
        )
        self.separation_minutes = separation_minutes
    
    def normalize_title(self, title: str) -> str:
        """Normalize title for comparison"""
        # Remove common suffixes
        normalized = title.lower()
        for suffix in [' - live', ' (live)', ' - acoustic', ' (acoustic)', ' - remix', ' (remix)']:
            normalized = normalized.replace(suffix, '')
        return normalized.strip()
    
    def test(self, song, context) -> RuleResult:
        """Test title separation"""
        if not hasattr(song, 'title'):
            return RuleResult(True, 1.0)
        
        current_title = self.normalize_title(song.title)
        history = context.get('history', [])
        current_time = context.get('current_time', datetime.now())
        
        for hist_entry in reversed(history):
            if not hasattr(hist_entry, 'title'):
                continue
            
            hist_title = self.normalize_title(hist_entry.title)
            
            if current_title == hist_title:
                # Same title - check if different category (across-category rule)
                current_cat = getattr(song, 'rotation', '')
                hist_cat = getattr(hist_entry, 'rotation', '')
                
                if current_cat != hist_cat:
                    time_diff = (current_time - hist_entry.datetime).total_seconds() / 60
                    
                    if time_diff < self.separation_minutes:
                        return RuleResult(
                            False,
                            time_diff / self.separation_minutes,
                            f"Title '{song.title}' played {int(time_diff)}min ago in {hist_cat}"
                        )
                break
        
        return RuleResult(True, 1.0)


class PreviousDaySeparationRule(BaseRule):
    """
    Prevent same artist/song from scheduling at similar time previous day.
    Music1 optional feature.
    """
    
    def __init__(
        self,
        window_minutes: int = 30,  # How close to same time = violation
        apply_to: str = "artist",  # "artist" or "song"
        **kwargs
    ):
        super().__init__(
            name="Previous Day Separation",
            priority=RulePriority.MEDIUM,
            **kwargs
        )
        self.window_minutes = window_minutes
        self.apply_to = apply_to
    
    def test(self, song, context) -> RuleResult:
        """Test previous day separation"""
        current_time = context.get('current_time', datetime.now())
        history = context.get('history', [])
        
        # Look for same time yesterday
        yesterday = current_time - timedelta(days=1)
        window_start = yesterday - timedelta(minutes=self.window_minutes)
        window_end = yesterday + timedelta(minutes=self.window_minutes)
        
        for hist_entry in history:
            hist_time = getattr(hist_entry, 'datetime', None)
            if not hist_time:
                continue
            
            if window_start <= hist_time <= window_end:
                # Same time window yesterday
                if self.apply_to == "artist":
                    if getattr(song, 'primary_artist', '') == getattr(hist_entry, 'primary_artist', ''):
                        return RuleResult(
                            False,
                            0.5,
                            f"Artist played at similar time yesterday ({hist_time.strftime('%H:%M')})"
                        )
                elif self.apply_to == "song":
                    if getattr(song, 'song_id', '') == getattr(hist_entry, 'song_id', ''):
                        return RuleResult(
                            False,
                            0.3,
                            f"Song played at similar time yesterday ({hist_time.strftime('%H:%M')})"
                        )
        
        return RuleResult(True, 1.0)


class HourOpenerSeparationRule(BaseRule):
    """
    MusicMaster feature - prevent song/artist from repeating as hour opener.
    "Don't want to intro the same artist/song at top of hour twice in a shift"
    """
    
    def __init__(
        self,
        separation_minutes: int = 180,
        apply_to: str = "both",  # "song", "artist", or "both"
        **kwargs
    ):
        super().__init__(
            name="Hour Opener Separation",
            priority=RulePriority.MEDIUM,
            **kwargs
        )
        self.separation_minutes = separation_minutes
        self.apply_to = apply_to
    
    def is_hour_opener(self, time: datetime) -> bool:
        """Check if this is a hour opener position"""
        return time.minute < 2  # First 2 minutes of hour
    
    def test(self, song, context) -> RuleResult:
        """Test hour opener separation"""
        current_time = context.get('current_time', datetime.now())
        
        # Only apply if current position is hour opener
        if not self.is_hour_opener(current_time):
            return RuleResult(True, 1.0)
        
        history = context.get('history', [])
        cutoff_time = current_time - timedelta(minutes=self.separation_minutes)
        
        for hist_entry in history:
            hist_time = getattr(hist_entry, 'datetime', None)
            if not hist_time or hist_time < cutoff_time:
                continue
            
            # Was this a hour opener?
            if self.is_hour_opener(hist_time):
                match = False
                
                if self.apply_to in ["song", "both"]:
                    if getattr(song, 'song_id', '') == getattr(hist_entry, 'song_id', ''):
                        match = True
                
                if self.apply_to in ["artist", "both"]:
                    if getattr(song, 'primary_artist', '') == getattr(hist_entry, 'primary_artist', ''):
                        match = True
                
                if match:
                    return RuleResult(
                        False,
                        0.5,
                        f"Already opened hour with this {self.apply_to} at {hist_time.strftime('%H:%M')}"
                    )
        
        return RuleResult(True, 1.0)


class SweepOpenerSeparationRule(BaseRule):
    """
    MusicMaster feature - prevent song/artist from repeating after commercial breaks.
    "Announcer doesn't want to talk about Pink Floyd after break twice in shift"
    """
    
    def __init__(
        self,
        separation_minutes: int = 180,
        apply_to: str = "both",  # "song", "artist", or "both"
        **kwargs
    ):
        super().__init__(
            name="Sweep Opener Separation",
            priority=RulePriority.MEDIUM,
            **kwargs
        )
        self.separation_minutes = separation_minutes
        self.apply_to = apply_to
    
    def test(self, song, context) -> RuleResult:
        """Test sweep opener separation"""
        # Check if current position is after a sweep/break
        is_after_break = context.get('after_break', False)
        
        if not is_after_break:
            return RuleResult(True, 1.0)
        
        current_time = context.get('current_time', datetime.now())
        history = context.get('history', [])
        cutoff_time = current_time - timedelta(minutes=self.separation_minutes)
        
        for hist_entry in history:
            hist_time = getattr(hist_entry, 'datetime', None)
            if not hist_time or hist_time < cutoff_time:
                continue
            
            # Was this also after a break?
            hist_after_break = getattr(hist_entry, 'after_break', False)
            if hist_after_break:
                match = False
                
                if self.apply_to in ["song", "both"]:
                    if getattr(song, 'song_id', '') == getattr(hist_entry, 'song_id', ''):
                        match = True
                
                if self.apply_to in ["artist", "both"]:
                    if getattr(song, 'primary_artist', '') == getattr(hist_entry, 'primary_artist', ''):
                        match = True
                
                if match:
                    return RuleResult(
                        False,
                        0.5,
                        f"Already used this {self.apply_to} after break at {hist_time.strftime('%H:%M')}"
                    )
        
        return RuleResult(True, 1.0)
