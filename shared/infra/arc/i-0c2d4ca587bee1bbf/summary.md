# Arc Machine Summary

Purpose: baseline evidence for Arc machine `i-0c2d4ca587bee1bbf` used for governance, compliance snapshots, and drift comparison over time.

## Snapshot
- Resource group: `rg_arc_eu_contoso`
- Location: `germanywestcentral`
- Connection status: `Disconnected`
- OS: `windows 10.0.26100.32230`

## Associated Tags
- `resource-origin=arc`
- `sovereignty-zone=comprehensive`

## OS Patch Status
- Direct OS patch status field: not present in `arc-machine.json`.
- Update extension signal: `WindowsOsUpdateExtension` not present.
- Policy-derived patch signal from `policy-states.json`: `2` patch-related records (`systemupdatesv2monitoring` = compliant, `systemupdatesautoassessmentmode` = non-compliant).
- Overall policy counts: `3` compliant, `5` non-compliant.
