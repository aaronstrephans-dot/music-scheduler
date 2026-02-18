#!/usr/bin/env python3
"""
import_m1_direct.py — Import songs from a Music1 .m1 database into data/tracks/

Cross-platform: works on Windows (pyodbc) and Linux (mdbtools).

Usage:
    python import_m1_direct.py "C:\\path\\to\\Praise FM.m1"
    python import_m1_direct.py "C:\\path\\to\\Praise FM.m1" --dry-run
    python import_m1_direct.py /path/to/Praise_FM.m1        # Linux

Windows requirements:
    pip install pyodbc
    Microsoft Access Database Engine must be installed.
    Download (free) from Microsoft if you don't have Access:
    https://www.microsoft.com/en-us/download/details.aspx?id=54920
    Choose the bitness (32/64) that matches your Python install.

Linux requirements:
    sudo apt-get install mdbtools

Column mapping from Music1 Songs table → track JSON:
    Title        → title        (required)
    Artist       → artist       (required)
    Rotation     → category     (required; mapped to Current/Recurrent/Gold)
    Length       → duration_seconds
    SongID       → m1_song_id   (kept for reference)

Category mapping (Music1 rotation codes → scheduler categories):
    A / AA / AAA / Current / 1  → Current
    B / Recurrent / 2           → Recurrent
    C / Gold / Oldies / 3       → Gold
    anything else               → Gold  (fallback)
"""

import csv
import json
import os
import platform
import subprocess
import sys
import uuid
from datetime import datetime, timezone


TRACKS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "tracks")

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

COL_TITLE    = ["title", "songtitle", "song_title", "name"]
COL_ARTIST   = ["artist", "artistname", "artist_name"]
COL_ROTATION = ["rotation", "category", "cat", "rotationcode"]
COL_LENGTH   = ["length", "duration", "runtime", "time"]
COL_SONGID   = ["songid", "song_id", "id", "trackid"]


# ---------------------------------------------------------------------------
# Windows backend (pyodbc)
# ---------------------------------------------------------------------------

def _windows_drivers():
    """Return list of installed Access-compatible ODBC driver names."""
    try:
        import pyodbc
        return [d for d in pyodbc.drivers()
                if "access" in d.lower() or "mdb" in d.lower() or "accdb" in d.lower()]
    except ImportError:
        return []


def _windows_read_table(m1_path, table_name):
    """Return (headers, rows) from an Access table using pyodbc."""
    try:
        import pyodbc
    except ImportError:
        print("ERROR: pyodbc is not installed.")
        print("       Run:  pip install pyodbc")
        sys.exit(1)

    drivers = _windows_drivers()
    if not drivers:
        print("ERROR: No Microsoft Access ODBC driver found.")
        print("       Download the Access Database Engine (free) from:")
        print("       https://www.microsoft.com/en-us/download/details.aspx?id=54920")
        print("       Choose the same bitness (32/64-bit) as your Python install.")
        sys.exit(1)

    driver = drivers[0]
    print(f"Using ODBC driver: {driver}")

    conn_str = f"Driver={{{driver}}};DBQ={m1_path};"
    conn = pyodbc.connect(conn_str, autocommit=True)
    cursor = conn.cursor()

    # List tables
    tables = [row.table_name for row in cursor.tables(tableType="TABLE")]
    print(f"Tables found: {tables}")

    if table_name not in tables:
        # case-insensitive fallback
        match = next((t for t in tables if t.lower() == table_name.lower()), None)
        if match:
            table_name = match
        else:
            print(f"ERROR: Table '{table_name}' not found. Available: {tables}")
            conn.close()
            sys.exit(1)

    print(f"Reading table: {table_name}")
    cursor.execute(f"SELECT * FROM [{table_name}]")
    headers = [col[0] for col in cursor.description]
    rows = [dict(zip(headers, row)) for row in cursor.fetchall()]
    conn.close()
    return headers, rows


def _windows_list_tables(m1_path):
    try:
        import pyodbc
    except ImportError:
        return []
    drivers = _windows_drivers()
    if not drivers:
        return []
    conn_str = f"Driver={{{drivers[0]}}};DBQ={m1_path};"
    conn = pyodbc.connect(conn_str, autocommit=True)
    cursor = conn.cursor()
    tables = [row.table_name for row in cursor.tables(tableType="TABLE")]
    conn.close()
    return tables


# ---------------------------------------------------------------------------
# Linux backend (mdbtools)
# ---------------------------------------------------------------------------

