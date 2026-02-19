"""
Week Grid data model.
Supports hour-based scheduling with flexible clock assignments.
"""
from dataclasses import dataclass, field
from datetime import datetime, date, timedelta
from typing import Dict, List, Optional, Union
from pathlib import Path
import json


@dataclass
class TimeSlot:
    """A single time slot in the schedule"""
    day: str  # "monday", "tuesday", etc.
    time: str  # "06:00", "14:30", etc.
    clock_name: str
    duration_minutes: int
    
    def get_datetime(self, week_start: date) -> datetime:
        """Convert to actual datetime given a week start date"""
        day_offset = {
            "monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3,
            "friday": 4, "saturday": 5, "sunday": 6
        }[self.day.lower()]
        
        hour, minute = map(int, self.time.split(':'))
        
        target_date = week_start + timedelta(days=day_offset)
        return datetime.combine(target_date, datetime.min.time()).replace(
            hour=hour, minute=minute
        )


@dataclass
class DateOverride:
    """Override specific clocks during a date range"""
    start_date: str  # "12-01" (MM-DD) or "2026-12-01" (YYYY-MM-DD)
    end_date: str    # "12-25" or "2026-12-25"
    replacements: Dict[str, str]  # {"MorningHour": "ChristmasMorningHour"}
    
    def applies_to(self, check_date: date) -> bool:
        """Check if this override applies to a given date"""
        # Parse dates
        start = self._parse_date(self.start_date, check_date.year)
        end = self._parse_date(self.end_date, check_date.year)
        
        # Handle year wraparound (e.g., 12-20 to 01-05)
        if end < start:
            return check_date >= start or check_date <= end
        else:
            return start <= check_date <= end
    
    def _parse_date(self, date_str: str, default_year: int) -> date:
        """Parse MM-DD or YYYY-MM-DD format"""
        parts = date_str.split('-')
        if len(parts) == 2:  # MM-DD
            return date(default_year, int(parts[0]), int(parts[1]))
        elif len(parts) == 3:  # YYYY-MM-DD
            return date(int(parts[0]), int(parts[1]), int(parts[2]))
        else:
            raise ValueError(f"Invalid date format: {date_str}")
    
    def apply(self, clock_name: str) -> str:
        """Apply override to clock name if applicable"""
        return self.replacements.get(clock_name, clock_name)


