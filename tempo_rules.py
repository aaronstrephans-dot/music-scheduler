"""
Tempo rules system - Music1-style tempo management.
Supports limits, transitions, and averages.
"""
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple
from enum import Enum


class TempoValue(Enum):
    """Standard tempo values with numeric scores for averaging"""
    VERY_SLOW = 1
    SLOW = 2
    MEDIUM = 3
    FAST = 4
    VERY_FAST = 5
    
    @classmethod
    def from_string(cls, tempo_str: Optional[str]) -> Optional['TempoValue']:
        """Convert string tempo to enum"""
        if not tempo_str:
            return None
        
        mapping = {
            "Very Slow": cls.VERY_SLOW,
            "Slow": cls.SLOW,
            "Medium": cls.MEDIUM,
            "Fast": cls.FAST,
            "Very Fast": cls.VERY_FAST
        }
        return mapping.get(tempo_str)
    
    @classmethod
    def get_score(cls, tempo_str: Optional[str]) -> float:
        """Get numeric score for tempo (for averaging)"""
        tempo_enum = cls.from_string(tempo_str)
        return tempo_enum.value if tempo_enum else 3.0  # Default to medium


@dataclass
class TempoLimit:
    """Limit on number of songs of a specific tempo"""
    tempo: str  # "Very Fast", "Fast", "Medium", "Slow", "Very Slow"
    max_count: Optional[int] = None
    min_count: Optional[int] = None
    scope: str = "hour"  # "hour" or "block"
    
    def check(self, tempo_counts: Dict[str, int]) -> Tuple[bool, Optional[str]]:
        """Check if limit is violated"""
        count = tempo_counts.get(self.tempo, 0)
        
        if self.max_count and count > self.max_count:
            return False, f"Too many {self.tempo} songs: {count} > {self.max_count}"
        
        if self.min_count and count < self.min_count:
            return False, f"Too few {self.tempo} songs: {count} < {self.min_count}"
        
        return True, None


@dataclass
class TempoTransition:
    """Rule for tempo transitions between songs"""
    from_tempo: str
    to_tempo: str
    allowed: bool = True
    penalty_score: float = 0.0  # How bad is this transition? (0 = fine, 1 = worst)
    message: Optional[str] = None
    
    def matches(self, from_t: str, to_t: str) -> bool:
        """Check if this rule applies to a transition"""
        return self.from_tempo == from_t and self.to_tempo == to_t
    
    def is_valid(self) -> bool:
        """Is this transition allowed?"""
        return self.allowed
    
    def get_message(self) -> str:
        """Get violation message"""
        if self.message:
            return self.message
        return f"Transition {self.from_tempo} → {self.to_tempo} not allowed"


@dataclass
class TempoAverage:
    """Target tempo average for a time period"""
    daypart_name: str
    target_average: float  # 1.0 (Very Slow) to 5.0 (Very Fast)
    min_average: Optional[float] = None
    max_average: Optional[float] = None
    tolerance: float = 0.5
    
    def check(self, actual_average: float) -> Tuple[bool, Optional[str]]:
        """Check if average is within acceptable range"""
        min_val = self.min_average if self.min_average else self.target_average - self.tolerance
        max_val = self.max_average if self.max_average else self.target_average + self.tolerance
        
        if actual_average < min_val:
            return False, f"{self.daypart_name} tempo too slow: {actual_average:.2f} < {min_val:.2f}"
        
        if actual_average > max_val:
            return False, f"{self.daypart_name} tempo too fast: {actual_average:.2f} > {max_val:.2f}"
        
        return True, None


