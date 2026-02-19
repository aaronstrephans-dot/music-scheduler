import argparse
import json
from pathlib import Path

from engine import EngineConfig, generate_block
from models import Clock, Pool, Slot, SlotFallback, Song


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def load_songs(path: Path) -> dict[str, Song]:
    raw = load_json(path)
    songs: dict[str, Song] = {}

    for s in raw["songs"]:
        artists = s.get("artists") or [s["artist"]]
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


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--clock", required=True, help="Clock name, e.g. WeekdayHalfHour")
    args = parser.parse_args()

    base = Path(__file__).parent
    songs = load_songs(base / "config" / "songs.json")
    pools = load_pools(base / "config" / "pools.json")
    clocks = load_clocks(base / "config" / "clocks.json")

    if args.clock not in clocks:
        raise SystemExit(f'Clock "{args.clock}" not found. Available: {", ".join(clocks.keys())}')

    results = generate_block(clocks[args.clock], pools, songs, EngineConfig())

    print(f"\nClock: {args.clock}")
    print("=" * (7 + len(args.clock)))
    for idx, r in enumerate(results, start=1):
        print(f"\nSlot {idx}: {r.slot_name}")
        if r.chosen_song:
            s = r.chosen_song
            mm, ss = divmod(s.length_seconds, 60)
            print(f'  ✓ {s.title} — {s.primary_artist} [{mm}:{ss:02d}]')
            print(f"    Why: {r.reason}")
        else:
            print("  ✗ EMPTY")
            print(f"    Why: {r.reason}")

        if r.rejected:
            for line in r.rejected[:5]:
                print(f"    - {line}")
            if len(r.rejected) > 5:
                print(f"    - (+{len(r.rejected)-5} more rejections)")

    print("\nDone.\n")


if __name__ == "__main__":
    main()
