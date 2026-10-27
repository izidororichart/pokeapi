#!/usr/bin/env python3
"""Export IZI Dex route and encounter data from PokeAPI CSVs.

The generated JSON is grouped by the exact game version used by IZI Dex. It
contains locations with encounter records, grouped by encounter method, with
species IDs, level ranges, and encounter-slot rates. No network access or third-
party Python packages are required.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import sys
import unicodedata
from collections import defaultdict
from pathlib import Path
from typing import Any

ENGLISH_LANGUAGE_ID = "9"
DEFAULT_OUTPUT_DIR = Path(__file__).resolve().parents[1] / "izi-dex" / "v1"

# PokeAPI's identifiers and IZI Dex's public game IDs differ for a few games.
VERSION_TO_GAME = {
    "red": "red", "blue": "blue", "yellow": "yellow",
    "gold": "gold", "silver": "silver", "crystal": "crystal",
    "ruby": "ruby", "sapphire": "sapphire", "emerald": "emerald",
    "firered": "firered", "leafgreen": "leafgreen",
    "diamond": "diamond", "pearl": "pearl", "platinum": "platinum",
    "heartgold": "heartgold", "soulsilver": "soulsilver",
    "black": "black", "white": "white", "black-2": "black2", "white-2": "white2",
    "x": "x", "y": "y", "omega-ruby": "omegaruby", "alpha-sapphire": "alphasapphire",
    "sun": "sun", "moon": "moon", "ultra-sun": "ultrasun", "ultra-moon": "ultramoon",
}
REGIONS = {
    "kanto": "Kanto", "johto": "Johto", "hoenn": "Hoenn", "sinnoh": "Sinnoh",
    "unova": "Unova", "kalos": "Kalos", "alola": "Alola",
    "hisui": "Hisui", "galar": "Galar",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Export IZI Dex route and encounter JSON from PokeAPI CSV files.")
    parser.add_argument("--pokeapi-dir", required=True, type=Path,
                        help="PokeAPI clone root, its data/v2/csv directory, or its data directory.")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR,
                        help=f"Output directory (default: {DEFAULT_OUTPUT_DIR}).")
    parser.add_argument("--max-species", type=int, default=809, help="Highest National Dex species ID (default: 809).")
    parser.add_argument("--max-generation", type=int, default=7, help="Highest generation to include (default: 7).")
    return parser.parse_args()


def find_csv_dir(source: Path) -> Path:
    source = source.expanduser().resolve()
    for candidate in (source, source / "data" / "v2" / "csv", source / "v2" / "csv", source / "csv"):
        if (candidate / "pokemon.csv").is_file() and (candidate / "encounters.csv").is_file():
            return candidate
    raise FileNotFoundError("Could not find PokeAPI CSV files (pokemon.csv and encounters.csv). Check --pokeapi-dir.")


def read_csv(csv_dir: Path, filename: str, *, required: bool = True) -> list[dict[str, str]]:
    path = csv_dir / filename
    if not path.is_file():
        if required:
            raise FileNotFoundError(f"Required PokeAPI CSV file is missing: {path}")
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def int_or_none(value: Any) -> int | None:
    try:
        return int(value) if value is not None and str(value).strip() else None
    except (TypeError, ValueError):
        return None


def pretty_identifier(value: str) -> str:
    return " ".join(part[:1].upper() + part[1:] for part in re.split(r"[-_]+", (value or "").strip()) if part)


def normalized(value: str) -> str:
    text = unicodedata.normalize("NFKD", value or "")
    text = "".join(char for char in text if not unicodedata.combining(char))
    return re.sub(r"[^a-z0-9]+", "", text.lower())


def slugify(value: str) -> str:
    text = unicodedata.normalize("NFKD", value or "")
    text = "".join(char for char in text if not unicodedata.combining(char))
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def english_names(rows: list[dict[str, str]], key_field: str) -> dict[str, str]:
    return {
        row.get(key_field, ""): row.get("name", "").strip()
        for row in rows
        if row.get("local_language_id") == ENGLISH_LANGUAGE_ID and row.get(key_field) and row.get("name", "").strip()
    }


def encounter_level(minimum: int | None, maximum: int | None) -> str:
    if minimum is None and maximum is None:
        return ""
    if minimum is None:
        minimum = maximum
    if maximum is None:
        maximum = minimum
    return str(minimum) if minimum == maximum else f"{minimum}-{maximum}"


def build_encounter_catalog(csv_dir: Path, max_species: int, max_generation: int) -> dict[str, Any]:
    versions = read_csv(csv_dir, "versions.csv")
    locations = read_csv(csv_dir, "locations.csv")
    location_areas = read_csv(csv_dir, "location_areas.csv")
    pokemon_rows = read_csv(csv_dir, "pokemon.csv")
    species_rows = read_csv(csv_dir, "pokemon_species.csv")
    slots = read_csv(csv_dir, "encounter_slots.csv")
    methods = read_csv(csv_dir, "encounter_methods.csv")
    method_prose = read_csv(csv_dir, "encounter_method_prose.csv", required=False)
    location_names_rows = read_csv(csv_dir, "location_names.csv", required=False)

    location_names = english_names(location_names_rows, "location_id")
    method_names = {
        row.get("encounter_method_id", ""): row.get("name", "").strip()
        for row in method_prose
        if row.get("local_language_id") == ENGLISH_LANGUAGE_ID and row.get("encounter_method_id") and row.get("name", "").strip()
    }
    method_identifiers = {row.get("id", ""): row.get("identifier", "") for row in methods}
    location_by_id = {row.get("id", ""): row for row in locations}
    location_area_to_location = {row.get("id", ""): row.get("location_id", "") for row in location_areas}
    area_identifiers = {row.get("id", ""): row.get("identifier", "") for row in location_areas}
    pokemon_to_species = {
        row.get("id", ""): (int_or_none(row.get("species_id")) or int_or_none(row.get("id")))
        for row in pokemon_rows
    }
    species_generation = {
        row.get("id", ""): int_or_none(row.get("generation_id"))
        for row in species_rows
    }
    eligible_species = {
        species_id for species_id, generation in species_generation.items()
        if (int_or_none(species_id) or 0) <= max_species and generation is not None and generation <= max_generation
    }
    slot_by_id = {row.get("id", ""): row for row in slots}
    version_to_game: dict[str, str] = {}
    version_group_by_game: dict[str, str] = {}
    for row in versions:
        game = VERSION_TO_GAME.get(row.get("identifier", ""))
        if game:
            version_to_game[row.get("id", "")] = game
            version_group_by_game[game] = row.get("version_group_id", "")

    # (game, location ID, method ID) -> set of compact entries. Merging location
    # areas beneath a location keeps routes together while retaining method details.
    encounters_by_key: dict[tuple[str, str, str], set[tuple[int, int | None, int | None, int | None]]] = defaultdict(set)
    for row in read_csv(csv_dir, "encounters.csv"):
        game = version_to_game.get(row.get("version_id", ""))
        if not game:
            continue
        location_id = location_area_to_location.get(row.get("location_area_id", ""))
        slot = slot_by_id.get(row.get("encounter_slot_id", ""))
        if not location_id or not slot or slot.get("version_group_id") != version_group_by_game.get(game):
            continue
        species_id = pokemon_to_species.get(row.get("pokemon_id", ""))
        if species_id is None or str(species_id) not in eligible_species:
            continue
        method_id = slot.get("encounter_method_id", "")
        if not method_id:
            continue
        encounters_by_key[(game, location_id, method_id)].add((
            species_id,
            int_or_none(row.get("min_level")),
            int_or_none(row.get("max_level")),
            int_or_none(slot.get("rarity")),
        ))

    by_game: dict[str, list[dict[str, Any]]] = {}
    for game in VERSION_TO_GAME.values():
        location_ids = sorted(
            {location_id for candidate_game, location_id, _ in encounters_by_key if candidate_game == game},
            key=lambda value: int_or_none(value) or 0,
        )
        areas: list[dict[str, Any]] = []
        for location_id in location_ids:
            location = location_by_id.get(location_id, {})
            identifier = location.get("identifier", "") or f"location-{location_id}"
            base_name = location_names.get(location_id) or pretty_identifier(identifier)
            groups: list[dict[str, Any]] = []
            method_ids = sorted(
                {method_id for candidate_game, candidate_location, method_id in encounters_by_key
                 if candidate_game == game and candidate_location == location_id},
                key=lambda value: int_or_none(value) or 0,
            )
            for method_id in method_ids:
                records = encounters_by_key[(game, location_id, method_id)]
                compact_entries: set[str] = set()
                for species_id, minimum, maximum, rate in records:
                    level = encounter_level(minimum, maximum)
                    entry = str(species_id)
                    if level or rate is not None:
                        entry += "," + level
                    if rate is not None:
                        if not level:
                            entry += ","
                        entry += "," + str(rate)
                    compact_entries.add(entry)
                method_label = method_names.get(method_id) or pretty_identifier(method_identifiers.get(method_id, ""))
                groups.append({
                    "id": slugify(method_identifiers.get(method_id, "")) or f"method-{method_id}",
                    "method": method_label or "Wild Pokémon",
                    "pokemon": sorted(compact_entries, key=lambda entry: (
                        int(entry.split(",", 1)[0]),
                        entry.split(",")[1] if "," in entry else "",
                        entry.split(",")[2] if entry.count(",") >= 2 else "",
                    )),
                })
            groups = [group for group in groups if group["pokemon"]]
            if not groups:
                continue
            areas.append({
                "id": slugify(identifier) or f"location-{location_id}",
                "name": base_name,
                "matchName": base_name,
                "locationId": int_or_none(location_id),
                "encounters": groups,
            })

        # A few games contain separate regions with identically named routes
        # (e.g. Route 1). Keep those locations distinct in the interface.
        counts: dict[str, int] = defaultdict(int)
        for area in areas:
            counts[normalized(area["name"])] += 1
        for area in areas:
            if counts[normalized(area["name"])] > 1:
                identifier = location_by_id.get(str(area.get("locationId") or ""), {}).get("identifier", "")
                region_slug = identifier.split("-", 1)[0]
                if region_slug in REGIONS:
                    area["name"] = f'{area["name"]} ({REGIONS[region_slug]})'
        by_game[game] = areas

    return {
        "schemaVersion": 1,
        "maxSpecies": max_species,
        "maxGeneration": max_generation,
        "games": by_game,
    }


def main() -> int:
    args = parse_args()
    if args.max_species < 1 or args.max_generation < 1:
        print("--max-species and --max-generation must be positive integers", file=sys.stderr)
        return 2
    try:
        csv_dir = find_csv_dir(args.pokeapi_dir)
        output_dir = args.output_dir.expanduser().resolve()
        output_dir.mkdir(parents=True, exist_ok=True)

        catalog = build_encounter_catalog(csv_dir, args.max_species, args.max_generation)
        encounters_path = output_dir / "encounters.json"
        encounters_path.write_text(json.dumps(catalog, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        encounters_sha = hashlib.sha256(encounters_path.read_bytes()).hexdigest()
        total_areas = sum(len(areas) for areas in catalog["games"].values())

        manifest_path = output_dir / "manifest.json"
        if not manifest_path.is_file():
            raise FileNotFoundError(f"Data manifest not found; run export_izi_dex_data.py first: {manifest_path}")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if not isinstance(manifest.get("pokemon"), dict) or not manifest["pokemon"].get("sha256"):
            raise ValueError("Existing data manifest has no Pokémon checksum.")
        manifest["encounters"] = {
            "file": "encounters.json",
            "count": total_areas,
            "gameCount": len(catalog["games"]),
            "sha256": encounters_sha,
        }
        checksum_parts = [manifest["pokemon"]["sha256"]]
        forms_sha = (manifest.get("forms") or {}).get("sha256")
        if forms_sha:
            checksum_parts.append(forms_sha)
        checksum_parts.append(encounters_sha)
        manifest["dataVersion"] = hashlib.sha256(":".join(checksum_parts).encode("utf-8")).hexdigest()[:24]
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"Wrote {total_areas} game-specific locations to {encounters_path}")
        print(f"Updated bundle manifest to data version {manifest['dataVersion']}")
        return 0
    except (FileNotFoundError, ValueError, OSError, csv.Error, json.JSONDecodeError) as exc:
        print(f"PokeAPI encounter export failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