@dataclass
class TempoRuleSet:
    """Complete set of tempo rules"""
    enabled: bool = False
    limits: List[TempoLimit] = field(default_factory=list)
    transitions: List[TempoTransition] = field(default_factory=list)
    averages: List[TempoAverage] = field(default_factory=list)
    
    # Default transitions if none specified
    use_default_transitions: bool = True
    
    def __post_init__(self):
        """Add default transition rules if enabled"""
        if self.use_default_transitions and not self.transitions:
            self.transitions = self._get_default_transitions()
    
    def _get_default_transitions(self) -> List[TempoTransition]:
        """Get sensible default transition rules"""
        return [
            # Very Fast → Slow/Very Slow: not allowed (too jarring)
            TempoTransition("Very Fast", "Slow", allowed=False, penalty_score=0.9),
            TempoTransition("Very Fast", "Very Slow", allowed=False, penalty_score=1.0),
            
            # Fast → Very Slow: discouraged but not forbidden
            TempoTransition("Fast", "Very Slow", allowed=True, penalty_score=0.7),
            
            # Very Slow → Very Fast: also jarring
            TempoTransition("Very Slow", "Very Fast", allowed=False, penalty_score=0.9),
            
            # Slow → Very Fast: discouraged
            TempoTransition("Slow", "Very Fast", allowed=True, penalty_score=0.6),
        ]
    
    def check_transition(self, from_tempo: str, to_tempo: str) -> Tuple[bool, float, Optional[str]]:
        """
        Check if a tempo transition is valid.
        Returns (is_allowed, penalty_score, message)
        """
        if not self.enabled:
            return True, 0.0, None
        
        # Check for explicit rule
        for rule in self.transitions:
            if rule.matches(from_tempo, to_tempo):
                if not rule.is_valid():
                    return False, rule.penalty_score, rule.get_message()
                return True, rule.penalty_score, None
        
        # No explicit rule - allowed but no penalty
        return True, 0.0, None
    
    def check_limits(self, tempo_counts: Dict[str, int], scope: str = "hour") -> List[str]:
        """Check all tempo limits for violations"""
        if not self.enabled:
            return []
        
        violations = []
        for limit in self.limits:
            if limit.scope == scope:
                is_valid, message = limit.check(tempo_counts)
                if not is_valid and message:
                    violations.append(message)
        
        return violations
    
    def check_average(self, tempos: List[str], daypart_name: str) -> Tuple[bool, Optional[str]]:
        """Check if tempo average meets target for daypart"""
        if not self.enabled or not self.averages:
            return True, None
        
        # Find matching daypart rule
        rule = None
        for avg_rule in self.averages:
            if avg_rule.daypart_name == daypart_name:
                rule = avg_rule
                break
        
        if not rule:
            return True, None  # No rule for this daypart
        
        # Calculate actual average
        if not tempos:
            return True, None
        
        scores = [TempoValue.get_score(t) for t in tempos]
        actual_avg = sum(scores) / len(scores)
        
        return rule.check(actual_avg)
    
    @classmethod
    def from_config(cls, config: Dict) -> 'TempoRuleSet':
        """Load tempo rules from configuration dictionary"""
        if not config:
            return cls(enabled=False)
        
        # Parse limits
        limits = []
        for limit_cfg in config.get("limits", []):
            limits.append(TempoLimit(
                tempo=limit_cfg["tempo"],
                max_count=limit_cfg.get("max_count"),
                min_count=limit_cfg.get("min_count"),
                scope=limit_cfg.get("scope", "hour")
            ))
        
        # Parse transitions
        transitions = []
        for trans_cfg in config.get("transitions", []):
            transitions.append(TempoTransition(
                from_tempo=trans_cfg["from"],
                to_tempo=trans_cfg["to"],
                allowed=trans_cfg.get("allowed", True),
                penalty_score=trans_cfg.get("penalty", 0.0),
                message=trans_cfg.get("message")
            ))
        
        # Parse averages
        averages = []
        for avg_cfg in config.get("averages", []):
            averages.append(TempoAverage(
                daypart_name=avg_cfg["daypart"],
                target_average=avg_cfg["target"],
                min_average=avg_cfg.get("min"),
                max_average=avg_cfg.get("max"),
                tolerance=avg_cfg.get("tolerance", 0.5)
            ))
        
        return cls(
            enabled=config.get("enabled", False),
            limits=limits,
            transitions=transitions,
            averages=averages,
            use_default_transitions=config.get("use_defaults", True) and not transitions
        )
