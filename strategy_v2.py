"""
Enhanced Strategy System - Bridges legacy constraints with new rule framework.
Clean integration, maintains compatibility, UI-friendly.
"""
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any
from abc import ABC, abstractmethod
import json
from pathlib import Path

from models import Slot
from rule_framework import RuleEngine, BaseRule, RuleResult, RuleType, RulePriority


@dataclass
class SeparationConfig:
    """Separation rule configuration"""
    artist_separation_minutes: int = 90
    song_rest_minutes: int = 1440
    title_separation_minutes: int = 240


@dataclass
class CategoryQuota:
    """Quota for a category"""
    category: str
    min_per_day: Optional[int] = None
    max_per_day: Optional[int] = None
    min_per_hour: Optional[int] = None
    max_per_hour: Optional[int] = None
    target_percentage: Optional[float] = None


class SchedulingStrategy:
    """
    Scheduling strategy that configures rules and constraints.
    Simplified and integrated with new rule system.
    """
    
    def __init__(self, name: str, config: Dict[str, Any], rule_engine: RuleEngine):
        self.name = name
        self.config = config
        self.rule_engine = rule_engine
        self.separation_config = SeparationConfig()
        self.quotas: List[CategoryQuota] = []
        
        self._load_config()
    
    def _load_config(self):
        """Load strategy configuration"""
        # Load separation settings
        sep_cfg = self.config.get("separation", {})
        self.separation_config.artist_separation_minutes = sep_cfg.get("artist_minutes", 90)
        self.separation_config.song_rest_minutes = sep_cfg.get("song_minutes", 1440)
        self.separation_config.title_separation_minutes = sep_cfg.get("title_minutes", 240)
        
        # Load quotas
        quotas_cfg = self.config.get("quotas", [])
        for q_cfg in quotas_cfg:
            self.quotas.append(CategoryQuota(
                category=q_cfg["category"],
                min_per_day=q_cfg.get("min_per_day"),
                max_per_day=q_cfg.get("max_per_day"),
                min_per_hour=q_cfg.get("min_per_hour"),
                max_per_hour=q_cfg.get("max_per_hour"),
                target_percentage=q_cfg.get("target_percentage")
            ))
        
        # Configure rule engine with separation settings
        self._configure_rules()
    
    def _configure_rules(self):
        """Configure rule engine based on strategy"""
        # Import rule classes
        from separation_rules import ArtistSeparationRule, TitleSeparationRule
        from pattern_rotation_rules import CategoryBalanceRule
        
        # Add artist separation (rules have default priority/type)
        artist_rule = ArtistSeparationRule(
            separation_minutes=self.separation_config.artist_separation_minutes
        )
        self.rule_engine.add_rule(artist_rule)
        
        # Add title separation
        title_rule = TitleSeparationRule(
            separation_minutes=self.separation_config.title_separation_minutes
        )
        self.rule_engine.add_rule(title_rule)
        
        # Add category balance rules for quotas with target percentages
        for quota in self.quotas:
            if quota.target_percentage:
                balance_rule = CategoryBalanceRule(
                    target_percentages={quota.category: quota.target_percentage},
                    tolerance=5.0,
                    scope="hour"
                )
                self.rule_engine.add_rule(balance_rule)
    
    def get_quota_for_category(self, category: str) -> Optional[CategoryQuota]:
        """Get quota configuration for a category"""
        for quota in self.quotas:
            if quota.category == category:
                return quota
        return None
    
    def check_hour_quota(self, category: str, current_count: int) -> bool:
        """Check if adding another song of this category would violate hour quota"""
        quota = self.get_quota_for_category(category)
        if not quota:
            return True  # No quota, allow
        
        if quota.max_per_hour and current_count >= quota.max_per_hour:
            return False
        
        return True
    
    def check_day_quota(self, category: str, current_count: int) -> bool:
        """Check if adding another song of this category would violate day quota"""
        quota = self.get_quota_for_category(category)
        if not quota:
            return True  # No quota, allow
        
        if quota.max_per_day and current_count >= quota.max_per_day:
            return False
        
        return True
    
    @classmethod
    def load_from_file(cls, filepath: Path, rule_engine: RuleEngine) -> 'SchedulingStrategy':
        """Load strategy from JSON file"""
        with open(filepath, 'r') as f:
            config = json.load(f)
        
        strategy_name = config.get("name", "Unnamed Strategy")
        return cls(strategy_name, config, rule_engine)


def load_strategy(config_path: Path, rule_engine: RuleEngine) -> SchedulingStrategy:
    """
    Load scheduling strategy from configuration file.
    
    Args:
        config_path: Path to strategy config JSON
        rule_engine: Rule engine to configure
    
    Returns:
        Configured SchedulingStrategy
    """
    return SchedulingStrategy.load_from_file(config_path, rule_engine)
