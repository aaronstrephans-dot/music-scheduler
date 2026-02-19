"""
Core rule framework - Priority, breakable/unbreakable, rule groups.
Based on MusicMaster, Music1, PowerGold industry standards.
"""
from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any, Callable
from enum import Enum
from abc import ABC, abstractmethod


class RuleType(Enum):
    """Type of rule - determines enforcement level"""
    UNBREAKABLE = "unbreakable"  # Hard rule - must pass
    BREAKABLE = "breakable"      # Soft rule - prefer to pass but can break
    GOAL = "goal"                # Aspirational - nice to have


class RulePriority(Enum):
    """Priority order for testing rules"""
    CRITICAL = 1    # Test first (artist separation, legal requirements)
    HIGH = 2        # Test second (tempo flow, gender balance)
    MEDIUM = 3      # Test third (sound codes, mood)
    LOW = 4         # Test last (nice-to-haves)


class RuleResult:
    """Result of testing a rule"""
    def __init__(
        self,
        passed: bool,
        score: float = 0.0,
        message: Optional[str] = None,
        rule_name: Optional[str] = None
    ):
        self.passed = passed
        self.score = score  # 0.0 = worst, 1.0 = perfect (for breakable rules)
        self.message = message
        self.rule_name = rule_name
    
    def __bool__(self):
        """Allow if result: syntax"""
        return self.passed


class BaseRule(ABC):
    """Base class for all scheduling rules"""
    
    def __init__(
        self,
        name: str,
        rule_type: RuleType = RuleType.UNBREAKABLE,
        priority: RulePriority = RulePriority.MEDIUM,
        enabled: bool = True
    ):
        self.name = name
        self.rule_type = rule_type
        self.priority = priority
        self.enabled = enabled
    
    @abstractmethod
    def test(self, song, context) -> RuleResult:
        """
        Test if song passes this rule.
        
        Args:
            song: Song object to test
            context: Scheduling context (history, hour state, etc.)
        
        Returns:
            RuleResult with pass/fail and optional score
        """
        pass
    
    def is_breakable(self) -> bool:
        """Is this a breakable rule?"""
        return self.rule_type in [RuleType.BREAKABLE, RuleType.GOAL]
    
    def is_critical(self) -> bool:
        """Is this a critical priority rule?"""
        return self.priority == RulePriority.CRITICAL


class RuleGroupMode(Enum):
    """How rules within a group are evaluated"""
    ALL_MUST_PASS = "all"     # AND logic - all rules must pass
    ANY_CAN_PASS = "any"      # OR logic - at least one must pass
    INDEPENDENT = "independent"  # Each rule tested independently


@dataclass
class RuleGroup:
    """
    Group of rules with shared conditions.
    MusicMaster-style rule groups with dayparting, clock restrictions, filters.
    """
    name: str
    rules: List[BaseRule] = field(default_factory=list)
    mode: RuleGroupMode = RuleGroupMode.INDEPENDENT
    
    # When to apply this group
    enabled: bool = True
    dayparts: List[str] = field(default_factory=list)  # Empty = all dayparts
    clocks: List[str] = field(default_factory=list)    # Empty = all clocks
    categories: List[str] = field(default_factory=list)  # Empty = all categories
    
    # Filter - only test certain songs
    filter_func: Optional[Callable] = None
    
    # Availability
    apply_in_auto: bool = True      # Apply during automatic scheduling
    apply_in_manual: bool = True    # Apply during manual editing
    
    def should_apply(self, context) -> bool:
        """Check if this rule group should apply in current context"""
        if not self.enabled:
            return False
        
        # Check scheduling mode
        is_auto = context.get('is_auto_scheduling', True)
        if is_auto and not self.apply_in_auto:
            return False
        if not is_auto and not self.apply_in_manual:
            return False
        
        # Check daypart
        if self.dayparts:
            current_daypart = context.get('daypart')
            if current_daypart not in self.dayparts:
                return False
        
        # Check clock
        if self.clocks:
            current_clock = context.get('clock_name')
            if current_clock not in self.clocks:
                return False
        
        # Check category
        if self.categories:
            song = context.get('song')
            if song and hasattr(song, 'rotation'):
                if song.rotation not in self.categories:
                    return False
        
        return True
    
    def test_song(self, song, context) -> RuleResult:
        """
        Test song against all rules in group.
        
        Returns:
            RuleResult based on group mode
        """
        if not self.should_apply(context):
            return RuleResult(True, 1.0, "Rule group not applicable")
        
        # Apply filter if present
        if self.filter_func:
            if not self.filter_func(song, context):
                return RuleResult(True, 1.0, "Song filtered out of rule group")
        
        results = []
        for rule in self.rules:
            if rule.enabled:
                result = rule.test(song, context)
                results.append(result)
        
        if not results:
            return RuleResult(True, 1.0, "No active rules in group")
        
        # Evaluate based on mode
        if self.mode == RuleGroupMode.ALL_MUST_PASS:
            # AND logic - all must pass
            all_passed = all(r.passed for r in results)
            avg_score = sum(r.score for r in results) / len(results)
            
            if not all_passed:
                failed = [r for r in results if not r.passed]
                message = f"{self.name}: {len(failed)} rule(s) failed"
                return RuleResult(False, avg_score, message, self.name)
            
            return RuleResult(True, avg_score, f"{self.name}: All rules passed", self.name)
        
        elif self.mode == RuleGroupMode.ANY_CAN_PASS:
            # OR logic - at least one must pass
            any_passed = any(r.passed for r in results)
            avg_score = sum(r.score for r in results) / len(results)
            
            if not any_passed:
                message = f"{self.name}: All rules failed (OR group)"
                return RuleResult(False, avg_score, message, self.name)
            
            return RuleResult(True, avg_score, f"{self.name}: At least one rule passed", self.name)
        
        else:  # INDEPENDENT
            # Return worst result
            worst = min(results, key=lambda r: r.score if r.passed else -1)
            return worst


