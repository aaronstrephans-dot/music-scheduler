"""
Export CLI - Export generated schedules to various automation formats.
Can be run standalone or integrated into generate_week.py
"""
import argparse
import json
from pathlib import Path
from datetime import datetime

from export_base import convert_schedule_results_to_blocks
from exporter_zetta import ZettaExporter
from exporter_wideorbit import WideOrbitExporter
from exporter_enco_csv import ENCOExporter, CSVExporter


EXPORTERS = {
    "zetta": ZettaExporter,
    "wideorbit": WideOrbitExporter,
    "enco": ENCOExporter,
    "csv": CSVExporter
}


def export_schedule_from_results(
    results_list,
    time_slots,
    output_dir: Path,
    formats: list[str],
    scope: str = "week"
):
    """
    Export schedule results to various formats.
    
    Args:
        results_list: List of (time_slot, start_time, results, context) tuples
        time_slots: List of TimeSlot objects
        output_dir: Where to save exports
        formats: List of format names ("zetta", "wideorbit", etc.)
        scope: "day" or "week"
    """
    # Convert to ScheduleBlock objects
    blocks = convert_schedule_results_to_blocks(time_slots, results_list)
    
    if not blocks:
        print("⚠️  No blocks to export")
        return
    
    # Group by day if doing day exports
    if scope == "day":
        blocks_by_day = {}
        for block in blocks:
            day_key = block.start_time.date()
            if day_key not in blocks_by_day:
                blocks_by_day[day_key] = []
            blocks_by_day[day_key].append(block)
    
    # Export each format
    for format_name in formats:
        if format_name not in EXPORTERS:
            print(f"⚠️  Unknown format: {format_name}")
            continue
        
        exporter_class = EXPORTERS[format_name]
        exporter = exporter_class(output_dir)
        
        print(f"\nExporting {format_name.upper()} format...")
        
        if scope == "week":
            # Single week file
            filename = exporter.generate_filename(blocks[0].start_time, scope="week")
            output_file = output_dir / filename
            exporter.export_week(blocks, output_file)
            print(f"  ✅ {output_file}")
        
        elif scope == "day":
            # One file per day
            for day_date, day_blocks in blocks_by_day.items():
                filename = exporter.generate_filename(
                    datetime.combine(day_date, datetime.min.time()),
                    scope="day"
                )
                output_file = output_dir / filename
                exporter.export_day(day_blocks, output_file)
                print(f"  ✅ {output_file}")


def main():
    """CLI for exporting schedules"""
    parser = argparse.ArgumentParser(
        description="Export music schedules to automation system formats"
    )
    
    parser.add_argument(
        "--input",
        required=True,
        help="Input schedule data (from generate_week.py --save-data)"
    )
    
    parser.add_argument(
        "--output",
        required=True,
        help="Output directory for exported logs"
    )
    
    parser.add_argument(
        "--formats",
        nargs="+",
        default=["csv"],
        choices=["zetta", "wideorbit", "enco", "csv"],
        help="Export formats (default: csv)"
    )
    
    parser.add_argument(
        "--scope",
        choices=["day", "week"],
        default="week",
        help="Export scope: one file per day or one file for whole week"
    )
    
    args = parser.parse_args()
    
    # Load schedule data
    input_path = Path(args.input)
    if not input_path.exists():
        print(f"❌ Input file not found: {input_path}")
        return 1
    
    print(f"Loading schedule data from {input_path}...")
    
    try:
        with open(input_path, 'r') as f:
            data = json.load(f)
        
        # TODO: Need to implement --save-data in generate_week.py
        # For now, this is a placeholder
        print("❌ Schedule data format not yet implemented")
        print("   Run generate_week.py with --export flag instead")
        return 1
        
    except Exception as e:
        print(f"❌ Error loading data: {e}")
        return 1
    
    # Export
    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)
    
    print(f"\nExporting to: {output_dir}")
    print(f"Formats: {', '.join(args.formats)}")
    print(f"Scope: {args.scope}")
    
    # TODO: Call export_schedule_from_results with loaded data
    
    return 0


if __name__ == "__main__":
    exit(main())
