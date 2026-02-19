"""
Generate Week - Week-long music schedule generator.
Clean architecture, rule-based scheduling, export integration.

Usage:
    python generate_week.py --week-config config/week_standard.json
    python generate_week.py --week-config config/week_standard.json --export zetta-log --export-scope day
"""
import argparse
import json
from pathlib import Path
from datetime import datetime, timedelta
from typing import Dict, List

from models import Song, Pool, Clock, Slot, SlotFallback
from pool_builder import build_pools_from_songs
from scheduler_engine import SchedulerEngine, SchedulingContext
from rule_loader import load_rule_engine_from_config
from rule_framework import RuleEngine
from strategy_v2 import load_strategy
from overnight_fill import apply_overnight_fill, load_copy_rules_from_config
from export_base import convert_schedule_results_to_blocks
from exporter_zetta_log import ZettaLOGExporter
from exporter_zetta import ZettaExporter
from exporter_wideorbit import WideOrbitExporter
from exporter_enco_csv import ENCOExporter, CSVExporter


EXPORTERS = {
    "zetta-log": ZettaLOGExporter,
    "zetta": ZettaExporter,
    "wideorbit": WideOrbitExporter,
    "enco": ENCOExporter,
    "csv": CSVExporter
}


def load_json(path: Path) -> dict:
    """Load JSON file"""
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)


def load_songs(path: Path) -> Dict[str, Song]:
    """Load songs from JSON"""
    raw = load_json(path)
    songs: Dict[str, Song] = {}

    for s in raw["songs"]:
        artists = s.get("artists") or [s.get("artist", "Unknown")]
        primary = s.get("primary_artist") or artists[0]

        songs[s["song_id"]] = Song(
            song_id=s["song_id"],
            title=s["title"],
            artists=artists,
            primary_artist=primary,
            length_seconds=int(s["length_seconds"]),
            intro_seconds=int(s.get("intro_seconds", 0)),
            active=bool(s.get("active", True)),
            rotation=s.get("rotation"),
            song_type=s.get("song_type"),
            tempo=s.get("tempo"),
            tags=s.get("tags", []),
            m1_metadata=s.get("m1_metadata")
        )
    return songs


def load_clocks(path: Path) -> Dict[str, Clock]:
    """Load clocks from JSON"""
    raw = load_json(path)
    clocks: Dict[str, Clock] = {}

    for c in raw.get("clocks", []):
        slots = []
        for s in c.get("slots", []):
            fallbacks = []
            for f in s.get("fallbacks", []):
                fallbacks.append(SlotFallback(
                    pool=f.get("pool"),
                    require_song_type=f.get("require_song_type")
                ))

            slots.append(Slot(
                slot_id=s["slot_id"],
                name=s["name"],
                primary_pool=s["primary_pool"],
                require_song_type=s.get("require_song_type"),
                terminal=s.get("terminal", False),
                fallbacks=fallbacks
            ))

        clocks[c["clock_id"]] = Clock(
            clock_id=c["clock_id"],
            name=c["name"],
            duration_minutes=c["duration_minutes"],
            slots=slots
        )

    return clocks


def load_week_config(path: Path) -> dict:
    """Load week configuration"""
    return load_json(path)


def print_progress(progress):
    """Print progress update"""
    print(f"  [{progress.percentage:5.1f}%] {progress.message}")