class RuleEngine:
    """
    Master rule engine that manages all rules and rule groups.
    Tests songs in priority order, handles breakable rules.
    """
    
    def __init__(self):
        self.rule_groups: List[RuleGroup] = []
        self.standalone_rules: List[BaseRule] = []
    
    def add_rule(self, rule: BaseRule):
        """Add a standalone rule"""
        self.standalone_rules.append(rule)
    
    def add_rule_group(self, group: RuleGroup):
        """Add a rule group"""
        self.rule_groups.append(group)
    
    def test_song(self, song, context, respect_priority: bool = True) -> Dict[str, Any]:
        """
        Test song against all rules.
        
        Args:
            song: Song to test
            context: Scheduling context
            respect_priority: Test in priority order and stop on first unbreakable failure
        
        Returns:
            dict with:
                - passed: bool (overall pass/fail for unbreakable rules)
                - score: float (composite score for breakable rules)
                - violations: list of failed rules
                - warnings: list of breakable rules that failed
        """
        # Gather all rules
        all_rules = list(self.standalone_rules)
        for group in self.rule_groups:
            if group.should_apply(context):
                all_rules.extend(group.rules)
        
        # Sort by priority if requested
        if respect_priority:
            all_rules.sort(key=lambda r: r.priority.value)
        
        # Test each rule
        violations = []
        warnings = []
        scores = []
        
        for rule in all_rules:
            if not rule.enabled:
                continue
            
            result = rule.test(song, context)
            
            if result.passed:
                scores.append(result.score)
            else:
                # Failed rule
                if rule.is_breakable():
                    warnings.append({
                        'rule': rule.name,
                        'message': result.message,
                        'score': result.score
                    })
                    scores.append(result.score)
                else:
                    # Unbreakable rule failed
                    violations.append({
                        'rule': rule.name,
                        'message': result.message,
                        'priority': rule.priority.name
                    })
                    
                    # Stop testing if critical unbreakable rule failed
                    if respect_priority and rule.is_critical():
                        break
        
        # Calculate overall score
        overall_score = sum(scores) / len(scores) if scores else 0.0
        
        # Overall pass = no unbreakable violations
        passed = len(violations) == 0
        
        return {
            'passed': passed,
            'score': overall_score,
            'violations': violations,
            'warnings': warnings,
            'total_rules_tested': len(all_rules)
        }
    
    def get_best_song(self, candidates: List, context) -> Optional[Any]:
        """
        Find best song from candidates based on rules.
        Uses scoring for breakable rules.
        
        Returns:
            Best song or None if all violate unbreakable rules
        """
        if not candidates:
            return None
        
        scored_candidates = []
        
        for song in candidates:
            test_context = {**context, 'song': song}
            result = self.test_song(song, test_context)
            
            if result['passed']:
                scored_candidates.append((song, result['score']))
        
        if not scored_candidates:
            return None  # All violated unbreakable rules
        
        # Return highest scoring song
        best = max(scored_candidates, key=lambda x: x[1])
        return best[0]
