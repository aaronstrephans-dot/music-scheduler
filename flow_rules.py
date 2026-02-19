"""
Flow control rules - Gender, sound code, mood, energy, ending type.
Controls music flow and transitions between songs.
"""
from typing import Optional, List, Dict
from rule_framework import BaseRule, RuleResult, RuleType, RulePriority


class GenderSeparationRule(BaseRule):
    """
    Gender separation - prevent too many male/female vocals in a row.
    Industry standard feature.
    """
    
    def __init__(
        self,
        max_in_a_row: int = 3,
        separation_minutes: Optional[int] = None,
        **kwargs
    ):
        super().__init__(
            name="Gender Separation",
            priority=RulePriority.HIGH,
            **kwargs
        )
        self.max_in_a_row = max_in_a_row
        self.separation_minutes = separation_minutes
    
    def get_gender(self, song) -> Optional[str]:
        """Get gender from song"""
        if hasattr(song, 'gender'):
            return song.gender
        
        # Check tags
        if hasattr(song, 'tags'):
            if 'Male' in song.tags:
                return 'Male'
            if 'Female' in song.tags:
                return 'Female'
        
        return None
    
    def test(self, song, context) -> RuleResult:
        """Test gender separation"""
        gender = self.get_gender(song)
        if not gender:
            return RuleResult(True, 1.0)  # No gender data
        
        history = context.get('recent_songs', [])
        
        # Check back-to-back limit
        consecutive_count = 0
        for hist_song in reversed(history):
            hist_gender = self.get_gender(hist_song)
            if hist_gender == gender:
                consecutive_count += 1
            else:
                break
        
        if consecutive_count >= self.max_in_a_row:
            return RuleResult(
                False,
                0.3,
                f"{consecutive_count} {gender} songs in a row (max {self.max_in_a_row})"
            )
        
        # Check time-based separation if configured
        if self.separation_minutes:
            current_time = context.get('current_time')
            if current_time:
                from datetime import timedelta
                cutoff = current_time - timedelta(minutes=self.separation_minutes)
                
                for hist_entry in history:
                    if getattr(hist_entry, 'datetime', None) and hist_entry.datetime >= cutoff:
                        if self.get_gender(hist_entry) == gender:
                            time_diff = (current_time - hist_entry.datetime).total_seconds() / 60
                            return RuleResult(
                                False,
                                time_diff / self.separation_minutes,
                                f"{gender} vocal {int(time_diff)}min ago (need {self.separation_minutes}min)"
                            )
                            break
        
        return RuleResult(True, 1.0)


class SoundCodeSeparationRule(BaseRule):
    """
    Sound code separation - prevent similar styles/textures too close.
    Music1/PowerGold feature for controlling flow.
    """
    
    def __init__(
        self,
        max_in_a_row: int = 2,
        codes_to_separate: Optional[List[str]] = None,
        **kwargs
    ):
        super().__init__(
            name="Sound Code Separation",
            priority=RulePriority.MEDIUM,
            **kwargs
        )
        self.max_in_a_row = max_in_a_row
        self.codes_to_separate = codes_to_separate or []
    
    def get_sound_code(self, song) -> Optional[str]:
        """Get sound code from song"""
        if hasattr(song, 'sound_code'):
            return song.sound_code
        
        # Check tags for sound code
        if hasattr(song, 'tags'):
            for tag in song.tags:
                if tag.startswith('sound:'):
                    return tag.replace('sound:', '')
        
        return None
    
    def test(self, song, context) -> RuleResult:
        """Test sound code separation"""
        code = self.get_sound_code(song)
        if not code:
            return RuleResult(True, 1.0)
        
        # Only check codes in separation list (if specified)
        if self.codes_to_separate and code not in self.codes_to_separate:
            return RuleResult(True, 1.0)
        
        history = context.get('recent_songs', [])
        
        # Count consecutive same code
        consecutive_count = 0
        for hist_song in reversed(history):
            hist_code = self.get_sound_code(hist_song)
            if hist_code == code:
                consecutive_count += 1
            else:
                break
        
        if consecutive_count >= self.max_in_a_row:
            return RuleResult(
                False,
                0.4,
                f"{consecutive_count} songs with sound code '{code}' in a row (max {self.max_in_a_row})"
            )
        
        return RuleResult(True, 1.0)


class MoodFlowRule(BaseRule):
    """
    Mood flow control - prevent mood whiplash.
    1-5 scale: 1=very sad, 5=very happy
    """
    
    def __init__(
        self,
        max_mood_jump: int = 3,  # Max allowed mood change
        **kwargs
    ):
        super().__init__(
            name="Mood Flow",
            priority=RulePriority.MEDIUM,
            rule_type=RuleType.BREAKABLE,
            **kwargs
        )
        self.max_mood_jump = max_mood_jump
    
    def get_mood(self, song) -> Optional[int]:
        """Get mood level (1-5)"""
        if hasattr(song, 'mood'):
            return song.mood
        return None
    
    def test(self, song, context) -> RuleResult:
        """Test mood flow"""
        current_mood = self.get_mood(song)
        if current_mood is None:
            return RuleResult(True, 1.0)
        
        history = context.get('recent_songs', [])
        if not history:
            return RuleResult(True, 1.0)
        
        # Check previous song's mood
        prev_mood = self.get_mood(history[-1])
        if prev_mood is None:
            return RuleResult(True, 1.0)
        
        mood_jump = abs(current_mood - prev_mood)
        
        if mood_jump > self.max_mood_jump:
            # Too big of a jump
            score = 1.0 - (mood_jump - self.max_mood_jump) / 5.0
            return RuleResult(
                False,
                max(0.0, score),
                f"Mood jump too large: {prev_mood} → {current_mood} (max jump: {self.max_mood_jump})"
            )
        
        return RuleResult(True, 1.0)


