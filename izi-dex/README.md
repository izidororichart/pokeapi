# IZI Dex data bundle

This directory contains a generated, versioned data contract for IZI Dex. The app reads the small manifest first and then downloads the matching Pokémon catalog. It does not query the PokeAPI at runtime.

## Published bundle

- `v1/manifest.json`: schema version, data version, source commit, supported scope, and checksums.
- `v1/pokemon.json`: 809 base species through Generation VII.
- `v1/pokemon-forms.json`: alternate forms available within the same scope, including form identifiers and sprite keys.

The versioned directory name (`v1`) represents the JSON contract, not the source dataset revision. The `dataVersion` in the manifest is a content hash and changes when the exported JSON changes.

## Automatic refresh

The workflow at `.github/workflows/izi-dex-data.yml` regenerates the bundle immediately when relevant CSVs change on this fork, when manually started using **Actions → Refresh IZI Dex data bundle → Run workflow**, and once daily from the upstream `PokeAPI/pokeapi` repository. It commits only when generated files changed.

The scheduled run reads upstream CSVs into a temporary directory and publishes the compatible IZI Dex bundle here. It does not merge or overwrite the rest of this fork. A push-triggered run still uses the CSVs in this fork.

The current export intentionally stays limited to National Dex #001–#809 / Generations I–VII so it remains compatible with the current IZI Dex Web app. A future schema or scope change should be published under a new versioned directory and adopted by the app deliberately.

## License and attribution

This is a derived data export based on the PokeAPI database. See the parent repository's license and attribution guidance.
