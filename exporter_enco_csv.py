"""
ENCO DAD and generic CSV exporters.
"""
from pathlib import Path
from typing import List
from datetime import datetime

from export_base import ScheduleExporter, ScheduleBlock, ScheduledSong, ScheduledElement


class ENCOExporter(ScheduleExporter):
    """
    Export to ENCO DAD format.
    
    Format: Comma-delimited with date/time
    Date,Time,Type,Cart,Title,Artist,Length
    """
    
    def get_file_extension(self) -> str:
        return "csv"
    
    def _format_song_line(self, song: ScheduledSong) -> str:
        """Format a song as an ENCO log line"""
        date_str = song.datetime.strftime("%m/%d/%Y")
        time_str = song.datetime.strftime("%H:%M:%S")
        
        # Clean fields
        title = song.title.replace(',', ' ')
        artist = song.artist.replace(',', ' ')
        cart = song.cart_id or song.song_id
        
        return f"{date_str},{time_str},SONG,{cart},{title},{artist},{song.length_seconds}"
    
    def _format_element_line(self, element: ScheduledElement) -> str:
        """Format a non-music element"""
        date_str = element.datetime.strftime("%m/%d/%Y")
        time_str = element.datetime.strftime("%H:%M:%S")
        
        type_map = {
            "legal_id": "ID",
            "liner": "LINER",
            "sweeper": "SWEEP",
            "announcement": "ANNOUNCE",
            "time_announcement": "TIME",
            "network_join": "NETWORK"
        }
        
        enco_type = type_map.get(element.element_type, "OTHER")
        cart = element.cart_id or "UNKNOWN"
        desc = (element.description or element.element_type).replace(',', ' ')
        
        return f"{date_str},{time_str},{enco_type},{cart},{desc},,{element.duration}"
    
    def export_block(self, block: ScheduleBlock, output_file: Path):
        """Export a single block"""
        with open(output_file, 'w') as f:
            f.write("Date,Time,Type,Cart,Title,Artist,Length\n")
            
            items = block.get_all_items_chronological()
            
            for item in items:
                if isinstance(item, ScheduledSong):
                    f.write(self._format_song_line(item) + "\n")
                elif isinstance(item, ScheduledElement):
                    f.write(self._format_element_line(item) + "\n")
    
    def export_day(self, blocks: List[ScheduleBlock], output_file: Path):
        """Export a full day"""
        with open(output_file, 'w') as f:
            f.write("Date,Time,Type,Cart,Title,Artist,Length\n")
            
            for block in blocks:
                items = block.get_all_items_chronological()
                
                for item in items:
                    if isinstance(item, ScheduledSong):
                        f.write(self._format_song_line(item) + "\n")
                    elif isinstance(item, ScheduledElement):
                        f.write(self._format_element_line(item) + "\n")
    
    def export_week(self, blocks: List[ScheduleBlock], output_file: Path):
        """Export a full week"""
        self.export_day(blocks, output_file)


class CSVExporter(ScheduleExporter):
    """
    Generic CSV exporter with customizable columns.
    Most flexible format for review/editing.
    """
    
    def __init__(self, output_dir: Path, include_metadata: bool = True):
        super().__init__(output_dir)
        self.include_metadata = include_metadata
    
    def get_file_extension(self) -> str:
        return "csv"
    
    def _get_header(self) -> str:
        """Get CSV header row"""
        if self.include_metadata:
            return "Date,Time,Day,Hour,Type,ID,Cart,Title,Artist,Length_Sec,Length_MM:SS,Rotation,SongType,Clock"
        else:
            return "Date,Time,Type,ID,Title,Artist,Length"
    
    def _format_song_line(self, song: ScheduledSong, clock_name: str = "") -> str:
        """Format a song as a CSV line"""
        date_str = song.datetime.strftime("%Y-%m-%d")
        time_str = song.datetime.strftime("%H:%M:%S")
        day_str = song.datetime.strftime("%A")
        hour_str = song.datetime.strftime("%H:00")
        
        # Clean fields
        title = song.title.replace(',', ' ').replace('"', "'")
        artist = song.artist.replace(',', ' ').replace('"', "'")
        
        if self.include_metadata:
            return (f"{date_str},{time_str},{day_str},{hour_str},Music,"
                   f"{song.song_id},{song.cart_id or song.song_id},"
                   f"{title},{artist},"
                   f"{song.length_seconds},{song.format_length_mmss()},"
                   f"{song.rotation or ''},{song.song_type or ''},{clock_name}")
        else:
            return f"{date_str},{time_str},Music,{song.song_id},{title},{artist},{song.length_seconds}"
    
    def _format_element_line(self, element: ScheduledElement, clock_name: str = "") -> str:
        """Format a non-music element"""
        date_str = element.datetime.strftime("%Y-%m-%d")
        time_str = element.datetime.strftime("%H:%M:%S")
        day_str = element.datetime.strftime("%A")
        hour_str = element.datetime.strftime("%H:00")
        
        desc = (element.description or element.element_type).replace(',', ' ')
        
        if self.include_metadata:
            return (f"{date_str},{time_str},{day_str},{hour_str},{element.element_type},"
                   f",{element.cart_id or ''},"
                   f"{desc},,"
                   f"{element.duration},,,{clock_name}")
        else:
            return f"{date_str},{time_str},{element.element_type},{element.cart_id or ''},{desc},,{element.duration}"
    
    def export_block(self, block: ScheduleBlock, output_file: Path):
        """Export a single block"""
        with open(output_file, 'w') as f:
            f.write(self._get_header() + "\n")
            
            items = block.get_all_items_chronological()
            
            for item in items:
                if isinstance(item, ScheduledSong):
                    f.write(self._format_song_line(item, block.clock_name) + "\n")
                elif isinstance(item, ScheduledElement):
                    f.write(self._format_element_line(item, block.clock_name) + "\n")
    
    def export_day(self, blocks: List[ScheduleBlock], output_file: Path):
        """Export a full day"""
        with open(output_file, 'w') as f:
            f.write(self._get_header() + "\n")
            
            for block in blocks:
                items = block.get_all_items_chronological()
                
                for item in items:
                    if isinstance(item, ScheduledSong):
                        f.write(self._format_song_line(item, block.clock_name) + "\n")
                    elif isinstance(item, ScheduledElement):
                        f.write(self._format_element_line(item, block.clock_name) + "\n")
    
    def export_week(self, blocks: List[ScheduleBlock], output_file: Path):
        """Export a full week"""
        self.export_day(blocks, output_file)
