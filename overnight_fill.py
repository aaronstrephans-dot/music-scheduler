"""
Overnight filler - copies daytime hours to fill overnight slots.
Integrated into week scheduling workflow.
"""
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import List, Dict, Optional
from copy import deepcopy


@dataclass
class CopyRule:
    """Rule for copying scheduled hours"""
    target_start: str      # "22:00" or "00:00"
    target_end: str        # "23:59" or "05:59"
    source_start: str      # "10:00" or "12:00"
    source_end: str        # "11:59" or "17:59"
    source_day: str        # "same" or "previous"
    
    def parse_time(self, time_str: str) -> tuple[int, int]:
        """Parse HH:MM to (hour, minute)"""
        parts = time_str.split(':')
        return int(parts[0]), int(parts[1])
    
    def get_source_range(self) -> tuple[int, int, int, int]:
        """Get source hour/minute range"""
        start_h, start_m = self.parse_time(self.source_start)
        end_h, end_m = self.parse_time(self.source_end)
        return start_h, start_m, end_h, end_m
    
    def get_target_range(self) -> tuple[int, int, int, int]:
        """Get target hour/minute range"""
        start_h, start_m = self.parse_time(self.target_start)
        end_h, end_m = self.parse_time(self.target_end)
        return start_h, start_m, end_h, end_m


def time_in_range(dt: datetime, start_h: int, start_m: int, end_h: int, end_m: int) -> bool:
    """Check if datetime falls within time range"""
    time_minutes = dt.hour * 60 + dt.minute
    start_minutes = start_h * 60 + start_m
    end_minutes = end_h * 60 + end_m
    
    # Handle overnight range (e.g., 22:00 to 05:59 next day)
    if end_minutes < start_minutes:
        return time_minutes >= start_minutes or time_minutes <= end_minutes
    else:
        return start_minutes <= time_minutes <= end_minutes


def apply_overnight_fill(
    scheduled_blocks: List,
    copy_rules: List[CopyRule],
    start_date: datetime
) -> List:
    """
    Apply overnight fill rules to scheduled blocks.
    
    Args:
        scheduled_blocks: List of ScheduleBlock objects from scheduler
        copy_rules: List of CopyRule objects defining what to copy
        start_date: Week start date
    
    Returns:
        Extended list of ScheduleBlock objects including filled overnight hours
    """
    from export_base import ScheduleBlock, ScheduledSong, ScheduledElement
    
    # Group blocks by date
    blocks_by_date = {}
    for block in scheduled_blocks:
        block_date = block.start_time.date()
        if block_date not in blocks_by_date:
            blocks_by_date[block_date] = []
        blocks_by_date[block_date].append(block)
    
    # Result list
    filled_blocks = []
    
    # Sort dates
    sorted_dates = sorted(blocks_by_date.keys())
    
    for date_idx, current_date in enumerate(sorted_dates):
        day_blocks = blocks_by_date[current_date]
        
        # Add all originally scheduled blocks for this day
        filled_blocks.extend(day_blocks)
        
        # Apply each copy rule
        for rule in copy_rules:
            source_start_h, source_start_m, source_end_h, source_end_m = rule.get_source_range()
            target_start_h, target_start_m, target_end_h, target_end_m = rule.get_target_range()
            
            # Determine source date
            if rule.source_day == "same":
                source_date = current_date
            elif rule.source_day == "previous":
                if date_idx > 0:
                    source_date = sorted_dates[date_idx - 1]
                else:
                    # First day - can't copy from previous
                    continue
            else:
                continue
            
            # Get source blocks
            if source_date not in blocks_by_date:
                continue
            
            source_blocks = blocks_by_date[source_date]
            
            # Find blocks in source time range
            blocks_to_copy = []
            for block in source_blocks:
                if time_in_range(block.start_time, source_start_h, source_start_m, source_end_h, source_end_m):
                    blocks_to_copy.append(block)
            
            # Copy blocks to target time range
            for source_block in blocks_to_copy:
                # Calculate time offset
                source_time = source_block.start_time
                source_minutes = source_time.hour * 60 + source_time.minute
                
                # Determine target time
                # For "same day" rules: just shift hours
                # For "previous day" rules: shift to next day + adjust hours
                if rule.source_day == "same":
                    # Same day: 10:00 → 22:00 (shift +12 hours)
                    time_diff_minutes = (target_start_h * 60 + target_start_m) - (source_start_h * 60 + source_start_m)
                    target_time = source_time + timedelta(minutes=time_diff_minutes)
                else:
                    # Previous day: day+1 12:00 → day+1 00:00 (shift +12 hours to next day's midnight range)
                    # Source is previous day, target is current day
                    offset_minutes = source_minutes - (source_start_h * 60 + source_start_m)
                    target_minutes = (target_start_h * 60 + target_start_m) + offset_minutes
                    
                    target_time = datetime.combine(current_date, datetime.min.time())
                    target_time += timedelta(minutes=target_minutes)
                
                # Create copied block
                copied_block = ScheduleBlock(
                    start_time=target_time,
                    duration_minutes=source_block.duration_minutes,
                    clock_name=source_block.clock_name,
                    songs=[],
                    elements=[]
                )
                
                # Copy songs with adjusted timestamps
                time_offset = target_time - source_block.start_time
                
                for song in source_block.songs:
                    copied_song = ScheduledSong(
                        datetime=song.datetime + time_offset,
                        song_id=song.song_id,
                        title=song.title,
                        artist=song.artist,
                        length_seconds=song.length_seconds,
                        intro_seconds=song.intro_seconds,
                        rotation=song.rotation,
                        song_type=song.song_type,
                        cart_id=song.cart_id
                    )
                    copied_block.songs.append(copied_song)
                
                # Copy elements with adjusted timestamps
                for elem in source_block.elements:
                    copied_elem = ScheduledElement(
                        datetime=elem.datetime + time_offset,
                        element_type=elem.element_type,
                        duration=elem.duration,
                        cart_id=elem.cart_id,
                        description=elem.description
                    )
                    copied_block.elements.append(copied_elem)
                
                filled_blocks.append(copied_block)
    
    # Sort all blocks chronologically
    filled_blocks.sort(key=lambda b: b.start_time)
    
    return filled_blocks


def load_copy_rules_from_config(config_dict: dict) -> List[CopyRule]:
    """Load copy rules from week config dictionary"""
    rules = []
    
    fill_config = config_dict.get("fill_overnight", {})
    if not fill_config.get("enabled", False):
        return rules
    
    for rule_data in fill_config.get("copy_rules", []):
        rules.append(CopyRule(
            target_start=rule_data["target"].split("-")[0],
            target_end=rule_data["target"].split("-")[1],
            source_start=rule_data["source"].split("-")[0],
            source_end=rule_data["source"].split("-")[1],
            source_day=rule_data.get("source_day", "same")
        ))
    
    return rules
