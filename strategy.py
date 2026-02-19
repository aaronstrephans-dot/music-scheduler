"""
Strategy system for music scheduling.
Defines different approaches: rotation-based, goal-based, custom.
"""
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any
from abc import ABC, abstractmethod
import json
from pathlib import Path

from constraints import (
    ConstraintManager, MaxPerHourConstraint, MinPerHourConstraint,
    MaxPerBlockConstraint, DailyQuotaConstraint, HourlyPatternConstraint,
    SchedulingContext
)
from rule_engine import (
    RuleEngine, Rule, Condition, RuleAction,
    ComparisonCondition, AndCondition, OrCondition,
    create_quota_rule, create_pattern_rule, create_max_rule
)
from models import Slot, SlotFallback


@dataclass
class SlotLayerConfig:
    """Configuration for multi-layer slot evaluation"""
    pool: Optional[str] = None
    require_song_type: Optional[str] = None
    require_rotation: Optional[str] = None
    require_tempo: Optional[str] = None
    weight: float = 1.0  # Relative preference for this layer


@dataclass
class SeparationConfig:
    """Separation rule configuration"""
    artist_separation_minutes: int = 90
    song_rest_minutes: int = 1440
    current_artist_separation_minutes: Optional[int] = None  # Override for specific categories


class SchedulingStrategy(ABC):
    """Base class for scheduling strategies"""
    
    def __init__(self, name: str, config: Dict[str, Any]):
        self.name = name
        self.config = config
        self.constraints = ConstraintManager()
        self.rules = RuleEngine()
        self.separation_config = SeparationConfig()
        self._initialize()
    
    @abstractmethod
    def _initialize(self):
        """Initialize constraints and rules from config"""
        pass
    
    @abstractmethod
    def get_slot_layers(self, slot: Slot, context: SchedulingContext) -> List[SlotLayerConfig]:
        """
        Get the evaluation layers for a slot.
        Returns ordered list of layer configs (primary first, then fallbacks).
        """
        pass
    
    def get_constraints(self) -> ConstraintManager:
        """Get constraint manager"""
        return self.constraints
    
    def get_rules(self) -> RuleEngine:
        """Get rule engine"""
        return self.rules
    
    def get_separation_config(self) -> SeparationConfig:
        """Get separation configuration"""
        return self.separation_config


class RotationStrategy(SchedulingStrategy):
    """
    Standard rotation-based scheduling.
    Prioritizes rotation tiers (Power, Current, Recurrent, Gold).
    """
    
    def _initialize(self):
        """Initialize rotation strategy from config"""
        # Load separation config
        sep_cfg = self.config.get("separation", {})
        self.separation_config.artist_separation_minutes = sep_cfg.get("artist_minutes", 90)
        self.separation_config.song_rest_minutes = sep_cfg.get("song_minutes", 1440)
        
        # Load constraints
        constraints_cfg = self.config.get("constraints", [])
        for c_cfg in constraints_cfg:
            c_type = c_cfg.get("type")
            
            if c_type == "max_per_hour":
                self.constraints.add(MaxPerHourConstraint(
                    c_cfg["category"],
                    c_cfg["limit"],
                    c_cfg.get("severity", "error")
                ))
            elif c_type == "min_per_hour":
                self.constraints.add(MinPerHourConstraint(
                    c_cfg["category"],
                    c_cfg["minimum"],
                    c_cfg.get("severity", "warning")
                ))
            elif c_type == "max_per_block":
                self.constraints.add(MaxPerBlockConstraint(
                    c_cfg["category"],
                    c_cfg["limit"],
                    c_cfg.get("severity", "error")
                ))
    
    def get_slot_layers(self, slot: Slot, context: SchedulingContext) -> List[SlotLayerConfig]:
        """
        For rotation strategy, use slot's defined pools and fallbacks directly.
        """
        layers = []
        
        # Primary layer
        layers.append(SlotLayerConfig(
            pool=slot.primary_pool,
            require_song_type=slot.require_song_type,
            weight=1.0
        ))
        
        # Fallback layers
        for fb in slot.fallbacks:
            layers.append(SlotLayerConfig(
                pool=fb.pool or slot.primary_pool,
                require_song_type=fb.require_song_type or slot.require_song_type,
                weight=0.8  # Lower preference for fallbacks
            ))
        
        return layers


