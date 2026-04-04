# Shared Data Model

The solution assumes a shared model for ingesting governance signals and exposing them through reporting and agent experiences.

## Common Model Concepts

- Source inventory tables
- Compliance or control scoring tables
- Dimension tables for environment, resource type, region, and ownership
- Measures surfaced in semantic models and reports

Module-specific scoring logic should extend this shared model rather than redefine it from scratch.
