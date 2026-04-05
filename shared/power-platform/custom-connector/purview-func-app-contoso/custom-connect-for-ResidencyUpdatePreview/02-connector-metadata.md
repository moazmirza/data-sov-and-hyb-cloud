# Connector Metadata - purview_residency_update_preview

## Purpose
Build a no-write preview plan for residency change.

## Operation registration
- Operation ID: purview_residency_update_preview
- Relative path: /api/purview_residency_update_preview
- Method: POST
- Content type: application/json

## Where to set this in GUI
1. Data > Custom connectors > Your connector.
2. Definition tab > New action (or edit existing).
3. Enter Summary and Operation ID.
4. Add request schema and response schema from 01-openapi.operation.json.
