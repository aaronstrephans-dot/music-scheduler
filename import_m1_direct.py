#!/usr/bin/env python3
"""
import_m1_direct.py — Import songs from a Music1 .m1 database into data/tracks/

Usage:
    python import_m1_direct.py /path/to/Praise\ FM.m1
    python import_m1_direct.py /path/to/Praise\ FM.m1 --dry-run

Requirements (Linux):
    sudo apt-get install mdbtools

The .m1 file is a Microsoft Access (MDB) database.
mdbtools reads it natively on Linux without needing Windows or Wine.

Column mapping from Music1 Songs table → track JSON:
    Title        → title        (required)
    Artist       → artist       (required)
    Rotation     → category     (required; mapped to Current/Recurrent/Gold)
    Length       → duration_seconds
    SongID       → m1_song_id   (kept for reference)
    All others   → stored under extra_fields (not indexed)

Category mapping (Music1 rotation codes → scheduler categories):
    A / AA / AAA / Current / 1  → Current
    B / Recurrent / 2           → Recurrent
    C / Gold / Oldies / 3       → Gold
    anything else               → Gold  (fallback)
"""

import csv
import json
import os
import subprocess
import sys
import uuid
from datetime import datetime, timezone


TRACKS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "tracks")

# Music1 rotation codes → scheduler category
CATEGORY_MAP = {
    "a":         "Current",
    "aa":        "Current",
    "aaa":       "Current",
    "current":   "Current",
    "1":         "Current",
    "b":         "Recurrent",
    "recurrent": "Recurrent",
    "2":         "Recurrent",
    "c":         "Gold",
    "gold":      "Gold",
    "oldies":    "Gold",
    "3":         "Gold",
}

# Music1 column names to look for (case-insensitive)
COL_TITLE    = ["title", "songtitle", "song_title", "name"]
COL_ARTIST   = ["artist", "artistname", "artist_name"]
COL_ROTATION = ["rotation", "category", "cat", "rotationcode"]
COL_LENGTH   = ["length", "duration", "runtime", "time"]
COL_SONGID   = ["songid", "song_id", "id", "trackid"]


def check_mdbtools():
    for tool in ("mdb-tables", "mdb-export"):
        if subprocess.run(["which", tool], capture_output=True).returncode != 0:
            print(f"ERROR: '{tool}' not found. Install mdbtools:")
            print("       sudo apt-get install mdbtools")
            sys.exit(1)


def list_tables(m1_path):
    result = subprocess.run(
        ["mdb-tables", "-1", m1_path],
        capture_output=True, text=True, check=True
    )
    return [t.strip() for t in result.stdout.splitlines() if t.strip()]


def find_songs_table(tables):
    for name in tables:
        if name.lower() in ("songs", "song", "music", "tracks", "library"):
            return name
    # fallback: first table
    return tables[0] if tables else None


def export_table_csv(m1_path, table_name):
    result = subprocess.run(
        ["mdb-export", m1_path, table_name],
        capture_output=True, text=True, check=True
    )
    return result.stdout


def _find_col(headers, candidates):
    """Return the actual header name matching any candidate (case-insensitive)."""
    lower = {h.lower(): h for h in headers}
    for c in candidates:
        if c.lower() in lower:
            return lower[c.lower()]
    return None


def parse_duration(value):
    """Convert Music1 length field to integer seconds.
    Handles formats: 'MM:SS', 'H:MM:SS', integer seconds, float seconds.
    Returns None on failure.
    """
    if not value:
        return None
    value = str(value).strip()
    if ":" in value:
        parts = value.split(":")
        try:
            if len(parts) == 2:   # MM:SS
                return int(parts[0]) * 60 + int(float(parts[1]))
            if len(parts) == 3:   # H:MM:SS
                return int(parts[0]) * 3600 + int(parts[1]) * 60 + int(float(parts[2]))
        except ValueError:
            return None
    try:
        return int(float(value))
    except ValueError:
        return None


def map_category(raw):
    if not raw:
        return "Gold"
    key = str(raw).strip().lower()
    return CATEGORY_MAP.get(key, "Gold")


def _now():
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def row_to_track(row, col_map):
    title  = row.get(col_map["title"],  "").strip()
    artist = row.get(col_map["artist"], "").strip()

    if not title:
        return None  # skip rows without a title

    category = map_category(row.get(col_map["rotation"], ""))
    duration = parse_duration(row.get(col_map["length"], ""))
    m1_id    = row.get(col_map["songid"], "").strip()

    track = {
        "id":             str(uuid.uuid4()),
        "added_at":       _now(),
        "play_count":     0,
        "last_played_at": None,
        "title":          title,
        "artist":         artist or "Unknown Artist",
        "category":       category,
    }
    if duration is not None:
        track["duration_seconds"] = duration
    if m1_id:
        track["m1_song_id"] = m1_id

    return track


def build_col_map(headers):
    return {
        "title":    _find_col(headers, COL_TITLE)    or headers[0],
        "artist":   _find_col(headers, COL_ARTIST),
        "rotation": _find_col(headers, COL_ROTATION),
        "length":   _find_col(headers, COL_LENGTH),
        "songid":   _find_col(headers, COL_SONGID),
    }


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Import Music1 .m1 file into data/tracks/")
    parser.add_argument("m1_file", help="Path to the .m1 database file")
    parser.add_argument("--dry-run", action="store_true",
                        help="Parse and report without writing any files")
    parser.add_argument("--table", default=None,
                        help="Override which table to read (default: auto-detect Songs)")
    args = parser.parse_args()

    if not os.path.isfile(args.m1_file):
        print(f"ERROR: File not found: {args.m1_file}")
        sys.exit(1)

    check_mdbtools()

    # Discover tables
    print(f"Opening: {args.m1_file}")
    tables = list_tables(args.m1_file)
    print(f"Tables found: {tables}")

    table_name = args.table or find_songs_table(tables)
    if not table_name:
        print("ERROR: No tables found in the database.")
        sys.exit(1)
    print(f"Reading table: {table_name}")

    # Export to CSV and parse
    csv_data = export_table_csv(args.m1_file, table_name)
    reader   = csv.DictReader(csv_data.splitlines())
    headers  = reader.fieldnames or []
    print(f"Columns: {headers}")

    col_map = build_col_map(headers)
    print(f"Column mapping: {col_map}")

    if col_map["title"] is None:
        print("ERROR: Cannot find a Title column. Use --table or check column names above.")
        sys.exit(1)

    # Convert rows
    tracks, skipped = [], 0
    for row in reader:
        track = row_to_track(row, col_map)
        if track:
            tracks.append(track)
        else:
            skipped += 1

    print(f"\nParsed {len(tracks)} tracks, skipped {skipped} rows (no title).")

    if args.dry_run:
        print("DRY RUN — no files written.")
        if tracks:
            print("Sample (first 3):")
            for t in tracks[:3]:
                print(f"  {t['title']} / {t['artist']} / {t['category']} / {t.get('duration_seconds')}s")
        return

    # Write tracks
    os.makedirs(TRACKS_DIR, exist_ok=True)
    written = 0
    for track in tracks:
        path = os.path.join(TRACKS_DIR, f"{track['id']}.json")
        with open(path, "w") as f:
            json.dump(track, f, indent=2)
        written += 1

    print(f"Wrote {written} track files to {TRACKS_DIR}/")
    print("Done. You can now run the scheduler app and the tracks will be available.")


if __name__ == "__main__":
    main()
