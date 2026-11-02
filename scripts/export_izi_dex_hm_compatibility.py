#!/usr/bin/env python3
"""Export Pokémon HM compatibility by PokéAPI version group for IZI Dex.

The source is the official PokéAPI CSV dataset. Compatibility means the Pokémon
has that move in its version-group learnset, matching the app's existing logic.
"""
from __future__ import annotations

import argparse
import csv
import json
from collections import defaultdict
from pathlib import Path

HM_MOVES = {
    "cut", "fly", "surf", "strength", "flash", "whirlpool", "waterfall",
    "rock-smash", "dive", "defog", "rock-climb",
}


def read_csv(path: Path):
    with path.open("r", encoding="utf-8", newline="") as handle:
        yield from csv.DictReader(handle)


def build_bundle(csv_dir: Path, source_commit: str = "") -> dict:
    move_ids = {
        int(row["id"]): row["identifier"]
        for row in read_csv(csv_dir / "moves.csv")
        if row["identifier"] in HM_MOVES
    }
    version_groups = {
        int(row["id"]): row["identifier"]
        for row in read_csv(csv_dir / "version_groups.csv")
    }
    grouped: dict[str, dict[str, set[str]]] = defaultdict(lambda: defaultdict(set))
    for row in read_csv(csv_dir / "pokemon_moves.csv"):
        move = move_ids.get(int(row["move_id"]))
        group = version_groups.get(int(row["version_group_id"]))
        if move and group:
            grouped[group][str(int(row["pokemon_id"]))].add(move)
    return {
        "schemaVersion": 1,
        "source": "izidororichart/pokeapi data/v2/csv",
        "sourceCommit": source_commit or None,
        "moveIds": sorted(HM_MOVES),
        "versionGroups": {
            group: {
                pokemon_id: sorted(moves)
                for pokemon_id, moves in sorted(pokemon.items(), key=lambda item: int(item[0]))
            }
            for group, pokemon in sorted(grouped.items())
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pokeapi-dir", type=Path, default=Path("data/v2/csv"))
    parser.add_argument("--output", type=Path, default=Path("izi-dex/v1/hm-compatibility.json"))
    parser.add_argument("--source-commit", default="")
    args = parser.parse_args()
    bundle = build_bundle(args.pokeapi_dir, args.source_commit)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(bundle, separators=(",", ":"), ensure_ascii=False) + "\n", encoding="utf-8")
    pokemon_count = len({pokemon_id for group in bundle["versionGroups"].values() for pokemon_id in group})
    print(f"Wrote {args.output}: {len(bundle['versionGroups'])} version groups, {pokemon_count} Pokémon records")


if __name__ == "__main__":
    main()
