"""
Pattern and rotation rules - Disallowed patterns, same day repeat, 
category balance, daypart distribution.
"""
from typing import List, Optional, Dict
from datetime import datetime, timedelta
from rule_framework import BaseRule, RuleResult, RuleType, RulePriority


class DisallowedPatternRule(BaseRule):
    """
    MusicMaster disallowed patterns - prevent specific sequences.
    Example: "1??1" = no Slow-X-X-Slow
    Example: "3333" = no four Medium songs in a row
    """
    
    def __init__(
        self,
        field_name: str,  # Which field to check (tempo, mood, energy, sound_code)
        patterns: List[str],  # List of disallowed patterns
        **kwargs
    ):
        super().__init__(
            name=f"Disallowed Pattern ({field_name})",
            priority=RulePriority.HIGH,
            **kwargs
        )
        self.field_name = field_name
        self.patterns = patterns
    
    def get_field_value(self, song) -> Optional[str]:
        """Get field value from song"""
        if hasattr(song, self.field_name):
            val = getattr(song, self.field_name)
            return str(val) if val is not None else None
        return None
    
    def matches_pattern(self, sequence: List[str], pattern: str) -> bool:
        """
        Check if sequence matches disallowed pattern.
        ? = wildcard (any value)
        """
        if len(sequence) != len(pattern):
            return False
        
        for seq_val, pat_char in zip(sequence, pattern):
            if pat_char != '?' and seq_val != pat_char:
                return False
        
        return True
    
    def test(self, song, context) -> RuleResult:
        """Test for disallowed patterns"""
        current_value = self.get_field_value(song)
        if current_value is None:
            return RuleResult(True, 1.0)
        
        history = context.get('recent_songs', [])
        
        # Build sequence including current song
        max_pattern_len = max(len(p) for p in self.patterns)
        sequence = []
        
        for hist_song in reversed(history[-(max_pattern_len-1):]):
            val = self.get_field_value(hist_song)
            if val:
                sequence.append(val)
        
        sequence.append(current_value)
        
        # Check each pattern
        for pattern in self.patterns:
            pattern_len = len(pattern)
            
            if len(sequence) >= pattern_len:
                test_sequence = sequence[-pattern_len:]
                
                if self.matches_pattern(test_sequence, pattern):
                    return RuleResult(
                        False,
                        0.2,
                        f"Pattern violation: {''.join(test_sequence)} matches disallowed pattern '{pattern}'"
                    )
        
        return RuleResult(True, 1.0)


class SameDayRepeatRule(BaseRule):
    """
    Same day repeat - "No repeat workday" positioning.
    Prevents song from playing twice in same day.
    """
    
    def __init__(self, **kwargs):
        super().__init__(
            name="Same Day Repeat",
            priority=RulePriority.HIGH,
            **kwargs
        )
    
    def test(self, song, context) -> RuleResult:
        """Test for same day repeat"""
        if not hasattr(song, 'song_id'):
            return RuleResult(True, 1.0)
        
        current_time = context.get('current_time', datetime.now())
        current_date = current_time.date()
        
        history = context.get('history', [])
        
        for hist_entry in history:
            hist_time = getattr(hist_entry, 'datetime', None)
            if not hist_time:
                continue
            
            # Same date?
            if hist_time.date() == current_date:
                if getattr(hist_entry, 'song_id', '') == song.song_id:
                    return RuleResult(
                        False,
                        0.1,
                        f"Song already played today at {hist_time.strftime('%H:%M')}"
                    )
        
        return RuleResult(True, 1.0)


class CategoryBalanceRule(BaseRule):
    """
    Category balance - ensure proper distribution of categories per hour/day.
    Example: "15% Hot Current, 20% Medium Current, 65% Gold"
    """
    
    def __init__(
        self,
        target_percentages: Dict[str, float],  # {category: target_percent}
        tolerance: float = 5.0,  # Percentage points tolerance
        scope: str = "hour",  # "hour" or "day"
        **kwargs
    ):
        super().__init__(
            name="Category Balance",
            priority=RulePriority.MEDIUM,
            rule_type=RuleType.BREAKABLE,
            **kwargs
        )
        self.target_percentages = target_percentages
        self.tolerance = tolerance
        self.scope = scope
    
    def test(self, song, context) -> RuleResult:
        """Test category balance"""
        if not hasattr(song, 'rotation'):
            return RuleResult(True, 1.0)
        
        category = song.rotation
        
        # Get category counts in scope
        if self.scope == "hour":
            category_counts = context.get('hour_category_counts', {})
            total_songs = context.get('hour_song_count', 0)
        else:  # day
            category_counts = context.get('day_category_counts', {})
            total_songs = context.get('day_song_count', 0)
        
        if total_songs == 0:
            return RuleResult(True, 1.0)
        
        # Calculate current percentage if we add this song
        current_count = category_counts.get(category, 0)
        new_count = current_count + 1
        new_total = total_songs + 1
        new_percentage = (new_count / new_total) * 100
        
        # Check against target
        target = self.target_percentages.get(category)
        if target is None:
            return RuleResult(True, 1.0)  # No target for this category
        
        difference = abs(new_percentage - target)
        
        if difference > self.tolerance:
            # Would exceed balance
            score = max(0.0, 1.0 - (difference - self.tolerance) / 20.0)
            return RuleResult(
                False,
                score,
                f"{category} would be {new_percentage:.1f}% (target {target}% ±{self.tolerance}%)"
            )
        
        return RuleResult(True, 1.0)


