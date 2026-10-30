#!/usr/bin/env python3
"""Import PokeDB's public JSON export into the IZI Dex supplemental encounter bundle.

Expected files in --pokedb-dir:
  encounters.json, pokemon_forms.json, location_areas.json, locations.json,
  encounter_methods.json
Also needs this fork's data/v2/csv/locations.csv and location_names.csv.

Only BDSP, Legends: Arceus, Scarlet and Violet are imported here. Let's Go and
Sword/Shield are exported through the official PokeAPI CSV exporter instead.
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

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_POKEDB_DIR = REPO_ROOT / "data" / "pokedb"
DEFAULT_CSV_DIR = REPO_ROOT / "data" / "v2" / "csv"
DEFAULT_OUTPUT_DIR = REPO_ROOT / "izi-dex" / "v1"

VERSION_TO_GAME = {
    "brilliant-diamond": "brilliantdiamond",
    "shining-pearl": "shiningpearl",
    "legends-arceus": "legendsarceus",
    "scarlet": "scarlet",
    "violet": "violet",
}

def args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build IZI Dex encounter supplement from PokeDB JSON exports.")
    parser.add_argument("--pokedb-dir", type=Path, default=DEFAULT_POKEDB_DIR)
    parser.add_argument("--pokeapi-csv-dir", type=Path, default=DEFAULT_CSV_DIR)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--dry-run", action="store_true", help="Validate and summarize without writing files.")
    return parser.parse_args()

def read_array(folder: Path, filename: str, required: bool = True) -> list[dict[str, Any]]:
    path = folder / filename
    if not path.exists():
        if required:
            raise FileNotFoundError(f"Missing PokeDB export: {path}")
        return []
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, list):
        raise ValueError(f"{filename} must contain a JSON array")
    return value

def read_csv(folder: Path, filename: str, required: bool = True) -> list[dict[str, str]]:
    path = folder / filename
    if not path.exists():
        if required:
            raise FileNotFoundError(f"Missing PokeAPI CSV: {path}")
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))

def slug(value: str) -> str:
    value = unicodedata.normalize("NFKD", value or "")
    value = "".join(c for c in value if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")

def number(value: Any) -> float | None:
    if value is None or value == "":
        return None
    match = re.search(r"-?\d+(?:\.\d+)?", str(value).replace(",", "."))
    if not match:
        return None
    try:
        return float(match.group(0))
    except ValueError:
        return None

def level_range(value: Any) -> tuple[int | None, int | None]:
    if value is None:
        return None, None
    values = [int(x) for x in re.findall(r"\d+", str(value))]
    if not values:
        return None, None
    return min(values), max(values)

def rate_value(row: dict[str, Any]) -> float | None:
    value = row.get("probability_overall")
    if value in (None, ""):
        value = row.get("rate_overall")
    if value is None or value == "":
        return None
    text = str(value).strip()
    fraction = re.fullmatch(r"(\d+(?:\.\d+)?)\s*/\s*(\d+(?:\.\d+)?)", text)
    if fraction:
        numerator, denominator = map(float, fraction.groups())
        parsed = numerator / denominator * 100 if denominator else None
    else:
        parsed = number(text)
    return round(parsed, 2) if parsed is not None and 0 <= parsed <= 100 else None

def labels(row: dict[str, Any]) -> list[str]:
    result: list[str] = []
    if not row.get("during_any_time"):
        times = [name for name in ("morning", "day", "evening", "night") if row.get("during_" + name)]
        if times:
            result.append("Time: " + ", ".join(times))
    if not row.get("while_weather_overall"):
        weather = [name for name in ("clear", "harsh_sunlight", "cloudy", "blizzard") if row.get("while_" + name)]
        if weather:
            result.append("Weather: " + ", ".join(weather).replace("_", " "))
    terrain = [name for name in ("land", "watersurface", "underwater", "overland", "sky") if row.get("on_terrain_" + name)]
    if terrain:
        result.append("Terrain: " + ", ".join(terrain).replace("watersurface", "water surface"))
    return result

def boolish(value: Any) -> bool:
    return value is True or str(value).lower() in ("1", "true", "yes")

def main() -> int:
    options = args()
    pokedb_dir = options.pokedb_dir.expanduser().resolve()
    csv_dir = options.pokeapi_csv_dir.expanduser().resolve()
    output_dir = options.output_dir.expanduser().resolve()

    encounters = read_array(pokedb_dir, "encounters.json")
    forms = read_array(pokedb_dir, "pokemon_forms.json")
    areas = read_array(pokedb_dir, "location_areas.json")
    locations = read_array(pokedb_dir, "locations.json")
    methods = read_array(pokedb_dir, "encounter_methods.json")

    pokeapi_locations = read_csv(csv_dir, "locations.csv")
    pokeapi_location_names = read_csv(csv_dir, "location_names.csv", required=False)
    english_names = {
        row.get("location_id", ""): row.get("name", "").strip()
        for row in pokeapi_location_names
        if row.get("local_language_id") == "9" and row.get("name", "").strip()
    }
    location_ids = {
        row.get("identifier", ""): int(row["id"])
        for row in pokeapi_locations
        if row.get("id", "").isdigit()
    }

    form_by_id = {row.get("identifier"): row for row in forms}
    area_by_id = {row.get("identifier"): row for row in areas}
    location_by_id = {row.get("identifier"): row for row in locations}
    method_by_id = {row.get("identifier"): row for row in methods}

    # game -> parent location -> (method, sub-area, time/weather/terrain) -> rows
    grouped: dict[str, dict[str, dict[tuple[str, ...], dict[str, Any]]]] = defaultdict(lambda: defaultdict(dict))
    missing = defaultdict(int)
    unmapped_locations: set[str] = set()
    imported_rows = defaultdict(int)

    for row in encounters:
        versions = row.get("version_identifiers") or []
        games = {VERSION_TO_GAME[v] for v in versions if v in VERSION_TO_GAME}
        if not games:
            continue
        form = form_by_id.get(row.get("pokemon_form_identifier"))
        area = area_by_id.get(row.get("location_area_identifier"))
        method = method_by_id.get(row.get("encounter_method_identifier"))
        if not form:
            missing["forms"] += 1
            continue
        if not area:
            missing["areas"] += 1
            continue
        location = location_by_id.get(area.get("location_identifier"))
        if not location:
            missing["locations"] += 1
            continue
        if not method:
            missing["methods"] += 1
            continue
        species_id = int(form.get("ndex_id") or 0)
        if not 1 <= species_id <= 1025:
            missing["species"] += 1
            continue
        location_slug = location.get("identifier") or slug(location.get("name") or "unknown")
        location_id = location_ids.get(location_slug)
        if location_id is None:
            unmapped_locations.add(location_slug)
        location_name = location.get("name") or location_slug.replace("-", " ").title()
        if location_id is not None:
            location_name = english_names.get(str(location_id), location_name)

        time_weather_terrain = labels(row)
        area_name = area.get("name") or area.get("identifier") or ""
        sub_area = area_name.strip()
        qualifier = " · ".join(part for part in [sub_area, *time_weather_terrain] if part)
        minimum, maximum = level_range(row.get("levels"))
        alpha_min, alpha_max = level_range(row.get("alpha_levels"))
        rate = rate_value(row)
        alpha = boolish(row.get("is_alpha")) or row.get("alpha_levels") not in (None, "")
        method_identifier = method.get("identifier") or "wild"
        method_name = method.get("name") or "Wild Pokémon"
        if alpha:
            method_identifier = "alpha-" + method_identifier
            method_name = "Alpha Pokémon"
        group_key = (method_identifier, method_name, qualifier)
        for game in games:
            target = grouped[game][location_slug].setdefault(group_key, {
                "id": slug("-".join(group_key)) or "encounter",
                "method": " · ".join(part for part in [method_name, qualifier] if part),
                "pokemon": {},
            })
            entry_key = (species_id, bool(alpha))
            entry = target["pokemon"].setdefault(entry_key, {"id": species_id})
            if alpha:
                if alpha_min is not None:
                    entry["minLevel"] = min(entry.get("minLevel", alpha_min), alpha_min)
                    entry["maxLevel"] = max(entry.get("maxLevel", alpha_max), alpha_max)
                entry["rate"] = 100
            else:
                if minimum is not None:
                    entry["minLevel"] = min(entry.get("minLevel", minimum), minimum)
                    entry["maxLevel"] = max(entry.get("maxLevel", maximum), maximum)
                if rate is not None:
                    entry["rate"] = max(entry.get("rate", rate), rate)
            imported_rows[game] += 1

    supplemental_path = output_dir / "encounters-supplemental.json"
    existing: dict[str, Any] = {}
    if supplemental_path.exists():
        existing = json.loads(supplemental_path.read_text(encoding="utf-8"))
    supplemental_games = dict(existing.get("games") or {})
    counts: dict[str, int] = {}

    for game, game_locations in grouped.items():
        game_areas = []
        for location_slug, method_groups in game_locations.items():
            location = location_by_id.get(location_slug, {})
            location_name = location.get("name") or location_slug.replace("-", " ").title()
            location_id = location_ids.get(location_slug)
            if location_id is not None:
                location_name = english_names.get(str(location_id), location_name)
            out_groups = []
            for key, group in method_groups.items():
                entries = list(group["pokemon"].values())
                entries.sort(key=lambda item: (item["id"], item.get("minLevel", 0), item.get("rate", 0)))
                if entries:
                    out_groups.append({"id": group["id"], "method": group["method"], "pokemon": entries})
            if not out_groups:
                continue
            area: dict[str, Any] = {
                "id": slug(location_slug) or f"pokedb-{game}",
                "name": location_name,
                "encounters": out_groups,
                "source": "pokedb",
            }
            if location_id is not None:
                area["locationId"] = location_id
            game_areas.append(area)
        game_areas.sort(key=lambda item: (item.get("locationId", 999999), item["name"]))
        supplemental_games[game] = game_areas
        counts[game] = len(game_areas)

    result = {
        "schemaVersion": 1,
        "maxSpecies": 1025,
        "maxGeneration": 9,
        "games": supplemental_games,
        "sources": {
            **(existing.get("sources") or {}),
            "pokedb": {
                "name": "PokeDB Data Export",
                "url": "https://pokedb.org/data-export/",
                "terms": "Educational, research and non-commercial use; contact PokeDB for commercial licensing.",
                "games": ["brilliantdiamond", "shiningpearl", "legendsarceus", "scarlet", "violet"],
            },
        },
        "coverage": {**(existing.get("coverage") or {}), "pokedb": {
            "areasByGame": counts,
            "rowsByGame": dict(imported_rows),
            "unmappedLocationIdentifiers": sorted(unmapped_locations),
            "missingJoins": dict(missing),
        }},
    }
    serialized = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    checksum = hashlib.sha256(serialized.encode("utf-8")).hexdigest()

    print(f"PokeDB encounters scanned: {len(encounters)}")
    for game in sorted(counts):
        print(f"  {game}: {imported_rows[game]} encounter rows, {counts[game]} locations")
    print(f"Missing joins: {dict(missing)}")
    print(f"Locations not mapped to PokeAPI location IDs: {len(unmapped_locations)}")
    if unmapped_locations:
        print("  " + ", ".join(sorted(unmapped_locations)[:30]))
    if options.dry_run:
        print("Dry run only; no files written.")
        return 0

    output_dir.mkdir(parents=True, exist_ok=True)
    supplemental_path.write_text(serialized, encoding="utf-8")
    manifest_path = output_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    base_parts = [
        manifest["pokemon"]["sha256"],
        (manifest.get("forms") or {}).get("sha256", ""),
        manifest["encounters"]["sha256"],
        checksum,
    ]
    manifest["encountersSupplemental"] = {
        "file": "encounters-supplemental.json",
        "count": sum(counts.values()) + len(supplemental_games.get("legendsza", [])),
        "gameCount": len(supplemental_games),
        "sha256": checksum,
    }
    manifest["dataVersion"] = hashlib.sha256(":".join(x for x in base_parts if x).encode("utf-8")).hexdigest()[:24]
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {supplemental_path}")
    print(f"Updated {manifest_path} ({manifest['dataVersion']})")
    return 0

if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, KeyError, json.JSONDecodeError, csv.Error) as exc:
        print(f"PokeDB import failed: {exc}", file=sys.stderr)
        raise SystemExit(1)