def main():
    """Main entry point"""
    parser = argparse.ArgumentParser(
        description="Generate week-long music schedule with rule-based AI"
    )

    parser.add_argument(
        "--week-config",
        required=True,
        help="Week configuration JSON file"
    )

    parser.add_argument(
        "--start-date",
        help="Start date (YYYY-MM-DD), defaults to next Sunday"
    )

    parser.add_argument(
        "--export",
        nargs="+",
        choices=list(EXPORTERS.keys()),
        help="Export formats"
    )

    parser.add_argument(
        "--export-dir",
        default="exports",
        help="Export directory (default: exports/)"
    )

    parser.add_argument(
        "--export-scope",
        choices=["day", "week"],
        default="day",
        help="Export scope: one file per day or single week file"
    )

    parser.add_argument(
        "--rules-config",
        help="Rules configuration JSON (optional, uses default if not specified)"
    )

    parser.add_argument(
        "--clear-history",
        action="store_true",
        help="Clear scheduling history before generating"
    )

    parser.add_argument(
        "--summary-only",
        action="store_true",
        help="Only show summary, no detailed output"
    )

    args = parser.parse_args()

    # Setup paths
    base = Path(__file__).parent
    week_config_path = Path(args.week_config)

    if not week_config_path.exists():
        print(f"❌ Week config not found: {week_config_path}")
        return 1

    print("="*70)
    print("MUSIC SCHEDULER - Week Generator")
    print("="*70)

    # Load configuration
    print("\n📋 Loading configuration...")
    week_config = load_week_config(week_config_path)

    # Determine start date
    if args.start_date:
        start_date = datetime.strptime(args.start_date, "%Y-%m-%d").date()
    else:
        # Default to next Sunday
        today = datetime.now().date()
        days_ahead = 6 - today.weekday()  # Sunday = 6
        if days_ahead <= 0:
            days_ahead += 7
        start_date = today + timedelta(days=days_ahead)

    print(f"   Week starting: {start_date.strftime('%A, %B %d, %Y')}")

    # Load songs
    songs_path = base / "config" / "songs.json"
    print(f"   Loading songs from {songs_path}...")
    songs = load_songs(songs_path)
    print(f"   ✅ Loaded {len(songs)} songs")

    # Build pools
    print("   Building pools...")
    pools = build_pools_from_songs(songs)
    print(f"   ✅ Built {len(pools)} pools")

    # Load clocks
    clocks_path = base / "config" / "clocks.json"
    print(f"   Loading clocks from {clocks_path}...")
    clocks = load_clocks(clocks_path)
    print(f"   ✅ Loaded {len(clocks)} clocks")

    # Load rules
    rule_engine = RuleEngine()
    
    if args.rules_config:
        rules_path = Path(args.rules_config)
        print(f"   Loading rules from {rules_path}...")
        rule_engine = load_rule_engine_from_config(rules_path)
        print(f"   ✅ Rules loaded")
    else:
        print("   Using default rules (basic constraints only)")
    
    # Load strategy if specified in week config
    strategy = None
    strategy_file = week_config.get("strategy_file")
    if strategy_file:
        strategy_path = base / strategy_file
        if strategy_path.exists():
            print(f"   Loading strategy from {strategy_path}...")
            strategy = load_strategy(strategy_path, rule_engine)
            print(f"   ✅ Strategy loaded: {strategy.name}")
        else:
            print(f"   ⚠️  Strategy file not found: {strategy_path}")
    elif not args.rules_config:
        # Load default strategy
        default_strategy_path = base / "config" / "strategy_standard.json"
        if default_strategy_path.exists():
            print(f"   Loading default strategy...")
            strategy = load_strategy(default_strategy_path, rule_engine)
            print(f"   ✅ Strategy loaded: {strategy.name}")

    # Validate week config
    time_slots = week_config.get("time_slots", [])
    if not time_slots:
        print("❌ No time slots in week config")
        return 1

    print(f"   ✅ Week configuration validated: {len(time_slots)} time slots")

    # Create scheduler engine
    print("\n🎵 Initializing scheduler engine...")
    scheduler = SchedulerEngine(
        songs=songs,
        pools=pools,
        rule_engine=rule_engine,
        strategy=strategy,
        progress_callback=print_progress if not args.summary_only else None
    )

    if args.clear_history:
        print("   Clearing history...")
        scheduler.clear_history()

    print("   ✅ Engine ready")

    # Generate schedule
    print(f"\n📅 Generating {len(time_slots)} time blocks...")

    all_results = []
    current_day = None

    for slot_config in time_slots:
        # Build datetime
        day_offset = slot_config["day"]
        slot_time = datetime.strptime(slot_config["time"], "%H:%M").time()
        slot_datetime = datetime.combine(
            start_date + timedelta(days=day_offset),
            slot_time
        )
        
        # Check if we've moved to a new day
        if current_day != day_offset:
            if current_day is not None:
                scheduler.start_new_day()
            current_day = day_offset

        # Get clock
        clock_name = slot_config["clock"]
        clock = clocks.get(clock_name)

        if not clock:
            print(f"⚠️  Clock not found: {clock_name}")
            continue

        # Schedule hour
        daypart = slot_config.get("daypart", "Unknown")
        results = scheduler.schedule_hour(clock, slot_datetime, daypart)
        all_results.extend(results)

    # Summary
    print("\n" + "="*70)
    print("SCHEDULING COMPLETE")
    print("="*70)

    successful = sum(1 for r in all_results if r.success)
    failed = len(all_results) - successful
    fill_rate = (successful / len(all_results) * 100) if all_results else 0

    print(f"Total slots: {len(all_results)}")
    print(f"Filled: {successful} ({fill_rate:.1f}%)")
    print(f"Unfilled: {failed}")

    # Convert to blocks for export
    print("\n📦 Converting to schedule blocks...")
    # Build time_slot objects for export
    from dataclasses import dataclass

    @dataclass
    class TimeSlot:
        day: int
        time: str
        clock: str
        daypart: str

    time_slot_objects = [
        TimeSlot(day=ts["day"], time=ts["time"], clock=ts["clock"], daypart=ts.get("daypart", ""))
        for ts in time_slots
    ]

    # Create results list in expected format
    results_list = []
    for i, result in enumerate(all_results):
        if result.success:
            time_slot = time_slot_objects[i % len(time_slot_objects)]
            results_list.append((
                time_slot,
                result.time,
                [result],
                {}
            ))

    blocks = convert_schedule_results_to_blocks(time_slot_objects, results_list)
    print(f"   ✅ {len(blocks)} blocks created")

    # Apply overnight fill if configured
    fill_config = week_config.get("fill_overnight", {})
    if fill_config.get("enabled"):
        print("\n🌙 Applying overnight fill...")
        copy_rules = load_copy_rules_from_config(week_config)
        if copy_rules:
            print(f"   Copy rules: {len(copy_rules)}")
            filled_blocks = apply_overnight_fill(blocks, copy_rules)
            print(f"   ✅ Total blocks after fill: {len(filled_blocks)}")
            blocks = filled_blocks

    # Export if requested
    if args.export:
        export_dir = Path(args.export_dir)
        export_dir.mkdir(parents=True, exist_ok=True)

        print(f"\n📤 Exporting to {export_dir}...")

        # Group by day if needed
        if args.export_scope == "day":
            blocks_by_day = {}
            for block in blocks:
                day_key = block.start_time.date()
                if day_key not in blocks_by_day:
                    blocks_by_day[day_key] = []
                blocks_by_day[day_key].append(block)

        for format_name in args.export:
            exporter_class = EXPORTERS[format_name]
            exporter = exporter_class(export_dir)

            print(f"\n{format_name.upper()}:")

            if args.export_scope == "week":
                filename = exporter.generate_filename(blocks[0].start_time, scope="week")
                output_file = export_dir / filename
                exporter.export_week(blocks, output_file)
                print(f"  ✅ {filename}")

            else:  # day
                for day_date in sorted(blocks_by_day.keys()):
                    day_blocks = blocks_by_day[day_date]
                    filename = exporter.generate_filename(
                        datetime.combine(day_date, datetime.min.time()),
                        scope="day"
                    )
                    output_file = export_dir / filename
                    exporter.export_day(day_blocks, output_file)
                    print(f"  ✅ {filename}")

    print("\n✅ Week generation complete!\n")
    return 0


if __name__ == "__main__":
    exit(main())