class DaypartDistributionRule(BaseRule):
    """
    Daypart distribution - ensure songs rotate through all dayparts evenly.
    Prevents "morning only" or "afternoon only" stacking.
    """
    
    def __init__(
        self,
        dayparts: List[str],
        lookback_days: int = 7,
        max_percentage_in_one: float = 40.0,  # Max % of plays in single daypart
        **kwargs
    ):
        super().__init__(
            name="Daypart Distribution",
            priority=RulePriority.LOW,
            rule_type=RuleType.BREAKABLE,
            **kwargs
        )
        self.dayparts = dayparts
        self.lookback_days = lookback_days
        self.max_percentage_in_one = max_percentage_in_one
    
    def test(self, song, context) -> RuleResult:
        """Test daypart distribution"""
        if not hasattr(song, 'song_id'):
            return RuleResult(True, 1.0)
        
        current_daypart = context.get('daypart')
        if not current_daypart:
            return RuleResult(True, 1.0)
        
        current_time = context.get('current_time', datetime.now())
        cutoff_time = current_time - timedelta(days=self.lookback_days)
        
        history = context.get('history', [])
        
        # Count plays of this song by daypart
        daypart_counts = {dp: 0 for dp in self.dayparts}
        total_plays = 0
        
        for hist_entry in history:
            if getattr(hist_entry, 'song_id', '') != song.song_id:
                continue
            
            hist_time = getattr(hist_entry, 'datetime', None)
            if not hist_time or hist_time < cutoff_time:
                continue
            
            hist_daypart = getattr(hist_entry, 'daypart', None)
            if hist_daypart in daypart_counts:
                daypart_counts[hist_daypart] += 1
                total_plays += 1
        
        if total_plays == 0:
            return RuleResult(True, 1.0)
        
        # Check if adding to current daypart would exceed max
        new_count = daypart_counts[current_daypart] + 1
        new_total = total_plays + 1
        percentage = (new_count / new_total) * 100
        
        if percentage > self.max_percentage_in_one:
            score = max(0.0, 1.0 - (percentage - self.max_percentage_in_one) / 30.0)
            return RuleResult(
                False,
                score,
                f"Song overplayed in {current_daypart}: {percentage:.1f}% of plays (max {self.max_percentage_in_one}%)"
            )
        
        return RuleResult(True, 1.0)


class HourRestrictionRule(BaseRule):
    """
    Hour restriction (dayparting) - prevent songs from scheduling in certain hours.
    Example: Christmas songs only in December, specialty tracks only in specific shows.
    """
    
    def __init__(
        self,
        allowed_hours: Optional[List[int]] = None,  # List of allowed hours (0-23)
        blocked_hours: Optional[List[int]] = None,  # List of blocked hours
        allowed_days: Optional[List[int]] = None,   # List of allowed days (0=Mon, 6=Sun)
        **kwargs
    ):
        super().__init__(
            name="Hour Restriction",
            priority=RulePriority.CRITICAL,
            **kwargs
        )
        self.allowed_hours = allowed_hours
        self.blocked_hours = blocked_hours or []
        self.allowed_days = allowed_days
    
    def test(self, song, context) -> RuleResult:
        """Test hour restrictions"""
        current_time = context.get('current_time', datetime.now())
        current_hour = current_time.hour
        current_day = current_time.weekday()
        
        # Check blocked hours
        if current_hour in self.blocked_hours:
            return RuleResult(
                False,
                0.0,
                f"Song blocked from hour {current_hour}:00"
            )
        
        # Check allowed hours
        if self.allowed_hours and current_hour not in self.allowed_hours:
            return RuleResult(
                False,
                0.0,
                f"Song only allowed in hours {self.allowed_hours}"
            )
        
        # Check allowed days
        if self.allowed_days and current_day not in self.allowed_days:
            days_names = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']
            allowed_names = [days_names[d] for d in self.allowed_days]
            return RuleResult(
                False,
                0.0,
                f"Song only allowed on {', '.join(allowed_names)}"
            )
        
        return RuleResult(True, 1.0)