class EnergyFlowRule(BaseRule):
    """
    Energy flow control - maintain appropriate energy levels.
    1-5 scale: 1=very low, 5=very high
    Separate from tempo.
    """
    
    def __init__(
        self,
        max_energy_drop: int = 3,  # Max allowed energy decrease
        **kwargs
    ):
        super().__init__(
            name="Energy Flow",
            priority=RulePriority.MEDIUM,
            rule_type=RuleType.BREAKABLE,
            **kwargs
        )
        self.max_energy_drop = max_energy_drop
    
    def get_energy(self, song) -> Optional[int]:
        """Get energy level (1-5)"""
        if hasattr(song, 'energy'):
            return song.energy
        return None
    
    def test(self, song, context) -> RuleResult:
        """Test energy flow"""
        current_energy = self.get_energy(song)
        if current_energy is None:
            return RuleResult(True, 1.0)
        
        history = context.get('recent_songs', [])
        if not history:
            return RuleResult(True, 1.0)
        
        # Check previous song's energy
        prev_energy = self.get_energy(history[-1])
        if prev_energy is None:
            return RuleResult(True, 1.0)
        
        energy_change = prev_energy - current_energy  # Positive = drop
        
        if energy_change > self.max_energy_drop:
            # Energy dropped too much
            score = 1.0 - (energy_change - self.max_energy_drop) / 5.0
            return RuleResult(
                False,
                max(0.0, score),
                f"Energy drop too steep: {prev_energy} → {current_energy}"
            )
        
        return RuleResult(True, 1.0)


class EndingTypeRule(BaseRule):
    """
    Ending type segue - prevent awkward transitions.
    Example: Cold ending followed immediately by song with no intro = jarring
    """
    
    def __init__(self, **kwargs):
        super().__init__(
            name="Ending Type Segue",
            priority=RulePriority.LOW,
            rule_type=RuleType.BREAKABLE,
            **kwargs
        )
    
    def get_ending(self, song) -> Optional[str]:
        """Get ending type: 'cold' or 'fade'"""
        if hasattr(song, 'ending'):
            return song.ending
        
        # Check tags
        if hasattr(song, 'tags'):
            if 'Cold' in song.tags or 'cold_ending' in song.tags:
                return 'cold'
            if 'Fade' in song.tags or 'fade_ending' in song.tags:
                return 'fade'
        
        return None
    
    def has_intro(self, song) -> bool:
        """Check if song has significant intro"""
        if hasattr(song, 'intro_seconds'):
            return song.intro_seconds > 3  # More than 3 seconds of intro
        return True  # Assume intro if unknown
    
    def test(self, song, context) -> RuleResult:
        """Test ending type transition"""
        history = context.get('recent_songs', [])
        if not history:
            return RuleResult(True, 1.0)
        
        prev_song = history[-1]
        prev_ending = self.get_ending(prev_song)
        
        # Check cold ending → no intro (awkward)
        if prev_ending == 'cold' and not self.has_intro(song):
            return RuleResult(
                False,
                0.5,
                "Cold ending followed by song with no intro (awkward transition)"
            )
        
        return RuleResult(True, 1.0)


class BPMMatchingRule(BaseRule):
    """
    BPM (beats per minute) matching - for beat-matching transitions.
    Advanced feature for formats that crossfade.
    """
    
    def __init__(
        self,
        max_bpm_difference: int = 20,
        **kwargs
    ):
        super().__init__(
            name="BPM Matching",
            priority=RulePriority.LOW,
            rule_type=RuleType.BREAKABLE,
            **kwargs
        )
        self.max_bpm_difference = max_bpm_difference
    
    def get_bpm(self, song) -> Optional[int]:
        """Get BPM from song"""
        if hasattr(song, 'bpm'):
            return song.bpm
        return None
    
    def test(self, song, context) -> RuleResult:
        """Test BPM compatibility"""
        current_bpm = self.get_bpm(song)
        if current_bpm is None:
            return RuleResult(True, 1.0)
        
        history = context.get('recent_songs', [])
        if not history:
            return RuleResult(True, 1.0)
        
        prev_bpm = self.get_bpm(history[-1])
        if prev_bpm is None:
            return RuleResult(True, 1.0)
        
        bpm_diff = abs(current_bpm - prev_bpm)
        
        if bpm_diff > self.max_bpm_difference:
            score = 1.0 - (bpm_diff - self.max_bpm_difference) / 50.0
            return RuleResult(
                False,
                max(0.0, score),
                f"BPM mismatch: {prev_bpm} → {current_bpm} (diff: {bpm_diff})"
            )
        
        return RuleResult(True, 1.0)
