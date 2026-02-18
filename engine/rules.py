DEFAULT_RULES = {
    "artist_separation_songs": 9,
    "title_separation_hours": 3,
    "categories": [
        {"name": "Current",   "rotation_hours": 2, "weight": 40},
        {"name": "Recurrent", "rotation_hours": 4, "weight": 30},
        {"name": "Gold",      "rotation_hours": 6, "weight": 30},
    ],
}


def merge_rules(overrides: dict) -> dict:
    """Return DEFAULT_RULES with caller-supplied overrides applied."""
    rules = {**DEFAULT_RULES}
    rules.update(overrides)
    return rules
