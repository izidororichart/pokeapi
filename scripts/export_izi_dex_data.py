#!/usr/bin/env python3
"""Build IZI Dex's compact local JSON catalogs from a PokeAPI repository clone.

No network access or third-party Python packages are required. The source directory
must contain data/v2/csv (or be that directory itself).
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT_DIR = REPO_ROOT / "izi-dex" / "v1"
STAT_LABELS = {
    "hp": "HP",
    "attack": "Attack",
    "defense": "Defense",
    "special-attack": "Sp. Attack",
    "special-defense": "Sp. Defense",
    "speed": "Speed",
}
POKEAPI_ENGLISH_LANGUAGE_ID = "9"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate IZI Dex Pokémon and alternate-form JSON from PokeAPI CSV files."
    )
    parser.add_argument(
        "--pokeapi-dir",
        required=True,
        type=Path,
        help="Path to the PokeAPI clone root, its data/v2/csv directory, or its data directory.",
    )
    parser.add_argument(
        "--max-species",
        type=int,
        default=809,
        help="Highest National Pokédex species ID to export (default: 809).",
    )
    parser.add_argument(
        "--max-generation",
        type=int,
        default=7,
        help="Highest generation to include (default: 7).",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help=f"Output folder (default: {DEFAULT_OUTPUT_DIR}).",
    )
    parser.add_argument(
        "--source-commit",
        default=os.environ.get("GITHUB_SHA", "local"),
        help="Source commit SHA to record in manifest.json (defaults to GITHUB_SHA when run in Actions).",
    )
    parser.add_argument(
        "--source-branch",
        default=os.environ.get("GITHUB_REF_NAME", "master"),
        help="Source branch to record in manifest.json.",
    )
    parser.add_argument(
        "--source-repository",
        default=os.environ.get("IZI_DEX_SOURCE_REPOSITORY", os.environ.get("GITHUB_REPOSITORY", "izidororichart/pokeapi")),
        help="Source repository to record in manifest.json.",
    )
    parser.add_argument(
        "--skip-forms",
        action="store_true",
        help="Only write pokemon.json; do not generate pokemon-forms.json.",
    )
    return parser.parse_args()


def find_csv_dir(source: Path) -> Path:
    source = source.expanduser().resolve()
    candidates = [
        source,
        source / "data" / "v2" / "csv",
        source / "v2" / "csv",
        source / "csv",
    ]
    for candidate in candidates:
        if (candidate / "pokemon.csv").is_file() and (candidate / "pokemon_species.csv").is_file():
            return candidate
    raise FileNotFoundError(
        "Could not find PokeAPI CSV files. Expected pokemon.csv and pokemon_species.csv in "
        "<clone>/data/v2/csv. Check --pokeapi-dir."
    )


def read_csv(csv_dir: Path, filename: str, *, required: bool = True) -> list[dict[str, str]]:
    path = csv_dir / filename
    if not path.is_file():
        if required:
            raise FileNotFoundError(f"Required PokeAPI CSV file is missing: {path}")
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def int_or_none(value: Any) -> int | None:
    if value is None or str(value).strip() == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def int_value(value: Any, *, default: int = 0) -> int:
    parsed = int_or_none(value)
    return default if parsed is None else parsed


def bool_value(value: Any) -> bool:
    return str(value).strip() == "1"


def pretty_identifier(value: str) -> str:
    return " ".join(part[:1].upper() + part[1:] for part in value.replace("_", "-").split("-") if part)


def make_sprite_url(identifier: str, generation: int) -> str:
    slug = identifier.strip().lower()
    if generation <= 5:
        return f"https://img.pokemondb.net/sprites/black-white/anim/normal/{slug}.gif"
    return f"https://projectpokemon.org/images/normal-sprite/{slug}.gif"


def grouped_by(rows: list[dict[str, str]], key: str) -> dict[str, list[dict[str, str]]]:
    result: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        result[row.get(key, "")].append(row)
    return result


def build_catalogs(
    csv_dir: Path, max_species: int, max_generation: int, include_forms: bool
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    species_rows = read_csv(csv_dir, "pokemon_species.csv")
    pokemon_rows = read_csv(csv_dir, "pokemon.csv")
    english_names_rows = read_csv(csv_dir, "pokemon_species_names.csv")
    type_rows = read_csv(csv_dir, "types.csv")
    pokemon_type_rows = read_csv(csv_dir, "pokemon_types.csv")
    stat_rows = read_csv(csv_dir, "stats.csv")
    pokemon_stat_rows = read_csv(csv_dir, "pokemon_stats.csv")

    species_by_id = {
        int_value(row.get("id")): row
        for row in species_rows
        if int_or_none(row.get("id")) is not None
    }
    english_names = {
        int_value(row.get("pokemon_species_id")): row.get("name", "").strip()
        for row in english_names_rows
        if row.get("local_language_id") == POKEAPI_ENGLISH_LANGUAGE_ID and row.get("name", "").strip()
    }
    types_by_id = {
        int_value(row.get("id")): pretty_identifier(row.get("identifier", ""))
        for row in type_rows
        if int_or_none(row.get("id")) is not None and row.get("identifier")
    }
    stat_names = {
        int_value(row.get("id")): STAT_LABELS.get(
            row.get("identifier", ""), pretty_identifier(row.get("identifier", ""))
        )
        for row in stat_rows
        if int_or_none(row.get("id")) is not None and row.get("identifier")
    }

    pokemon_by_species: dict[int, list[dict[str, str]]] = defaultdict(list)
    pokemon_by_id: dict[int, dict[str, str]] = {}
    for row in pokemon_rows:
        pid = int_or_none(row.get("id"))
        species_id = int_or_none(row.get("species_id"))
        if pid is None or species_id is None:
            continue
        pokemon_by_species[species_id].append(row)
        pokemon_by_id[pid] = row

    def choose_default_pokemon(species_id: int) -> dict[str, str] | None:
        candidates = pokemon_by_species.get(species_id, [])
        preferred = next(
            (
                row for row in candidates
                if int_value(row.get("id")) == species_id and bool_value(row.get("is_default"))
            ),
            None,
        )
        if preferred:
            return preferred
        candidates = [row for row in candidates if bool_value(row.get("is_default"))]
        if not candidates:
            return None
        return min(candidates, key=lambda row: int_value(row.get("id")))

    types_by_pokemon = grouped_by(pokemon_type_rows, "pokemon_id")
    stats_by_pokemon = grouped_by(pokemon_stat_rows, "pokemon_id")

    def get_types(pokemon_id: int) -> list[str]:
        entries = sorted(types_by_pokemon.get(str(pokemon_id), []), key=lambda row: int_value(row.get("slot")))
        return [
            types_by_id[int_value(row.get("type_id"))]
            for row in entries
            if int_value(row.get("type_id")) in types_by_id
        ]

    def get_stats(pokemon_id: int) -> dict[str, int]:
        entries = sorted(
            stats_by_pokemon.get(str(pokemon_id), []),
            key=lambda row: int_value(row.get("stat_id")),
        )
        result: dict[str, int] = {}
        for row in entries:
            stat_id = int_or_none(row.get("stat_id"))
            if stat_id is not None and stat_id in stat_names:
                result[stat_names[stat_id]] = int_value(row.get("base_stat"))
        return result

    catalog: list[dict[str, Any]] = []
    target_species = [
        row for row in species_rows
        if (sid := int_or_none(row.get("id"))) is not None
        and sid <= max_species
        and int_value(row.get("generation_id")) <= max_generation
    ]
    target_species.sort(key=lambda row: int_value(row.get("id")))

    for species in target_species:
        species_id = int_value(species.get("id"))
        generation = int_value(species.get("generation_id"), default=1)
        pokemon = choose_default_pokemon(species_id)
        if pokemon is None:
            raise ValueError(
                f"No default Pokémon record found for species #{species_id} ({species.get('identifier')})."
            )
        pokemon_id = int_value(pokemon.get("id"))
        identifier = species.get("identifier", "") or pokemon.get("identifier", "")
        name = english_names.get(species_id) or pretty_identifier(identifier)
        types = get_types(pokemon_id)
        stats = get_stats(pokemon_id)
        if not types:
            raise ValueError(f"No Pokémon type data found for #{species_id} ({name}).")
        if set(stats) != set(STAT_LABELS.values()):
            missing = sorted(set(STAT_LABELS.values()) - set(stats))
            raise ValueError(f"Missing base stats for #{species_id} ({name}): {', '.join(missing)}")

        entry: dict[str, Any] = {
            "id": species_id,
            "name": name,
            "types": types,
            "generation": generation,
            "sprite": make_sprite_url(identifier, generation),
            "stats": stats,
            "identifier": identifier,
            "speciesId": species_id,
            "pokemonId": pokemon_id,
            "spriteKey": str(pokemon_id),
            "height": int_value(pokemon.get("height")),
            "weight": int_value(pokemon.get("weight")),
            "baseExperience": int_or_none(pokemon.get("base_experience")),
            "captureRate": int_value(species.get("capture_rate")),
            "baseHappiness": int_value(species.get("base_happiness")),
            "genderRate": int_value(species.get("gender_rate"), default=-1),
            "hatchCounter": int_value(species.get("hatch_counter")),
            "evolvesFromSpeciesId": int_or_none(species.get("evolves_from_species_id")),
            "evolutionChainId": int_or_none(species.get("evolution_chain_id")),
            "isBaby": bool_value(species.get("is_baby")),
            "isLegendary": bool_value(species.get("is_legendary")),
            "isMythical": bool_value(species.get("is_mythical")),
            "hasGenderDifferences": bool_value(species.get("has_gender_differences")),
        }
        catalog.append(entry)

    actual_ids = [entry["id"] for entry in catalog]
    expected_ids = list(range(1, min(max_species, len(target_species)) + 1))
    if actual_ids != expected_ids:
        missing = sorted(set(expected_ids) - set(actual_ids))[:20]
        raise ValueError(
            f"The requested species range is not complete. Missing IDs (first 20): {missing}. "
            "Check --max-species / --max-generation and the PokeAPI data revision."
        )

    forms_catalog: list[dict[str, Any]] = []
    if include_forms:
        pokemon_forms = read_csv(csv_dir, "pokemon_forms.csv")
        form_names_rows = read_csv(csv_dir, "pokemon_form_names.csv", required=False)
        version_group_rows = read_csv(csv_dir, "version_groups.csv", required=False)
        version_group_generations = {
            int_value(row.get("id")): int_value(row.get("generation_id"))
            for row in version_group_rows
            if int_or_none(row.get("id")) is not None
        }
        english_form_names = {
            int_value(row.get("pokemon_form_id")): {
                "formName": row.get("form_name", "").strip(),
                "pokemonName": row.get("pokemon_name", "").strip(),
            }
            for row in form_names_rows
            if row.get("local_language_id") == POKEAPI_ENGLISH_LANGUAGE_ID
        }
        seen_form_keys: set[tuple[int, int]] = set()

        for form in pokemon_forms:
            form_id = int_or_none(form.get("id"))
            pokemon_id = int_or_none(form.get("pokemon_id"))
            if form_id is None or pokemon_id is None or pokemon_id not in pokemon_by_id:
                continue
            pokemon = pokemon_by_id[pokemon_id]
            species_id = int_value(pokemon.get("species_id"))
            species = species_by_id.get(species_id)
            if species is None or species_id > max_species:
                continue
            generation = int_value(species.get("generation_id"), default=1)
            if generation > max_generation:
                continue
            version_group_id = int_or_none(form.get("introduced_in_version_group_id"))
            introduced_generation = (
                version_group_generations.get(version_group_id)
                if version_group_id is not None else None
            )
            if introduced_generation is not None and introduced_generation > max_generation:
                continue

            # A non-default Pokemon record (e.g. Deoxys Attack) is an alternate
            # form even when PokeAPI marks its own form row as the default.
            is_alternate_pokemon = (
                pokemon_id != species_id or not bool_value(pokemon.get("is_default"))
            )
            is_alternate_form = not bool_value(form.get("is_default"))
            if not (is_alternate_pokemon or is_alternate_form):
                continue

            key = (pokemon_id, form_id)
            if key in seen_form_keys:
                continue
            seen_form_keys.add(key)

            species_name = english_names.get(species_id) or pretty_identifier(
                species.get("identifier", "")
            )
            identifier = form.get("identifier", "") or pokemon.get("identifier", "")
            form_identifier = form.get("form_identifier", "") or ""
            localized = english_form_names.get(form_id, {})
            form_name = (
                pretty_identifier(form_identifier)
                if form_identifier else localized.get("formName", "")
            )
            display_name = f"{species_name} ({form_name})" if form_name else species_name
            sprite_key = (
                f"{species_id}-{form_identifier}"
                if pokemon_id == species_id and form_identifier else str(pokemon_id)
            )
            types = get_types(pokemon_id)
            # Arceus and Silvally change type to match their Plate/Memory form.
            type_names_by_slug = {
                row.get("identifier", "").lower(): types_by_id[int_value(row.get("id"))]
                for row in type_rows
                if int_or_none(row.get("id")) is not None
                and int_value(row.get("id")) in types_by_id
            }
            if species_id in (493, 773) and form_identifier.lower() in type_names_by_slug:
                types = [type_names_by_slug[form_identifier.lower()]]
            if not types:
                continue
            stats = get_stats(pokemon_id)
            if not stats:
                continue

            form_entry: dict[str, Any] = {
                "id": pokemon_id,
                "formId": form_id,
                "speciesId": species_id,
                "speciesName": species_name,
                "name": display_name,
                "identifier": identifier,
                "formIdentifier": form_identifier,
                "spriteKey": sprite_key,
                "generation": generation,
                "introducedInVersionGroupId": version_group_id,
                "isDefaultPokemon": bool_value(pokemon.get("is_default")),
                "isDefaultForm": bool_value(form.get("is_default")),
                "isBattleOnly": bool_value(form.get("is_battle_only")),
                "isMega": bool_value(form.get("is_mega")),
                "types": types,
                "stats": stats,
                "height": int_value(pokemon.get("height")),
                "weight": int_value(pokemon.get("weight")),
                "baseExperience": int_or_none(pokemon.get("base_experience")),
            }
            forms_catalog.append(form_entry)

        forms_catalog.sort(
            key=lambda entry: (entry["speciesId"], entry["id"], entry["formId"])
        )

    return catalog, forms_catalog


def main() -> int:
    args = parse_args()
    if args.max_species < 1:
        print("--max-species must be at least 1", file=sys.stderr)
        return 2
    if args.max_generation < 1:
        print("--max-generation must be at least 1", file=sys.stderr)
        return 2

    try:
        csv_dir = find_csv_dir(args.pokeapi_dir)
        catalog, forms = build_catalogs(
            csv_dir,
            max_species=args.max_species,
            max_generation=args.max_generation,
            include_forms=not args.skip_forms,
        )
        output_dir = args.output_dir.expanduser().resolve()
        output_dir.mkdir(parents=True, exist_ok=True)
        pokemon_path = output_dir / "pokemon.json"
        pokemon_path.write_text(
            json.dumps(catalog, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        print(f"Wrote {len(catalog)} base species to {pokemon_path}")
        forms_path = None
        if not args.skip_forms:
            forms_path = output_dir / "pokemon-forms.json"
            forms_path.write_text(
                json.dumps(forms, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            print(f"Wrote {len(forms)} alternate forms to {forms_path}")

        pokemon_sha256 = hashlib.sha256(pokemon_path.read_bytes()).hexdigest()
        forms_sha256 = hashlib.sha256(forms_path.read_bytes()).hexdigest() if forms_path else None
        data_version_source = pokemon_sha256 + (":" + forms_sha256 if forms_sha256 else "")
        manifest = {
            "schemaVersion": 1,
            "dataVersion": hashlib.sha256(data_version_source.encode("utf-8")).hexdigest()[:24],
            "source": {
                "repository": args.source_repository,
                "branch": args.source_branch,
                "commit": args.source_commit,
            },
            "scope": {
                "maxSpecies": args.max_species,
                "maxGeneration": args.max_generation,
                "language": "en",
            },
            "pokemon": {
                "file": "pokemon.json",
                "count": len(catalog),
                "sha256": pokemon_sha256,
            },
            "forms": (
                {
                    "file": "pokemon-forms.json",
                    "count": len(forms),
                    "sha256": forms_sha256,
                }
                if forms_path else None
            ),
        }
        manifest_path = output_dir / "manifest.json"
        manifest_path.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        print(f"Wrote data manifest {manifest_path} (version {manifest['dataVersion']})")
        print(f"Source CSV directory: {csv_dir}")
        return 0
    except (FileNotFoundError, ValueError, OSError, csv.Error) as exc:
        print(f"PokeAPI import failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
