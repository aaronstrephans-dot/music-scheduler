"""
Zetta automation system exporter.
Generates logs in Zetta's import format.
"""
from pathlib import Path
from typing import List
from datetime import datetime

from export_base import ScheduleExporter, ScheduleBlock, ScheduledSong, ScheduledElement


class ZettaExporter(ScheduleExporter):
    """
    Export to Zetta format.
    
    Format: Date,Time,Type,Cart,Length,Title,Artist
    Example: 02/17/2026,06:00:00,MUS,T1788,4:30,So So Good,Phil Wickham
    """
    
    def __init__(self, output_dir: Path, use_hhmmss: bool = False):
        super().__init__(output_dir)
        self.use_hhmmss = use_hhmmss  # Use HH:MM:SS for length instead of MM:SS
    
    def get_file_extension(self) -> str:
        return "csv"
    
    def _format_song_line(self, song: ScheduledSong) -> str:
        """Format a song as a Zetta log line"""
        date_str = song.datetime.strftime("%m/%d/%Y")
        time_str = song.datetime.strftime("%H:%M:%S")
        
        # Length format
        if self.use_hhmmss:
            length_str = song.format_length_hhmmss()
        else:
            length_str = song.format_length_mmss()
        
        # Clean fields (remove commas)
        title = song.title.replace(',', ' ')
        artist = song.artist.replace(',', ' ')
        cart = song.cart_id or song.song_id
        
        return f"{date_str},{time_str},MUS,{cart},{length_str},{title},{artist}"
    
    def _format_element_line(self, element: ScheduledElement) -> str:
        """Format a non-music element as a Zetta log line"""
        date_str = element.datetime.strftime("%m/%d/%Y")
        time_str = element.datetime.strftime("%H:%M:%S")
        
        # Map element types to Zetta types
        type_map = {
            "legal_id": "LID",
            "liner": "LIN",
            "sweeper": "SWP",
            "announcement": "ANN",
            "time_announcement": "TIM",
            "network_join": "NET"
        }
        
        zetta_type = type_map.get(element.element_type, "OTH")
        
        length_str = element.format_length_hhmmss()
        cart = element.cart_id or "UNKNOWN"
        desc = (element.description or element.element_type).replace(',', ' ')
        
        return f"{date_str},{time_str},{zetta_type},{cart},{length_str},{desc}"
    
    def export_block(self, block: ScheduleBlock, output_file: Path):
        """Export a single block"""
        with open(output_file, 'w') as f:
            # Header
            f.write("Date,Time,Type,Cart,Length,Title,Artist\n")
            
            # All items in chronological order
            items = block.get_all_items_chronological()
            
            for item in items:
                if isinstance(item, ScheduledSong):
                    f.write(self._format_song_line(item) + "\n")
                elif isinstance(item, ScheduledElement):
                    f.write(self._format_element_line(item) + "\n")
    
    def export_day(self, blocks: List[ScheduleBlock], output_file: Path):
        """Export a full day"""
        with open(output_file, 'w') as f:
            # Header
            f.write("Date,Time,Type,Cart,Length,Title,Artist\n")
            
            for block in blocks:
                items = block.get_all_items_chronological()
                
                for item in items:
                    if isinstance(item, ScheduledSong):
                        f.write(self._format_song_line(item) + "\n")
                    elif isinstance(item, ScheduledElement):
                        f.write(self._format_element_line(item) + "\n")
    
    def export_week(self, blocks: List[ScheduleBlock], output_file: Path):
        """Export a full week"""
        # For Zetta, week export is same as day export (one big file)
        self.export_day(blocks, output_file)
