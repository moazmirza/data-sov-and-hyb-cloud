# RunFabricPipeline

## Status

- Enabled in screenshot: Yes
- Tool type: Flow

## Purpose

Triggers the Fabric `Data Sovereignty refresh` pipeline to refresh the latest snapshot tables used by downstream analytics/reporting.

## Backing flow

- [../../flows/RunFabricPipeline/README.md](../../flows/RunFabricPipeline/README.md)

## Intended usage

- Direct agent tool invocation when the user asks to refresh compliance scan/dashboard data.

## Notes

- This is an operational trigger tool.
- It may start downstream data refresh processing rather than returning final business results immediately.