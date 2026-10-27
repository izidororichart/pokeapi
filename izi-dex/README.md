# IZI Dex data bundle

This directory contains a generated, versioned data contract for IZI Dex. The app reads the small manifest first and then downloads the matching Pokémon catalog. It does not query the PokeAPI at runtime.

## Published bundle

- `v1/manifest.json`: schema version, data version, source commit, supported scope, and checksums.
- `v1/pokemon.json`: 809 base species through Generation VII.
- `v1/pokemon-forms.json`: alternate forms available within the same scope, including form identifiers and sprite keys.

The versioned directory name (`v1`) represents the JSON contract, not the source dataset revision. The `dataVersion` in the manifest is a content hash and changes when the exported JSON changes.

## Automatic refresh

The workflow at `.github/workflows/izi-dex-data.yml` regenerates the bundle when relevant PokeAPI CSVs change on `master`, or when manually started using **Actions → Refresh IZI Dex data bundle → Run workflow**. It commits only when generated files changed.

This updates the bundle whenever a change reaches this repository. It does **not** automatically sync this fork from upstream `PokeAPI/pokeapi`; after syncing the fork, the workflow runs if one of the source CSVs changed.

The current export intentionally stays limited to National Dex #001–#809 / Generations I–VII so it remains compatible with the current IZI Dex Web app. A future schema or scope change should be published under a new versioned directory and adopted by the app deliberately.

## License and attribution

This is a derived data export based on the PokeAPI database. See the parent repository's license and attribution guidance.
