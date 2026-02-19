"""
Rule configuration loader.
Loads all rules from JSON config and instantiates appropriate rule objects.
"""
import json
from pathlib import Path
from typing import Dict, Any, List

from rule_framework import RuleEngine, RuleGroup, RuleType, RulePriority, RuleGroupMode

# Import all rule classes
from separation_rules import (
    ArtistSeparationRule,
    ArtistKeywordSeparationRule,
    TitleSeparationRule,
    PreviousDaySeparationRule,
    HourOpenerSeparationRule,
    SweepOpenerSeparationRule
)

from flow_rules import (
    GenderSeparationRule,
    SoundCodeSeparationRule,
    MoodFlowRule,
    EnergyFlowRule,
    EndingTypeRule,
    BPMMatchingRule
)

from pattern_rotation_rules import (
    DisallowedPatternRule,
    SameDayRepeatRule,
    CategoryBalanceRule,
    DaypartDistributionRule,
    HourRestrictionRule
)

from tempo_rules import TempoRuleSet


def parse_rule_type(type_str: str) -> RuleType:
    """Convert string to RuleType enum"""
    mapping = {
        "unbreakable": RuleType.UNBREAKABLE,
        "breakable": RuleType.BREAKABLE,
        "goal": RuleType.GOAL
    }
    return mapping.get(type_str.lower(), RuleType.UNBREAKABLE)


def parse_priority(priority_str: str) -> RulePriority:
    """Convert string to RulePriority enum"""
    mapping = {
        "critical": RulePriority.CRITICAL,
        "high": RulePriority.HIGH,
        "medium": RulePriority.MEDIUM,
        "low": RulePriority.LOW
    }
    return mapping.get(priority_str.lower(), RulePriority.MEDIUM)


def load_separation_rules(config: Dict[str, Any]) -> List:
    """Load separation rules from config"""
    rules = []
    sep_config = config.get('separation_rules', {})
    
    # Artist separation
    if sep_config.get('artist_separation', {}).get('enabled'):
        cfg = sep_config['artist_separation']
        rules.append(ArtistSeparationRule(
            separation_minutes=cfg.get('separation_minutes', 90),
            per_artist_overrides=cfg.get('per_artist_overrides', {}),
            rule_type=parse_rule_type(cfg.get('type', 'unbreakable')),
            priority=parse_priority(cfg.get('priority', 'critical'))
        ))
    
    # Artist keyword separation
    if sep_config.get('artist_keyword_separation', {}).get('enabled'):
        cfg = sep_config['artist_keyword_separation']
        rules.append(ArtistKeywordSeparationRule(
            separation_minutes=cfg.get('separation_minutes', 90),
            per_keyword_overrides=cfg.get('per_keyword_overrides', {}),
            rule_type=parse_rule_type(cfg.get('type', 'unbreakable')),
            priority=parse_priority(cfg.get('priority', 'critical'))
        ))
    
    # Title separation
    if sep_config.get('title_separation', {}).get('enabled'):
        cfg = sep_config['title_separation']
        rules.append(TitleSeparationRule(
            separation_minutes=cfg.get('separation_minutes', 240),
            rule_type=parse_rule_type(cfg.get('type', 'unbreakable')),
            priority=parse_priority(cfg.get('priority', 'high'))
        ))
    
    # Previous day separation
    if sep_config.get('previous_day_separation', {}).get('enabled'):
        cfg = sep_config['previous_day_separation']
        rules.append(PreviousDaySeparationRule(
            window_minutes=cfg.get('window_minutes', 30),
            apply_to=cfg.get('apply_to', 'artist'),
            rule_type=parse_rule_type(cfg.get('type', 'breakable')),
            priority=parse_priority(cfg.get('priority', 'medium'))
        ))
    
    # Hour opener separation
    if sep_config.get('hour_opener_separation', {}).get('enabled'):
        cfg = sep_config['hour_opener_separation']
        rules.append(HourOpenerSeparationRule(
            separation_minutes=cfg.get('separation_minutes', 180),
            apply_to=cfg.get('apply_to', 'both'),
            rule_type=parse_rule_type(cfg.get('type', 'breakable')),
            priority=parse_priority(cfg.get('priority', 'medium'))
        ))
    
    # Sweep opener separation
    if sep_config.get('sweep_opener_separation', {}).get('enabled'):
        cfg = sep_config['sweep_opener_separation']
        rules.append(SweepOpenerSeparationRule(
            separation_minutes=cfg.get('separation_minutes', 180),
            apply_to=cfg.get('apply_to', 'both'),
            rule_type=parse_rule_type(cfg.get('type', 'breakable')),
            priority=parse_priority(cfg.get('priority', 'medium'))
        ))
    
    return rules


