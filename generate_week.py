"""
Week scheduler - Generate complete weekly schedules.
"""
import argparse
import json
from pathlib import Path
from datetime import datetime, date, timedelta

from week_model import WeekConfig, TimeSlot
from engine_v3 import EngineConfig, generate_block
from history import HistoryTracker
from constraints import SchedulingContext
from strategy import load_strategy_from_file
from models import Clock, Pool, Slot, SlotFallback, Song


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def load_songs(path: Path) -> dict[str, Song]:
    raw = load_json(path)
    songs: dict[str, Song] = {}

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


def load_pools(path: Path) -> dict[str, Pool]:
    raw = load_json(path)
    pools: dict[str, Pool] = {}

    for p in raw["pools"]:
        pools[p["name"]] = Pool(
            pool_id=p["pool_id"],
            name=p["name"],
            include=p.get("include", {}),
            exclude=p.get("exclude", {}),
            include_pools=p.get("include_pools", []),
            exclude_pools=p.get("exclude_pools", []),
            active=bool(p.get("active", True)),
        )
    return pools


def load_clocks(path: Path) -> dict[str, Clock]:
    raw = load_json(path)
    clocks: dict[str, Clock] = {}

    for c in raw["clocks"]:
        slots: list[Slot] = []
        for sl in c["slots"]:
            fallbacks = [
                SlotFallback(pool=fb.get("pool"), require_song_type=fb.get("require_song_type"))
                for fb in sl.get("fallbacks", [])
            ]
            slots.append(
                Slot(
                    slot_id=sl["slot_id"],
                    name=sl["name"],
                    primary_pool=sl["primary_pool"],
                    require_song_type=sl.get("require_song_type"),
                    terminal=bool(sl.get("terminal", False)),
                    fallbacks=fallbacks,
                )
            )

        clocks[c["name"]] = Clock(
            clock_id=c["clock_id"],
            name=c["name"],
            duration_minutes=int(c["duration_minutes"]),
            slots=slots,
        )
    return clocks


def format_time_hhmm(dt: datetime) -> str:
    """Format datetime as HH:MM AM/PM"""
    return dt.strftime("%I:%M %p").lstrip('0')


def format_day_date(dt: datetime) -> str:
    """Format as 'Monday, Feb 17'"""
    return dt.strftime("%A, %b %d")


def format_duration(seconds: int) -> str:
    """Format seconds as M:SS"""
    mins = seconds // 60
    secs = seconds % 60
    return f"{mins}:{secs:02d}"


