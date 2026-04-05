# ResidencyUpdatePreview_wrapped

## Status

- Enabled in screenshot: Yes
- Tool type: Flow

## Purpose

Runs the Purview residency preview flow in dry-run mode and returns typed outputs for controlled branching before any apply action.

## Backing flow

- [../../flows/ResidencyUpdatePreview_wrapped/README.md](../../flows/ResidencyUpdatePreview_wrapped/README.md)

## Intended usage

- Direct agent tool invocation when preview data is needed.
- Typically also called from the `Purview Residency Glossary Update Workflow` topic.

## Notes

- This is a preview-only tool.
- It is the safe pre-check before any update action.