@dataclass
class WeekConfig:
    """Complete week configuration"""
    week_name: str
    schedule: Dict[str, Dict[str, Union[str, List[str], None]]]  # day -> hour -> clock(s)
    default_strategy: Optional[str] = None
    overrides: List[DateOverride] = field(default_factory=list)
    
    def get_slots_for_week(
        self,
        week_start: date,
        available_clocks: Dict[str, 'Clock']
    ) -> List[TimeSlot]:
        """
        Generate ordered list of time slots for the entire week.
        Validates clocks and expands half-hour pairs.
        """
        from models import Clock
        
        slots = []
        errors = []
        
        day_order = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
        
        for day in day_order:
            if day not in self.schedule:
                continue
            
            day_schedule = self.schedule[day]
            
            # Get hours in order
            hours = sorted(day_schedule.keys())
            
            for hour_time in hours:
                clock_spec = day_schedule[hour_time]
                
                # Skip empty hours
                if clock_spec is None:
                    continue
                
                # Calculate actual date for this day
                day_offset = day_order.index(day)
                slot_date = week_start + timedelta(days=day_offset)
                
                # Apply date overrides
                active_overrides = [o for o in self.overrides if o.applies_to(slot_date)]
                
                # Single clock (string)
                if isinstance(clock_spec, str):
                    clock_name = clock_spec
                    
                    # Apply overrides
                    for override in active_overrides:
                        clock_name = override.apply(clock_name)
                    
                    # Validate clock exists
                    if clock_name not in available_clocks:
                        errors.append(f"{day} {hour_time}: Clock '{clock_name}' not found")
                        continue
                    
                    clock = available_clocks[clock_name]
                    
                    # Validate duration
                    if clock.duration_minutes > 60:
                        errors.append(
                            f"{day} {hour_time}: Clock '{clock_name}' is {clock.duration_minutes} min "
                            f"(max 60 for single clock)"
                        )
                        continue
                    
                    slots.append(TimeSlot(
                        day=day,
                        time=hour_time,
                        clock_name=clock_name,
                        duration_minutes=clock.duration_minutes
                    ))
                
                # Two half-hour clocks (array)
                elif isinstance(clock_spec, list):
                    if len(clock_spec) != 2:
                        errors.append(
                            f"{day} {hour_time}: Must specify exactly 2 clocks for half-hour split, "
                            f"got {len(clock_spec)}"
                        )
                        continue
                    
                    clock_name_1, clock_name_2 = clock_spec
                    
                    # Apply overrides
                    for override in active_overrides:
                        clock_name_1 = override.apply(clock_name_1)
                        clock_name_2 = override.apply(clock_name_2)
                    
                    # Validate both clocks exist
                    if clock_name_1 not in available_clocks:
                        errors.append(f"{day} {hour_time}: Clock '{clock_name_1}' not found")
                        continue
                    if clock_name_2 not in available_clocks:
                        errors.append(f"{day} {hour_time}: Clock '{clock_name_2}' not found")
                        continue
                    
                    clock1 = available_clocks[clock_name_1]
                    clock2 = available_clocks[clock_name_2]
                    
                    # Validate both are 30 minutes
                    if clock1.duration_minutes != 30:
                        errors.append(
                            f"{day} {hour_time}: First clock '{clock_name_1}' must be 30 min, "
                            f"got {clock1.duration_minutes}"
                        )
                        continue
                    
                    if clock2.duration_minutes != 30:
                        errors.append(
                            f"{day} {hour_time}: Second clock '{clock_name_2}' must be 30 min, "
                            f"got {clock2.duration_minutes}"
                        )
                        continue
                    
                    # Add both slots
                    hour, minute = map(int, hour_time.split(':'))
                    
                    # First half-hour (e.g., 06:00)
                    slots.append(TimeSlot(
                        day=day,
                        time=hour_time,
                        clock_name=clock_name_1,
                        duration_minutes=30
                    ))
                    
                    # Second half-hour (e.g., 06:30)
                    second_time = f"{hour:02d}:{minute + 30:02d}"
                    slots.append(TimeSlot(
                        day=day,
                        time=second_time,
                        clock_name=clock_name_2,
                        duration_minutes=30
                    ))
                
                else:
                    errors.append(
                        f"{day} {hour_time}: Invalid clock specification "
                        f"(must be string, array of 2, or null)"
                    )
        
        if errors:
            raise ValueError("Week configuration errors:\n" + "\n".join(f"  - {e}" for e in errors))
        
        return slots
    
    @classmethod
    def load_from_file(cls, filepath: Path) -> 'WeekConfig':
        """Load week configuration from JSON file"""
        with open(filepath, 'r') as f:
            data = json.load(f)
        
        # Parse overrides
        overrides = []
        for override_data in data.get("overrides", []):
            overrides.append(DateOverride(
                start_date=override_data["start_date"],
                end_date=override_data["end_date"],
                replacements=override_data["replacements"]
            ))
        
        return cls(
            week_name=data["week_name"],
            schedule=data["schedule"],
            default_strategy=data.get("default_strategy"),
            overrides=overrides
        )
    
    def save_to_file(self, filepath: Path):
        """Save week configuration to JSON file"""
        data = {
            "week_name": self.week_name,
            "schedule": self.schedule,
            "overrides": [
                {
                    "start_date": o.start_date,
                    "end_date": o.end_date,
                    "replacements": o.replacements
                }
                for o in self.overrides
            ]
        }
        
        if self.default_strategy:
            data["default_strategy"] = self.default_strategy
        
        filepath.parent.mkdir(parents=True, exist_ok=True)
        with open(filepath, 'w') as f:
            json.dump(data, f, indent=2)
