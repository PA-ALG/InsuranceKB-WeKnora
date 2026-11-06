"""Read the two declared inputs independently of the production catalog merger for order tests."""

import json
from pathlib import Path
from typing import Any


def expected_fields(path: Path) -> dict[str, Any]:
    base: dict[str, Any] = json.loads(path.read_bytes())
    overlay = json.loads(path.with_name("schema_pack_additions.json").read_bytes())
    for entry in base["entries"]:
        pack = entry["pack"]
        for row in overlay["additions"]:
            if row["pack_id"] != pack["schema_pack_id"]:
                continue
            key = row["field_key"]
            field = next(f for f in overlay["field_definitions"] if f["field_key"] == key)
            pack["fields"].append(field)
            section = next(
                s
                for s in entry["profile"]["sections"]
                if s["section_key"] == row["display"]["section_key"]
            )
            section["fields"].append(
                {"field_key": key, "short_title": row["display"]["short_title"]}
            )
    return base