class GoalBasedStrategy(SchedulingStrategy):
    """
    Goal-based scheduling with quotas and patterns.
    Supports hourly quotas, daily targets, weighted selection.
    """
    
    def _initialize(self):
        """Initialize goal-based strategy from config"""
        # Load separation config
        sep_cfg = self.config.get("separation", {})
        self.separation_config.artist_separation_minutes = sep_cfg.get("artist_minutes", 90)
        self.separation_config.song_rest_minutes = sep_cfg.get("song_minutes", 1440)
        self.separation_config.current_artist_separation_minutes = sep_cfg.get("current_artist_minutes")
        
        # Load goal rules
        goal_cfg = self.config.get("goal_rules", {})
        
        # Hourly pattern
        pattern = goal_cfg.get("current_quota_pattern")
        if pattern:
            self.constraints.add(HourlyPatternConstraint(
                "Current",
                pattern,
                severity="error"
            ))
            
            # Create rules that prefer Current when under quota
            pattern_rules = create_pattern_rule("Current", pattern)
            for rule in pattern_rules:
                self.rules.add_rule(rule)
        
        # Daily quota
        daily_target = goal_cfg.get("daily_current_target")
        if daily_target:
            self.constraints.add(DailyQuotaConstraint(
                "Current",
                daily_target,
                severity="warning"
            ))
        
        # Additional constraints
        constraints_cfg = self.config.get("constraints", [])
        for c_cfg in constraints_cfg:
            c_type = c_cfg.get("type")
            
            if c_type == "max_per_hour":
                self.constraints.add(MaxPerHourConstraint(
                    c_cfg["category"],
                    c_cfg["limit"],
                    c_cfg.get("severity", "error")
                ))
                
                # Also add blocking rule
                self.rules.add_rule(create_max_rule(
                    c_cfg["category"],
                    c_cfg["limit"],
                    scope="hour"
                ))
            
            elif c_type == "min_per_hour":
                self.constraints.add(MinPerHourConstraint(
                    c_cfg["category"],
                    c_cfg["minimum"],
                    c_cfg.get("severity", "warning")
                ))
        
        # Load custom rules
        rules_cfg = self.config.get("rules", [])
        for r_cfg in rules_cfg:
            rule = self._parse_rule(r_cfg)
            if rule:
                self.rules.add_rule(rule)
    
    def _parse_rule(self, rule_cfg: Dict) -> Optional[Rule]:
        """Parse a rule from config"""
        # Parse condition
        cond_cfg = rule_cfg.get("condition")
        if not cond_cfg:
            return None
        
        condition = self._parse_condition(cond_cfg)
        if not condition:
            return None
        
        # Parse action
        action_cfg = rule_cfg.get("action")
        if not action_cfg:
            return None
        
        action = RuleAction(
            action_type=action_cfg.get("type", "prefer"),
            target=action_cfg.get("target", ""),
            parameters=action_cfg.get("parameters", {})
        )
        
        return Rule(
            name=rule_cfg.get("name", "CustomRule"),
            condition=condition,
            action=action,
            priority=rule_cfg.get("priority", 0)
        )
    
    def _parse_condition(self, cond_cfg) -> Optional[Condition]:
        """Parse a condition from config"""
        # Simple comparison
        if isinstance(cond_cfg, dict) and "field" in cond_cfg:
            return ComparisonCondition(
                field=cond_cfg["field"],
                operator=cond_cfg.get("operator", "=="),
                value=cond_cfg["value"],
                scope=cond_cfg.get("scope", "hour")
            )
        
        # AND/OR/NOT
        if isinstance(cond_cfg, dict):
            if "and" in cond_cfg:
                sub_conds = [self._parse_condition(c) for c in cond_cfg["and"]]
                return AndCondition([c for c in sub_conds if c])
            elif "or" in cond_cfg:
                sub_conds = [self._parse_condition(c) for c in cond_cfg["or"]]
                return OrCondition([c for c in sub_conds if c])
        
        return None
    
    def get_slot_layers(self, slot: Slot, context: SchedulingContext) -> List[SlotLayerConfig]:
        """
        For goal-based strategy, dynamically modify layers based on quota status.
        """
        layers = []
        
        # Check if we should prioritize Current category
        current_pools = self.config.get("goal_rules", {}).get("current_pools", {})
        
        # Get hourly pattern constraint to know current quota
        pattern_constraint = self.constraints.get_pattern_constraint("Current")
        should_prioritize_current = False
        
        if pattern_constraint:
            hour_limit = pattern_constraint.get_hour_limit(context.current_hour)
            current_count = context.hour_category_counts.get("Current", 0)
            should_prioritize_current = current_count < hour_limit
        
        # Build layers based on song type
        song_type = slot.require_song_type
        
        if should_prioritize_current and song_type:
            # Try Current pools first (Heavy > Medium > Light)
            for pool_name, pool_config in sorted(
                current_pools.items(),
                key=lambda x: x[1].get("weight", 1),
                reverse=True
            ):
                layers.append(SlotLayerConfig(
                    pool=pool_config.get("pool"),
                    require_song_type=song_type,
                    weight=pool_config.get("weight", 1.0)
                ))
        
        # Then add recurrent/gold fallbacks
        fallback_pools_cfg = self.config.get("slot_template", {}).get("fallback_pools", {})
        fallback_pools = fallback_pools_cfg.get(song_type, ["Recurrent", "Gold"])
        
        for pool_name in fallback_pools:
            # Skip if already added
            if any(l.pool == pool_name and l.require_song_type == song_type for l in layers):
                continue
            
            layers.append(SlotLayerConfig(
                pool=pool_name,
                require_song_type=song_type,
                weight=0.5
            ))
        
        # If no layers created, use slot's defined fallbacks
        if not layers:
            layers.append(SlotLayerConfig(
                pool=slot.primary_pool,
                require_song_type=slot.require_song_type,
                weight=1.0
            ))
            
            for fb in slot.fallbacks:
                layers.append(SlotLayerConfig(
                    pool=fb.pool or slot.primary_pool,
                    require_song_type=fb.require_song_type or slot.require_song_type,
                    weight=0.8
                ))
        
        return layers


def load_strategy_from_file(filepath: Path) -> SchedulingStrategy:
    """Load a strategy from JSON configuration file"""
    with open(filepath, 'r') as f:
        config = json.load(f)
    
    strategy_type = config.get("strategy_type", "rotation")
    name = config.get("name", "Unnamed Strategy")
    
    if strategy_type == "rotation" or strategy_type == "rotation_based":
        return RotationStrategy(name, config)
    elif strategy_type == "goal" or strategy_type == "goal_based":
        return GoalBasedStrategy(name, config)
    else:
        raise ValueError(f"Unknown strategy type: {strategy_type}")


def load_strategy_from_dict(config: Dict[str, Any]) -> SchedulingStrategy:
    """Load a strategy from config dictionary"""
    strategy_type = config.get("strategy_type", "rotation")
    name = config.get("name", "Unnamed Strategy")
    
    if strategy_type == "rotation" or strategy_type == "rotation_based":
        return RotationStrategy(name, config)
    elif strategy_type == "goal" or strategy_type == "goal_based":
        return GoalBasedStrategy(name, config)
    else:
        raise ValueError(f"Unknown strategy type: {strategy_type}")
