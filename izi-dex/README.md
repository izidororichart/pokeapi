# IZI Dex encounter bundle

This directory contains the public JSON bundle consumed by IZI Dex.

## Encounter sources

- The base `encounters.json` catalog is generated from the upstream PokéAPI CSV dataset.
- `encounters-supplemental.json` merges additional encounter sources that are not available in PokéAPI's base encounter tables:
  - PokeDB export data for Brilliant Diamond, Shining Pearl, Legends: Arceus, Scarlet and Violet.
  - Curated Legends: Z-A Wild Zone and guaranteed Alpha encounter data.
- The app merges the base and supplemental catalogs at startup. Checksums in `manifest.json` control caching and refresh behavior.
- The supplemental catalog preserves source and coverage metadata so incomplete joins and unmatched locations remain visible during maintenance.

## Automatic refresh

The **Refresh IZI Dex data bundle** GitHub Actions workflow runs daily and whenever relevant data/exporter files change on `master`. It:

1. Builds the base Pokémon and encounter catalogs from the upstream PokéAPI CSV dataset on scheduled runs, or this fork's CSV files on pushes/manual runs.
2. Downloads the five public PokeDB JSON export tables to a temporary runner folder.
3. Validates the downloaded tables before importing them.
4. Merges PokeDB's supported modern-game encounters with the existing supplemental catalog, preserving the curated Legends: Z-A entries.
5. Updates the manifest checksums and commits the generated bundle only when its contents change.

The raw PokeDB tables are **not** committed to this repository.

## Manual refresh

To run the same process locally, first obtain a PokeAPI repository clone and install Python 3.12 or newer. Then run:

```bash
python scripts/export_izi_dex_data.py \
  --pokeapi-dir . \
  --max-species 809 \
  --max-generation 7 \
  --output-dir izi-dex/v1

python scripts/export_izi_dex_encounters.py \
  --pokeapi-dir . \
  --max-species 898 \
  --max-generation 8 \
  --output-dir izi-dex/v1

python scripts/download_izi_dex_pokedb.py --output-dir data/pokedb

python scripts/import_izi_dex_pokedb.py \
  --pokedb-dir data/pokedb \
  --pokeapi-csv-dir data/v2/csv \
  --output-dir izi-dex/v1
```

The importer requires these PokeDB tables:

- `encounters.json`
- `pokemon_forms.json`
- `location_areas.json`
- `locations.json`
- `encounter_methods.json`

The download script validates that each export is a JSON array with a plausible number of records before the importer runs. Local raw files live in `data/pokedb/`, which is ignored by Git.

## Coverage and limitations

- Let's Go and Sword/Shield, including their expansion version groups, use the base PokéAPI encounter exporter.
- Brilliant Diamond, Shining Pearl, Legends: Arceus, Scarlet and Violet use the supplemental PokeDB importer.
- Legends: Z-A uses the curated Wild Zone data in the supplemental catalog. Its zone reference levels are not guaranteed individual species levels; only known guaranteed Alpha level ranges are shown as exact levels.
- PokeDB locations that cannot be joined to a PokeAPI location ID are retained with their source slug and name, but they need a matching Companion guide location ID to appear in the ordered walkthrough.
- A missing level, probability, or condition remains unspecified rather than being inferred.

## PokeDB attribution and use

PokeDB asks projects using its export data to link back to PokeDB and identify it as the source. Its published guidance allows educational, research and non-commercial use; commercial applications require contacting PokeDB for a license. See [PokeDB Data Export](https://pokedb.org/data-export/) before redistributing or using the imported data commercially.
