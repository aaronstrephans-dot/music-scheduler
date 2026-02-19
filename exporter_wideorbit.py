"""
WideOrbit automation system exporter.
Generates logs in WideOrbit/Selector SS32 format.
"""
from pathlib import Path
from typing import List
from datetime import datetime

from export_base import ScheduleExporter, ScheduleBlock, ScheduledSong, ScheduledElement


class WideOrbitExporter(ScheduleExporter):
    """
    Export to WideOrbit/Selector SS32 format.
    
    Format: Tab-delimited with specific column order
    Time(HHMMSS) Type Cart Title Artist Length
    """
    
    def get_file_extension(self) -> str:
        return "txt"
    
    def _format_song_line(self, song: ScheduledSong) -> str:
        """Format a song as a WideOrbit log line"""
        time_str = song.datetime.strftime("%H%M%S")
        
        # Clean fields (remove tabs)
        title = song.title.replace('\t', ' ')
        artist = song.artist.replace('\t', ' ')
        cart = song.cart_id or song.song_id
        
        # Length in seconds
        length_str = str(song.length_seconds)
        
        return f"{time_str}\tM\t{cart}\t{title}\t{artist}\t{length_str}"
    
    def _format_element_line(self, element: ScheduledElement) -> str:
        """Format a non-music element as a WideOrbit log line"""
        time_str = element.datetime.strftime("%H%M%S")
        
        # Map element types to WideOrbit types
        type_map = {
            "legal_id": "I",
            "liner": "L",
            "sweeper": "S",
            "announcement": "A",
            "time_announcement": "T",
            "network_join": "N"
        }
        
        wo_type = type_map.get(element.element_type, "O")
        
        cart = element.cart_id or "UNKNOWN"
        desc = (element.description or element.element_type).replace('\t', ' ')
        
        return f"{time_str}\t{wo_type}\t{cart}\t{desc}\t\t{element.duration}"
    
    def export_block(self, block: ScheduleBlock, output_file: Path):
        """Export a single block"""
        with open(output_file, 'w') as f:
            # Header
            f.write("Time\tType\tCart\tTitle\tArtist\tLength\n")
            
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
            f.write("Time\tType\tCart\tTitle\tArtist\tLength\n")
            
            for block in blocks:
                items = block.get_all_items_chronological()
                
                for item in items:
                    if isinstance(item, ScheduledSong):
                        f.write(self._format_song_line(item) + "\n")
                    elif isinstance(item, ScheduledElement):
                        f.write(self._format_element_line(item) + "\n")
    
    def export_week(self, blocks: List[ScheduleBlock], output_file: Path):
        """Export a full week - WideOrbit typically uses daily files"""
        self.export_day(blocks, output_file)
