"""
Export framework for music schedules.
Base classes and common logic for exporting to various automation systems.
"""
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import List, Optional, Dict, Any
from abc import ABC, abstractmethod
from pathlib import Path


@dataclass
class ScheduledSong:
    """A song with its scheduled play time"""
    datetime: datetime
    song_id: str
    title: str
    artist: str
    length_seconds: int
    intro_seconds: int
    rotation: Optional[str] = None
    song_type: Optional[str] = None
    cart_id: Optional[str] = None  # For automation systems
    
    def get_end_time(self) -> datetime:
        """Get the time this song ends"""
        return self.datetime + timedelta(seconds=self.length_seconds)
    
    def format_length_mmss(self) -> str:
        """Format length as MM:SS"""
        mins = self.length_seconds // 60
        secs = self.length_seconds % 60
        return f"{mins}:{secs:02d}"
    
    def format_length_hhmmss(self) -> str:
        """Format length as HH:MM:SS"""
        hours = self.length_seconds // 3600
        mins = (self.length_seconds % 3600) // 60
        secs = self.length_seconds % 60
        return f"{hours:02d}:{mins:02d}:{secs:02d}"


@dataclass
class ScheduledElement:
    """A non-music element (liner, ID, etc.)"""
    datetime: datetime
    element_type: str  # "legal_id", "liner", "sweeper", "announcement", etc.
    duration: int      # Seconds
    cart_id: Optional[str] = None
    description: Optional[str] = None
    
    def get_end_time(self) -> datetime:
        """Get the time this element ends"""
        return self.datetime + timedelta(seconds=self.duration)
    
    def format_length_hhmmss(self) -> str:
        """Format length as HH:MM:SS"""
        hours = self.duration // 3600
        mins = (self.duration % 3600) // 60
        secs = self.duration % 60
        return f"{hours:02d}:{mins:02d}:{secs:02d}"


@dataclass
class ScheduleBlock:
    """A complete scheduled block (hour or half-hour)"""
    start_time: datetime
    duration_minutes: int
    clock_name: str
    songs: List[ScheduledSong]
    elements: List[ScheduledElement]
    
    def get_all_items_chronological(self) -> List:
        """Get all songs and elements in chronological order"""
        items = list(self.songs) + list(self.elements)
        items.sort(key=lambda x: x.datetime)
        return items
    
    def get_total_music_time(self) -> int:
        """Get total music time in seconds"""
        return sum(song.length_seconds for song in self.songs)
    
    def get_total_element_time(self) -> int:
        """Get total element time in seconds"""
        return sum(elem.duration for elem in self.elements)


class ScheduleExporter(ABC):
    """Base class for all schedule exporters"""
    
    def __init__(self, output_dir: Path):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
    
    @abstractmethod
    def export_block(self, block: ScheduleBlock, output_file: Path):
        """Export a single block to file"""
        pass
    
    @abstractmethod
    def export_day(self, blocks: List[ScheduleBlock], output_file: Path):
        """Export a full day to file"""
        pass
    
    @abstractmethod
    def export_week(self, blocks: List[ScheduleBlock], output_file: Path):
        """Export a full week to file"""
        pass
    
    @abstractmethod
    def get_file_extension(self) -> str:
        """Get the file extension for this format (e.g., 'csv', 'txt')"""
        pass
    
    def generate_filename(self, date: datetime, scope: str = "day") -> str:
        """
        Generate filename for export.
        scope: "day", "week", "block"
        """
        ext = self.get_file_extension()
        
        if scope == "day":
            return f"schedule_{date.strftime('%Y%m%d')}.{ext}"
        elif scope == "week":
            return f"schedule_week_{date.strftime('%Y%m%d')}.{ext}"
        elif scope == "block":
            return f"schedule_{date.strftime('%Y%m%d_%H%M')}.{ext}"
        else:
            return f"schedule.{ext}"


def convert_schedule_results_to_blocks(
    time_slots,
    results_list,
    hard_stops: Optional[Dict[str, List]] = None
) -> List[ScheduleBlock]:
    """
    Convert raw scheduling results into ScheduleBlock objects.
    
    Args:
        time_slots: List of TimeSlot objects
        results_list: List of (time_slot, start_time, results, context) tuples
        hard_stops: Optional dict mapping clock_name -> list of HardStop objects
    
    Returns:
        List of ScheduleBlock objects
    """
    from week_model import TimeSlot
    from models import PickExplanation
    
    blocks = []
    
    for time_slot, start_time, results, context in results_list:
        songs = []
        current_time = start_time
        
        # Convert PickExplanation results to ScheduledSong objects
        for result in results:
            if result.chosen_song:
                song = result.chosen_song
                
                # Get cart ID from m1_metadata if available, otherwise use song_id
                cart_id = song.song_id
                if hasattr(song, 'm1_metadata') and song.m1_metadata:
                    cart_id = song.m1_metadata.get('cart', song.song_id)
                
                scheduled_song = ScheduledSong(
                    datetime=current_time,
                    song_id=song.song_id,
                    title=song.title,
                    artist=song.primary_artist,
                    length_seconds=song.length_seconds,
                    intro_seconds=song.intro_seconds,
                    rotation=song.rotation,
                    song_type=song.song_type,
                    cart_id=cart_id
                )
                
                songs.append(scheduled_song)
                current_time = current_time + timedelta(seconds=song.length_seconds)
        
        # Add hard stops if provided
        elements = []
        if hard_stops and time_slot.clock_name in hard_stops:
            for hs in hard_stops[time_slot.clock_name]:
                elem_time = start_time + timedelta(minutes=hs.time_offset)
                elements.append(ScheduledElement(
                    datetime=elem_time,
                    element_type=hs.element_type,
                    duration=hs.duration,
                    cart_id=hs.cart_id,
                    description=hs.description
                ))
        
        block = ScheduleBlock(
            start_time=start_time,
            duration_minutes=time_slot.duration_minutes,
            clock_name=time_slot.clock_name,
            songs=songs,
            elements=elements
        )
        
        blocks.append(block)
    
    return blocks
