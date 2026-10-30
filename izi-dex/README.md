# IZI Dex encounter bundle

This directory contains the public JSON bundle consumed by IZI Dex.

## Encounter sources

- The base `encounters.json` catalog is generated from the upstream PokéAPI CSV dataset.
- `encounters-supplemental.json` contains additional game-specific encounter sources that are not present in the upstream PokéAPI encounter tables. The initial supplemental game is Legends: Z-A.
- The app merges the base and supplemental catalogs at startup. The checksum in `manifest.json` controls caching and refresh behavior.

## Refresh the base PokéAPI data

Run the repository workflow **Refresh IZI Dex data bundle** or execute the exporters with the repository's CSV data. The encounter exporter includes official Let's Go and Sword/Shield version groups and their expansions; the workflow generates data through National Dex #898 / Generation VIII.

## Import PokeDB supplemental data

PokeDB's export tables are not redistributed in this repository. Download the required JSON tables from [PokeDB Data Export](https://pokedb.org/data-export/) into a local folder (default: `data/pokedb/`):

- `encounters.json`
- `pokemon_forms.json`
- `location_areas.json`
- `locations.json`
- `encounter_methods.json`

The importer also uses this repository's `data/v2/csv/locations.csv` and, when available, `location_names.csv` to map locations to the IDs used by IZI Dex.

Preview the transformation:

```bash
python scripts/import_izi_dex_pokedb.py --dry-run
```

Write the merged supplemental catalog and update its checksum in `manifest.json`:

```bash
python scripts/import_izi_dex_pokedb.py
```

The importer covers Brilliant Diamond, Shining Pearl, Legends: Arceus, Scarlet and Violet. It preserves existing supplemental game data, including the initial Legends: Z-A catalog. Unmapped locations and incomplete joins are printed in the import report rather than silently assigned invented IDs.

## PokeDB attribution and use

PokeDB asks projects using its export data to link back to PokeDB and identify it as the source. Its published guidance allows educational, research and non-commercial use; commercial applications require contacting PokeDB for a license. See [PokeDB Data Export](https://pokedb.org/data-export/) before redistributing or using the imported data commercially.