def load_flow_rules(config: Dict[str, Any]) -> List:
    """Load flow control rules from config"""
    rules = []
    flow_config = config.get('flow_rules', {})
    
    # Gender separation
    if flow_config.get('gender_separation', {}).get('enabled'):
        cfg = flow_config['gender_separation']
        rules.append(GenderSeparationRule(
            max_in_a_row=cfg.get('max_in_a_row', 3),
            separation_minutes=cfg.get('separation_minutes'),
            rule_type=parse_rule_type(cfg.get('type', 'unbreakable')),
            priority=parse_priority(cfg.get('priority', 'high'))
        ))
    
    # Sound code separation
    if flow_config.get('sound_code_separation', {}).get('enabled'):
        cfg = flow_config['sound_code_separation']
        rules.append(SoundCodeSeparationRule(
            max_in_a_row=cfg.get('max_in_a_row', 2),
            codes_to_separate=cfg.get('codes_to_separate', []),
            rule_type=parse_rule_type(cfg.get('type', 'breakable')),
            priority=parse_priority(cfg.get('priority', 'medium'))
        ))
    
    # Mood flow
    if flow_config.get('mood_flow', {}).get('enabled'):
        cfg = flow_config['mood_flow']
        rules.append(MoodFlowRule(
            max_mood_jump=cfg.get('max_mood_jump', 3),
            rule_type=parse_rule_type(cfg.get('type', 'breakable')),
            priority=parse_priority(cfg.get('priority', 'medium'))
        ))
    
    # Energy flow
    if flow_config.get('energy_flow', {}).get('enabled'):
        cfg = flow_config['energy_flow']
        rules.append(EnergyFlowRule(
            max_energy_drop=cfg.get('max_energy_drop', 3),
            rule_type=parse_rule_type(cfg.get('type', 'breakable')),
            priority=parse_priority(cfg.get('priority', 'medium'))
        ))
    
    # Ending type
    if flow_config.get('ending_type', {}).get('enabled'):
        cfg = flow_config['ending_type']
        rules.append(EndingTypeRule(
            rule_type=parse_rule_type(cfg.get('type', 'breakable')),
            priority=parse_priority(cfg.get('priority', 'low'))
        ))
    
    # BPM matching
    if flow_config.get('bpm_matching', {}).get('enabled'):
        cfg = flow_config['bpm_matching']
        rules.append(BPMMatchingRule(
            max_bpm_difference=cfg.get('max_bpm_difference', 20),
            rule_type=parse_rule_type(cfg.get('type', 'breakable')),
            priority=parse_priority(cfg.get('priority', 'low'))
        ))
    
    return rules


