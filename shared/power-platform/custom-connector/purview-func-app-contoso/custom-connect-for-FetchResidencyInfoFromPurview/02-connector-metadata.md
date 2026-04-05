# Connector Metadata - purview_residency

## Purpose
Resolve current Purview residency term for a data product.

## Operation registration
- Operation ID: purview_residency
- Relative path: /api/purview_residency
- Method: POST
- Content type: application/json

## Where to set this in GUI
1. Data > Custom connectors > Your connector.
2. Definition tab > New action (or edit existing).
3. Enter Summary and Operation ID.
4. Add request schema and response schema from 01-openapi.operation.json.
