"""
Zetta .LOG format exporter.
Generates logs in Zetta's actual import format (fixed-width columns, no CSV).
"""
from pathlib import Path
from typing import List
from datetime import datetime

from export_base import ScheduleExporter, ScheduleBlock, ScheduledSong, ScheduledElement


class ZettaLOGExporter(ScheduleExporter):
    """
    Export to Zetta .LOG format.
    
    Format: Fixed-width columns, no headers
    CartID(16 chars) Time(HH:MM:SS) Title
    
    Example:
    C496            06:00:00Simple Pursuit
    P875            06:04:01Creator
    """
    
    def __init__(self, output_dir: Path, cart_width: int = 16):
        super().__init__(output_dir)
        self.cart_width = cart_width
    
    def get_file_extension(self) -> str:
        return "LOG"
    
    def _format_song_line(self, song: ScheduledSong) -> str:
        """Format a song as a Zetta .LOG line"""
        time_str = song.datetime.strftime("%H:%M:%S")
        cart = song.cart_id or song.song_id
        
        # Fixed-width cart column (left-aligned, padded with spaces)
        cart_padded = cart.ljust(self.cart_width)
        
        # Title only (no artist in this format)
        title = song.title
        
        return f"{cart_padded}{time_str}{title}"
    
    def _format_element_line(self, element: ScheduledElement) -> str:
        """Format a non-music element as a Zetta .LOG line"""
        time_str = element.datetime.strftime("%H:%M:%S")
        cart = element.cart_id or "UNKNOWN"
        
        # Fixed-width cart column
        cart_padded = cart.ljust(self.cart_width)
        
        # Description
        desc = element.description or element.element_type
        
        return f"{cart_padded}{time_str}{desc}"
    
    def export_block(self, block: ScheduleBlock, output_file: Path):
        """Export a single block"""
        with open(output_file, 'w') as f:
            # NO HEADER in .LOG format
            
            items = block.get_all_items_chronological()
            
            for item in items:
                if isinstance(item, ScheduledSong):
                    f.write(self._format_song_line(item) + "\n")
                elif isinstance(item, ScheduledElement):
                    f.write(self._format_element_line(item) + "\n")
    
    def export_day(self, blocks: List[ScheduleBlock], output_file: Path):
        """Export a full day"""
        with open(output_file, 'w') as f:
            for block in blocks:
                items = block.get_all_items_chronological()
                
                for item in items:
                    if isinstance(item, ScheduledSong):
                        f.write(self._format_song_line(item) + "\n")
                    elif isinstance(item, ScheduledElement):
                        f.write(self._format_element_line(item) + "\n")
    
    def export_week(self, blocks: List[ScheduleBlock], output_file: Path):
        """Export a full week"""
        # For .LOG format, typically one file per day
        # But we'll export as one continuous file
        self.export_day(blocks, output_file)
    
    def generate_filename(self, date: datetime, scope: str = "day") -> str:
        """
        Generate filename for Zetta .LOG export.
        Zetta typically uses format: YYYYMMDD.LOG
        """
        if scope == "day":
            return f"{date.strftime('%Y%m%d')}.LOG"
        elif scope == "week":
            return f"{date.strftime('%Y%m%d')}_week.LOG"
        else:
            return f"{date.strftime('%Y%m%d_%H%M')}.LOG"