def load_pattern_rotation_rules(config: Dict[str, Any]) -> List:
    """Load pattern and rotation rules from config"""
    rules = []
    
    # Pattern rules
    pattern_config = config.get('pattern_rules', {})
    
    for pattern_name, cfg in pattern_config.items():
        if cfg.get('enabled'):
            rules.append(DisallowedPatternRule(
                field_name=cfg['field_name'],
                patterns=cfg['disallowed_patterns'],
                rule_type=parse_rule_type(cfg.get('type', 'unbreakable')),
                priority=parse_priority(cfg.get('priority', 'high'))
            ))
    
    # Rotation rules
    rotation_config = config.get('rotation_rules', {})
    
    # Same day repeat
    if rotation_config.get('same_day_repeat', {}).get('enabled'):
        cfg = rotation_config['same_day_repeat']
        rules.append(SameDayRepeatRule(
            rule_type=parse_rule_type(cfg.get('type', 'unbreakable')),
            priority=parse_priority(cfg.get('priority', 'high'))
        ))
    
    # Category balance
    if rotation_config.get('category_balance', {}).get('enabled'):
        cfg = rotation_config['category_balance']
        rules.append(CategoryBalanceRule(
            target_percentages=cfg.get('target_percentages', {}),
            tolerance=cfg.get('tolerance', 5.0),
            scope=cfg.get('scope', 'hour'),
            rule_type=parse_rule_type(cfg.get('type', 'breakable')),
            priority=parse_priority(cfg.get('priority', 'medium'))
        ))
    
    # Daypart distribution
    if rotation_config.get('daypart_distribution', {}).get('enabled'):
        cfg = rotation_config['daypart_distribution']
        rules.append(DaypartDistributionRule(
            dayparts=cfg.get('dayparts', []),
            lookback_days=cfg.get('lookback_days', 7),
            max_percentage_in_one=cfg.get('max_percentage_in_one', 40.0),
            rule_type=parse_rule_type(cfg.get('type', 'breakable')),
            priority=parse_priority(cfg.get('priority', 'low'))
        ))
    
    # Hour restriction
    if rotation_config.get('hour_restriction', {}).get('enabled'):
        cfg = rotation_config['hour_restriction']
        rules.append(HourRestrictionRule(
            allowed_hours=cfg.get('allowed_hours'),
            blocked_hours=cfg.get('blocked_hours', []),
            allowed_days=cfg.get('allowed_days'),
            rule_type=parse_rule_type(cfg.get('type', 'unbreakable')),
            priority=parse_priority(cfg.get('priority', 'critical'))
        ))
    
    return rules


def load_rule_engine_from_config(config_path: Path) -> RuleEngine:
    """
    Load complete rule engine from configuration file.
    
    Args:
        config_path: Path to rules configuration JSON
    
    Returns:
        Configured RuleEngine instance
    """
    with open(config_path, 'r') as f:
        config = json.load(f)
    
    rules_config = config.get('rules_config', {})
    
    engine = RuleEngine()
    
    # Load all rule types
    all_rules = []
    all_rules.extend(load_separation_rules(rules_config))
    all_rules.extend(load_flow_rules(rules_config))
    all_rules.extend(load_pattern_rotation_rules(rules_config))
    
    # Add to engine
    for rule in all_rules:
        engine.add_rule(rule)
    
    # Load tempo rules if present
    tempo_config = rules_config.get('tempo_rules')
    if tempo_config:
        tempo_rules = TempoRuleSet.from_config(tempo_config)
        if tempo_rules.enabled:
            # Tempo rules are handled separately (already built)
            pass
    
    # Load rule groups
    for group_config in rules_config.get('rule_groups', []):
        if not group_config.get('enabled', True):
            continue
        
        # Parse mode
        mode_str = group_config.get('mode', 'independent')
        mode_map = {
            'all': RuleGroupMode.ALL_MUST_PASS,
            'any': RuleGroupMode.ANY_CAN_PASS,
            'independent': RuleGroupMode.INDEPENDENT
        }
        mode = mode_map.get(mode_str, RuleGroupMode.INDEPENDENT)
        
        group = RuleGroup(
            name=group_config['name'],
            mode=mode,
            enabled=group_config.get('enabled', True),
            dayparts=group_config.get('dayparts', []),
            clocks=group_config.get('clocks', []),
            categories=group_config.get('categories', []),
            apply_in_auto=group_config.get('apply_in_auto', True),
            apply_in_manual=group_config.get('apply_in_manual', True)
        )
        
        # TODO: Load rules within group
        # For now, rule groups are defined but rules within them
        # would need additional parsing
        
        engine.add_rule_group(group)
    
    return engine


def load_rules_from_file(filepath: str) -> RuleEngine:
    """Convenience function to load rules from file path"""
    return load_rule_engine_from_config(Path(filepath))