def _check_mdbtools():
    for tool in ("mdb-tables", "mdb-export"):
        if subprocess.run(["which", tool], capture_output=True).returncode != 0:
            print(f"ERROR: '{tool}' not found.")
            print("       Install with:  sudo apt-get install mdbtools")
            sys.exit(1)


def _linux_list_tables(m1_path):
    _check_mdbtools()
    result = subprocess.run(["mdb-tables", "-1", m1_path],
                            capture_output=True, text=True, check=True)
    return [t.strip() for t in result.stdout.splitlines() if t.strip()]


def _linux_read_table(m1_path, table_name):
    _check_mdbtools()
    result = subprocess.run(["mdb-export", m1_path, table_name],
                            capture_output=True, text=True, check=True)
    reader = csv.DictReader(result.stdout.splitlines())
    headers = reader.fieldnames or []
    rows = [dict(row) for row in reader]
    return headers, rows


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _find_col(headers, candidates):
    lower = {h.lower(): h for h in headers}
    for c in candidates:
        if c.lower() in lower:
            return lower[c.lower()]
    return None


def build_col_map(headers):
    return {
        "title":    _find_col(headers, COL_TITLE)    or headers[0],
        "artist":   _find_col(headers, COL_ARTIST),
        "rotation": _find_col(headers, COL_ROTATION),
        "length":   _find_col(headers, COL_LENGTH),
        "songid":   _find_col(headers, COL_SONGID),
    }


def parse_duration(value):
    if not value:
        return None
    value = str(value).strip()
    if ":" in value:
        parts = value.split(":")
        try:
            if len(parts) == 2:
                return int(parts[0]) * 60 + int(float(parts[1]))
            if len(parts) == 3:
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
    return CATEGORY_MAP.get(str(raw).strip().lower(), "Gold")


def _now():
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def row_to_track(row, col_map):
    title  = str(row.get(col_map["title"],  "") or "").strip()
    artist = str(row.get(col_map["artist"] or "", "") or "").strip() if col_map["artist"] else ""
    if not title:
        return None

    category = map_category(row.get(col_map["rotation"] or "", "") if col_map["rotation"] else "")
    duration = parse_duration(row.get(col_map["length"] or "", "") if col_map["length"] else "")
    m1_id    = str(row.get(col_map["songid"] or "", "") or "").strip() if col_map["songid"] else ""

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


def find_songs_table(tables):
    for name in tables:
        if name.lower() in ("songs", "song", "music", "tracks", "library"):
            return name
    return tables[0] if tables else None


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    import argparse
    parser = argparse.ArgumentParser(
        description="Import Music1 .m1 file into data/tracks/ (Windows + Linux)"
    )
    parser.add_argument("m1_file", help="Path to the .m1 database file")
    parser.add_argument("--dry-run", action="store_true",
                        help="Parse and report without writing any files")
    parser.add_argument("--table", default=None,
                        help="Override which Songs table to read (default: auto-detect)")
    args = parser.parse_args()

    if not os.path.isfile(args.m1_file):
        print(f"ERROR: File not found: {args.m1_file}")
        sys.exit(1)

    on_windows = platform.system() == "Windows"
    print(f"Platform: {'Windows (pyodbc)' if on_windows else 'Linux (mdbtools)'}")
    print(f"Opening:  {args.m1_file}")

    if on_windows:
        tables = _windows_list_tables(args.m1_file)
        print(f"Tables found: {tables}")
        table_name = args.table or find_songs_table(tables)
        if not table_name:
            print("ERROR: No tables found in the database.")
            sys.exit(1)
        headers, rows = _windows_read_table(args.m1_file, table_name)
    else:
        tables = _linux_list_tables(args.m1_file)
        print(f"Tables found: {tables}")
        table_name = args.table or find_songs_table(tables)
        if not table_name:
            print("ERROR: No tables found in the database.")
            sys.exit(1)
        print(f"Reading table: {table_name}")
        headers, rows = _linux_read_table(args.m1_file, table_name)

    print(f"Columns: {headers}")
    col_map = build_col_map(headers)
    print(f"Column mapping: {col_map}")

    if col_map["title"] is None:
        print("ERROR: Cannot find a Title column. Use --table or check column names above.")
        sys.exit(1)

    tracks, skipped = [], 0
    for row in rows:
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

    os.makedirs(TRACKS_DIR, exist_ok=True)
    for track in tracks:
        path = os.path.join(TRACKS_DIR, f"{track['id']}.json")
        with open(path, "w") as f:
            json.dump(track, f, indent=2)

    print(f"Wrote {len(tracks)} track files to {TRACKS_DIR}/")
    print("Done.")


if __name__ == "__main__":
    main()
