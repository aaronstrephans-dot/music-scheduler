"""
Constraint framework for music scheduling.
Supports caps, minimums, quotas, patterns, and custom constraints.
"""
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set
from abc import ABC, abstractmethod
from datetime import datetime


@dataclass
class ConstraintViolation:
    """Record of a constraint violation"""
    constraint_name: str
    reason: str
    severity: str = "error"  # "error" or "warning"


@dataclass
class SchedulingContext:
    """
    Context passed to constraints for evaluation.
    Tracks state across a scheduling run.
    """
    # Current position in schedule
    current_hour: int = 0
    current_block: int = 0
    current_slot: int = 0
    
    # Counters for current hour
    hour_category_counts: Dict[str, int] = field(default_factory=dict)
    hour_song_type_counts: Dict[str, int] = field(default_factory=dict)
    hour_rotation_counts: Dict[str, int] = field(default_factory=dict)
    hour_songs_played: List[str] = field(default_factory=list)
    hour_artists_played: Set[str] = field(default_factory=set)
    
    # Counters for current block (half-hour)
    block_category_counts: Dict[str, int] = field(default_factory=dict)
    block_song_type_counts: Dict[str, int] = field(default_factory=dict)
    block_songs_played: List[str] = field(default_factory=list)
    block_artists_played: Set[str] = field(default_factory=set)
    
    # Counters for entire day
    day_category_counts: Dict[str, int] = field(default_factory=dict)
    day_song_type_counts: Dict[str, int] = field(default_factory=dict)
    day_songs_played: List[str] = field(default_factory=list)
    
    # Metadata
    start_time: Optional[datetime] = None
    
    def increment_category(self, category: str, scope: str = "all"):
        """Increment category counter at specified scope"""
        if scope in ["hour", "all"]:
            self.hour_category_counts[category] = self.hour_category_counts.get(category, 0) + 1
        if scope in ["block", "all"]:
            self.block_category_counts[category] = self.block_category_counts.get(category, 0) + 1
        if scope in ["day", "all"]:
            self.day_category_counts[category] = self.day_category_counts.get(category, 0) + 1
    
    def increment_song_type(self, song_type: str, scope: str = "all"):
        """Increment song type counter at specified scope"""
        if scope in ["hour", "all"]:
            self.hour_song_type_counts[song_type] = self.hour_song_type_counts.get(song_type, 0) + 1
        if scope in ["block", "all"]:
            self.block_song_type_counts[song_type] = self.block_song_type_counts.get(song_type, 0) + 1
        if scope in ["day", "all"]:
            self.day_song_type_counts[song_type] = self.day_song_type_counts.get(song_type, 0) + 1
    
    def record_play(self, song_id: str, artist: str, category: str, song_type: Optional[str]):
        """Record that a song was played"""
        # Hour tracking
        self.hour_songs_played.append(song_id)
        self.hour_artists_played.add(artist)
        
        # Block tracking
        self.block_songs_played.append(song_id)
        self.block_artists_played.add(artist)
        
        # Day tracking
        self.day_songs_played.append(song_id)
        
        # Increment counters
        if category:
            self.increment_category(category)
        if song_type:
            self.increment_song_type(song_type)
    
    def reset_block(self):
        """Reset block-level counters (called at start of new block)"""
        self.block_category_counts.clear()
        self.block_song_type_counts.clear()
        self.block_songs_played.clear()
        self.block_artists_played.clear()
        self.current_block += 1
        self.current_slot = 0
    
    def reset_hour(self):
        """Reset hour-level counters (called at start of new hour)"""
        self.hour_category_counts.clear()
        self.hour_song_type_counts.clear()
        self.hour_songs_played.clear()
        self.hour_artists_played.clear()
        self.current_hour += 1
        self.reset_block()


class Constraint(ABC):
    """Base class for all constraints"""
    
    def __init__(self, name: str, severity: str = "error"):
        self.name = name
        self.severity = severity  # "error" or "warning"
    
    @abstractmethod
    def check(self, context: SchedulingContext, **kwargs) -> Optional[ConstraintViolation]:
        """
        Check if constraint is violated.
        Returns None if satisfied, ConstraintViolation if violated.
        """
        pass
    
    @abstractmethod
    def allows(self, context: SchedulingContext, **kwargs) -> bool:
        """
        Check if adding something would violate constraint.
        Used for filtering candidates.
        """
        pass


class MaxPerHourConstraint(Constraint):
    """Maximum count of a category/type per hour"""
    
    def __init__(self, category: str, limit: int, severity: str = "error"):
        super().__init__(f"MaxPerHour_{category}", severity)
        self.category = category
        self.limit = limit
    
    def check(self, context: SchedulingContext, **kwargs) -> Optional[ConstraintViolation]:
        count = context.hour_category_counts.get(self.category, 0)
        if count > self.limit:
            return ConstraintViolation(
                self.name,
                f"Category '{self.category}' exceeded limit: {count} > {self.limit}",
                self.severity
            )
        return None
    
    def allows(self, context: SchedulingContext, category: str = None, **kwargs) -> bool:
        if category != self.category:
            return True
        count = context.hour_category_counts.get(self.category, 0)
        return count < self.limit


