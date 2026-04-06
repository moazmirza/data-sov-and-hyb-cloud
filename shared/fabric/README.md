# Shared Fabric Assets

This folder stores Microsoft Fabric implementation assets, grouped by artifact type so they can be reused across environments.

## Folder layout

- `semantic-models/`: Semantic model definitions (`.pbism`, `.tmdl`, related metadata).
- `reports/`: Power BI/Fabric report definitions and report resources.
- `notebooks/`: Fabric notebook code and notebook-related assets.
- `pipelines/`: Data pipeline definitions and orchestration assets.
- `lakehouses/`: Lakehouse definitions and supporting metadata.
- `data-agents/`: Data agent definitions and configuration.
- `repro/`: Reproducible exports and sanitized packs used to recreate or validate end-to-end scenarios.

## How these folders relate

Most Fabric solutions follow this flow:

1. `notebooks/` and `pipelines/` ingest or transform data into `lakehouses/`.
2. `semantic-models/` model that prepared data.
3. `reports/` visualize the model for users.
4. `data-agents/` consume model/report context for guided actions and insights.
5. `repro/` keeps a portable, documented snapshot so the same setup can be replayed in another tenant or environment.

Keep each artifact in its type-specific folder and use `repro/` for complete, reproducible scenario packs.
