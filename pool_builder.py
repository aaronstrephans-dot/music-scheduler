"""
Pool Builder - Automatically build song pools from song library.
Creates pools based on rotation, tempo, tags, etc.
"""
from typing import Dict
from models import Song, Pool


def build_pools_from_songs(songs: Dict[str, Song]) -> Dict[str, Pool]:
    """
    Build standard pools from song library.
    
    Automatically creates pools for:
    - Each rotation category (Current, PowerGold, Recurrent, etc.)
    - Combined pools (All Active, All Music, etc.)
    
    Args:
        songs: Dictionary of songs {song_id: Song}
    
    Returns:
        Dictionary of pools {pool_id: Pool}
    """
    pools = {}
    
    # Find all unique rotations
    rotations = set()
    for song in songs.values():
        if song.rotation:
            rotations.add(song.rotation)
    
    # Create pool for each rotation (use rotation name as pool_id)
    for rotation in rotations:
        pools[rotation] = Pool(
            pool_id=rotation,
            name=f"{rotation} Pool",
            include={"rotation": [rotation]},
            exclude={},
            active=True
        )
    
    # Also create lowercase versions with pool_ prefix for compatibility
    for rotation in rotations:
        pool_id = f"pool_{rotation.lower().replace(' ', '_')}"
        pools[pool_id] = Pool(
            pool_id=pool_id,
            name=f"{rotation} Pool",
            include={"rotation": [rotation]},
            exclude={},
            active=True
        )
    
    # Create "All Active" pool
    pools["pool_all_active"] = Pool(
        pool_id="pool_all_active",
        name="All Active Songs",
        include={},
        exclude={},
        active=True
    )
    
    # Create "All Music" pool (including inactive)
    pools["pool_all_music"] = Pool(
        pool_id="pool_all_music",
        name="All Music",
        include={},
        exclude={},
        active=True
    )
    
    return pools


def build_custom_pool(
    pool_id: str,
    name: str,
    include: Dict = None,
    exclude: Dict = None
) -> Pool:
    """
    Build a custom pool with specific criteria.
    
    Args:
        pool_id: Unique pool identifier
        name: Display name
        include: Inclusion criteria {field: [values]}
        exclude: Exclusion criteria {field: [values]}
    
    Returns:
        Pool object
    """
    return Pool(
        pool_id=pool_id,
        name=name,
        include=include or {},
        exclude=exclude or {},
        active=True
    )