def main():
    parser = argparse.ArgumentParser(description="Generate complete weekly schedule")
    parser.add_argument("--week-config", required=True, help="Week configuration JSON file")
    parser.add_argument(
        "--start-date",
        help="Week start date (YYYY-MM-DD, default: next Monday)"
    )
    parser.add_argument(
        "--strategy",
        help="Strategy config file (overrides week's default strategy)"
    )
    parser.add_argument(
        "--clear-history",
        action="store_true",
        help="Clear existing history before starting"
    )
    parser.add_argument(
        "--output",
        help="Output file for detailed log (optional)"
    )
    parser.add_argument(
        "--summary-only",
        action="store_true",
        help="Only show summary, not full song lists"
    )
    parser.add_argument(
        "--export",
        nargs="+",
        choices=["zetta", "zetta-log", "wideorbit", "enco", "csv"],
        help="Export formats (e.g., --export zetta-log csv)"
    )
    parser.add_argument(
        "--export-dir",
        help="Export output directory (default: exports/)"
    )
    parser.add_argument(
        "--export-scope",
        choices=["day", "week"],
        default="week",
        help="Export scope: one file per day or one file for whole week"
    )
    
    args = parser.parse_args()

    # Load data
    base = Path(__file__).parent
    songs = load_songs(base / "config" / "songs.json")
    pools = load_pools(base / "config" / "pools.json")
    clocks = load_clocks(base / "config" / "clocks.json")
    
    # Load week config
    week_config_path = Path(args.week_config)
    if not week_config_path.is_absolute():
        week_config_path = base / week_config_path
    
    if not week_config_path.exists():
        print(f'❌ Week config not found: {week_config_path}')
        return 1
    
    try:
        week_config = WeekConfig.load_from_file(week_config_path)
    except Exception as e:
        print(f'❌ Error loading week config: {e}')
        return 1
    
    # Determine week start date
    if args.start_date:
        week_start = datetime.strptime(args.start_date, "%Y-%m-%d").date()
    else:
        # Default to next Monday
        today = date.today()
        days_until_monday = (7 - today.weekday()) % 7
        if days_until_monday == 0:
            days_until_monday = 7  # If today is Monday, use next Monday
        week_start = today + timedelta(days=days_until_monday)
    
    # Generate time slots
    try:
        time_slots = week_config.get_slots_for_week(week_start, clocks)
    except ValueError as e:
        print(f'❌ Week configuration validation failed:')
        print(str(e))
        return 1
    
    print(f"\n✅ Week configuration validated: {len(time_slots)} time slots")
    
    # Load strategy
    strategy = None
    strategy_path = None
    
    if args.strategy:
        strategy_path = Path(args.strategy)
    elif week_config.default_strategy:
        strategy_path = Path(week_config.default_strategy)
    
    if strategy_path:
        if not strategy_path.is_absolute():
            strategy_path = base / strategy_path
        
        if not strategy_path.exists():
            print(f'❌ Strategy file not found: {strategy_path}')
            return 1
        
        try:
            strategy = load_strategy_from_file(strategy_path)
            print(f"✅ Loaded strategy: {strategy.name}")
        except Exception as e:
            print(f'❌ Error loading strategy: {e}')
            return 1
    
    # Load or create history
    history_file = base / "data" / "history.json"
    if args.clear_history and history_file.exists():
        history_file.unlink()
        print(f"✅ Cleared existing history")
    
    history = HistoryTracker.load(history_file)
    
    # Configure engine
    cfg = EngineConfig(
        disallow_duplicate_artist_within_block=True,
        disallow_duplicate_song_within_block=True,
        strategy=strategy
    )
    
    # Print header
    print("\n" + "="*70)
    print(f"WEEK SCHEDULE GENERATION: {week_config.week_name}")
    print("="*70)
    print(f"Week: {format_day_date(datetime.combine(week_start, datetime.min.time()))} - "
          f"{format_day_date(datetime.combine(week_start + timedelta(days=6), datetime.min.time()))}")
    print(f"Time slots: {len(time_slots)}")
    print(f"Songs available: {len([s for s in songs.values() if s.active])}")
    
    if strategy:
        sep_cfg = strategy.get_separation_config()
        print(f"Strategy: {strategy.name}")
        print(f"  Artist sep: {sep_cfg.artist_separation_minutes}min, "
              f"Song rest: {sep_cfg.song_rest_minutes}min")
    
    # Generate schedule for each time slot
    all_results = []
    context = SchedulingContext(start_time=datetime.now())
    
    current_day = None
    slot_num = 0
    
    for time_slot in time_slots:
        slot_num += 1
        
        # Get clock
        clock = clocks[time_slot.clock_name]
        
        # Get start time
        start_time = time_slot.get_datetime(week_start)
        
        # Print day header if new day
        if time_slot.day != current_day:
            current_day = time_slot.day
            print(f"\n{'='*70}")
            print(f"{time_slot.day.upper()} - {format_day_date(start_time)}")
            print(f"{'='*70}")
            
            # Reset daily context at start of each day
            if slot_num > 1:  # Don't reset on very first slot
                context.reset_hour()  # This also resets day counters
        
        # Generate block
        results, context = generate_block(
            clock,
            pools,
            songs,
            cfg,
            start_time,
            history,
            context,
            record_to_history=True
        )
        
        all_results.append((time_slot, start_time, results, context))
        
        # Print block summary
        if not args.summary_only:
            total_duration = sum(
                r.chosen_song.length_seconds for r in results if r.chosen_song
            )
            songs_placed = sum(1 for r in results if r.chosen_song)
            
            print(f"\n{format_time_hhmm(start_time)} - {clock.name} ({clock.duration_minutes}min)")
            print(f"  Songs: {songs_placed}/{len(results)}, Duration: {format_duration(total_duration)}")
            
            for idx, r in enumerate(results, start=1):
                if r.chosen_song:
                    s = r.chosen_song
                    print(f"    {idx}. {s.title[:35]:35} - {s.primary_artist[:20]:20}")
        
        # Reset hour context for next hour
        context.reset_hour()
    
    # Save history
    history.save(history_file)
    print(f"\n✅ Saved history to {history_file}")
    
    # Overall summary
    print("\n" + "="*70)
    print("WEEK SUMMARY")
    print("="*70)
    
    total_songs = sum(sum(1 for r in results if r.chosen_song) for _, _, results, _ in all_results)
    total_slots = sum(len(results) for _, _, results, _ in all_results)
    
    print(f"Total time slots: {len(time_slots)}")
    print(f"Total song slots: {total_slots}")
    print(f"Songs placed: {total_songs}")
    print(f"Empty slots: {total_slots - total_songs}")
    print(f"Fill rate: {(total_songs/total_slots*100):.1f}%")
    
    # Category totals
    if all_results:
        final_context = all_results[-1][3]
        if final_context.day_category_counts:
            print(f"\nWeek category totals:")
            for cat, count in sorted(final_context.day_category_counts.items()):
                print(f"  {cat}: {count}")
    
    # Save detailed output if requested
    if args.output:
        output_path = Path(args.output)
        with open(output_path, 'w') as f:
            f.write(f"WEEK SCHEDULE: {week_config.week_name}\n")
            f.write(f"Week: {week_start}\n")
            f.write("="*70 + "\n\n")
            
            current_day = None
            for time_slot, start_time, results, ctx in all_results:
                if time_slot.day != current_day:
                    current_day = time_slot.day
                    f.write(f"\n{'='*70}\n")
                    f.write(f"{time_slot.day.upper()} - {format_day_date(start_time)}\n")
                    f.write(f"{'='*70}\n\n")
                
                f.write(f"{format_time_hhmm(start_time)} - {clocks[time_slot.clock_name].name}\n")
                f.write("-"*70 + "\n")
                
                for idx, r in enumerate(results, start=1):
                    if r.chosen_song:
                        s = r.chosen_song
                        f.write(f"{idx}. {s.title} - {s.primary_artist} [{format_duration(s.length_seconds)}]\n")
                    else:
                        f.write(f"{idx}. [EMPTY]\n")
                
                f.write("\n")
        
        print(f"✅ Saved detailed log to {output_path}")
    
    # Export to automation formats if requested
    if args.export:
        from export_base import convert_schedule_results_to_blocks
        from exporter_zetta_log import ZettaLOGExporter
        from exporter_wideorbit import WideOrbitExporter
        from exporter_enco_csv import ENCOExporter, CSVExporter
        from overnight_fill import apply_overnight_fill, load_copy_rules_from_config
        
        # Optional: Zetta CSV format
        try:
            from exporter_zetta import ZettaExporter
            has_zetta_csv = True
        except ImportError:
            has_zetta_csv = False
        
        EXPORTERS = {
            "zetta-log": ZettaLOGExporter,
            "wideorbit": WideOrbitExporter,
            "enco": ENCOExporter,
            "csv": CSVExporter
        }
        
        if has_zetta_csv:
            EXPORTERS["zetta"] = ZettaExporter
        
        export_dir = Path(args.export_dir) if args.export_dir else base / "exports"
        export_dir.mkdir(parents=True, exist_ok=True)
        
        print(f"\n{'='*70}")
        print("EXPORTING TO AUTOMATION FORMATS")
        print(f"{'='*70}")
        print(f"Export directory: {export_dir}")
        print(f"Formats: {', '.join(args.export)}")
        print(f"Scope: {args.export_scope}")
        
        # Convert results to blocks
        blocks = convert_schedule_results_to_blocks(time_slots, all_results)
        
        # Apply overnight fill if configured
        # Load week config to check for fill_overnight settings
        with open(week_config_path, 'r') as f:
            import json
            week_config_data = json.load(f)
        
        copy_rules = load_copy_rules_from_config(week_config_data)
        
        if copy_rules:
            print(f"\n✅ Applying overnight fill ({len(copy_rules)} rules)")
            for rule in copy_rules:
                source_desc = f"{rule.source_start}-{rule.source_end}"
                target_desc = f"{rule.target_start}-{rule.target_end}"
                day_desc = "same day" if rule.source_day == "same" else "previous day"
                print(f"  • {source_desc} ({day_desc}) → {target_desc}")
            
            blocks = apply_overnight_fill(blocks, copy_rules, blocks[0].start_time if blocks else datetime.now())
            print(f"  Total blocks after fill: {len(blocks)}")
        
        # Group by day if doing day exports
        if args.export_scope == "day":
            blocks_by_day = {}
            for block in blocks:
                day_key = block.start_time.date()
                if day_key not in blocks_by_day:
                    blocks_by_day[day_key] = []
                blocks_by_day[day_key].append(block)
        
        # Export each format
        for format_name in args.export:
            exporter_class = EXPORTERS[format_name]
            exporter = exporter_class(export_dir)
            
            print(f"\n{format_name.upper()}:")
            
            if args.export_scope == "week":
                filename = exporter.generate_filename(blocks[0].start_time, scope="week")
                output_file = export_dir / filename
                exporter.export_week(blocks, output_file)
                print(f"  ✅ {output_file}")
            
            elif args.export_scope == "day":
                for day_date, day_blocks in blocks_by_day.items():
                    filename = exporter.generate_filename(
                        datetime.combine(day_date, datetime.min.time()),
                        scope="day"
                    )
                    output_file = export_dir / filename
                    exporter.export_day(day_blocks, output_file)
                    print(f"  ✅ {output_file}")
    
    print("\nDone.\n")
    return 0


if __name__ == "__main__":
    exit(main())