class MinPerHourConstraint(Constraint):
    """Minimum count of a category/type per hour"""
    
    def __init__(self, category: str, minimum: int, severity: str = "warning"):
        super().__init__(f"MinPerHour_{category}", severity)
        self.category = category
        self.minimum = minimum
    
    def check(self, context: SchedulingContext, **kwargs) -> Optional[ConstraintViolation]:
        # Only check at end of hour (this is typically a soft constraint)
        count = context.hour_category_counts.get(self.category, 0)
        if count < self.minimum:
            return ConstraintViolation(
                self.name,
                f"Category '{self.category}' below minimum: {count} < {self.minimum}",
                self.severity
            )
        return None
    
    def allows(self, context: SchedulingContext, **kwargs) -> bool:
        # Minimums don't block, they warn
        return True


class MaxPerBlockConstraint(Constraint):
    """Maximum count of a category/type per block (half-hour)"""
    
    def __init__(self, category: str, limit: int, severity: str = "error"):
        super().__init__(f"MaxPerBlock_{category}", severity)
        self.category = category
        self.limit = limit
    
    def check(self, context: SchedulingContext, **kwargs) -> Optional[ConstraintViolation]:
        count = context.block_category_counts.get(self.category, 0)
        if count > self.limit:
            return ConstraintViolation(
                self.name,
                f"Category '{self.category}' exceeded block limit: {count} > {self.limit}",
                self.severity
            )
        return None
    
    def allows(self, context: SchedulingContext, category: str = None, **kwargs) -> bool:
        if category != self.category:
            return True
        count = context.block_category_counts.get(self.category, 0)
        return count < self.limit


class DailyQuotaConstraint(Constraint):
    """Target count of a category for entire day"""
    
    def __init__(self, category: str, target: int, severity: str = "warning"):
        super().__init__(f"DailyQuota_{category}", severity)
        self.category = category
        self.target = target
    
    def check(self, context: SchedulingContext, **kwargs) -> Optional[ConstraintViolation]:
        # This is informational - checked at end of day
        count = context.day_category_counts.get(self.category, 0)
        diff = abs(count - self.target)
        if diff > self.target * 0.1:  # More than 10% off
            return ConstraintViolation(
                self.name,
                f"Category '{self.category}' off target: {count} (target: {self.target})",
                self.severity
            )
        return None
    
    def allows(self, context: SchedulingContext, **kwargs) -> bool:
        # Quotas don't block
        return True
    
    def get_remaining(self, context: SchedulingContext) -> int:
        """How many more needed to hit target?"""
        count = context.day_category_counts.get(self.category, 0)
        return max(0, self.target - count)


class HourlyPatternConstraint(Constraint):
    """
    Enforce a repeating pattern of counts per hour.
    Example: [2, 3, 2, 3] = 2 in hour 1, 3 in hour 2, 2 in hour 3, 3 in hour 4, repeat
    """
    
    def __init__(self, category: str, pattern: List[int], severity: str = "error"):
        super().__init__(f"HourlyPattern_{category}", severity)
        self.category = category
        self.pattern = pattern
    
    def get_hour_limit(self, hour_index: int) -> int:
        """Get the limit for this hour based on pattern"""
        return self.pattern[hour_index % len(self.pattern)]
    
    def check(self, context: SchedulingContext, **kwargs) -> Optional[ConstraintViolation]:
        limit = self.get_hour_limit(context.current_hour)
        count = context.hour_category_counts.get(self.category, 0)
        if count > limit:
            return ConstraintViolation(
                self.name,
                f"Category '{self.category}' exceeded hour {context.current_hour} pattern limit: {count} > {limit}",
                self.severity
            )
        return None
    
    def allows(self, context: SchedulingContext, category: str = None, **kwargs) -> bool:
        if category != self.category:
            return True
        limit = self.get_hour_limit(context.current_hour)
        count = context.hour_category_counts.get(self.category, 0)
        return count < limit


class ConstraintManager:
    """Manages and evaluates multiple constraints"""
    
    def __init__(self):
        self.constraints: List[Constraint] = []
    
    def add(self, constraint: Constraint):
        """Add a constraint"""
        self.constraints.append(constraint)
    
    def check_all(self, context: SchedulingContext, **kwargs) -> List[ConstraintViolation]:
        """Check all constraints, return list of violations"""
        violations = []
        for constraint in self.constraints:
            violation = constraint.check(context, **kwargs)
            if violation:
                violations.append(violation)
        return violations
    
    def allows_all(self, context: SchedulingContext, **kwargs) -> tuple[bool, List[str]]:
        """
        Check if all constraints allow something.
        Returns (allowed, list_of_blocking_reasons)
        """
        blocking_reasons = []
        for constraint in self.constraints:
            if not constraint.allows(context, **kwargs):
                blocking_reasons.append(f"{constraint.name} blocks")
        
        return (len(blocking_reasons) == 0, blocking_reasons)
    
    def get_quota_constraint(self, category: str) -> Optional[DailyQuotaConstraint]:
        """Get daily quota constraint for a category if it exists"""
        for c in self.constraints:
            if isinstance(c, DailyQuotaConstraint) and c.category == category:
                return c
        return None
    
    def get_pattern_constraint(self, category: str) -> Optional[HourlyPatternConstraint]:
        """Get hourly pattern constraint for a category if it exists"""
        for c in self.constraints:
            if isinstance(c, HourlyPatternConstraint) and c.category == category:
                return c
        return None
