# Arc Machine Summary

Purpose: baseline evidence for Arc machine `i-05c131818f13b0057` used for governance, compliance snapshots, and drift comparison over time.

## Snapshot
- Resource group: `rg_arc_us_contoso`
- Location: `eastus2`
- Connection status: `Disconnected`
- OS: `windows 10.0.20348.4773`

## Associated Tags
- `dataproductid=<DATAPRODUCT_ID>`
- `resource-origin=arc`
- `sovereignty-zone=comprehensive`

## OS Patch Status
- Direct OS patch status field: not present in `arc-machine.json`.
- Update extension signal: `WindowsOsUpdateExtension` present; latest captured assessment message indicates `0 patches were found`.
- Policy-derived patch signal from `policy-states.json`: `2` patch-related records (`systemupdatesv2monitoring` = compliant, `systemupdatesautoassessmentmode` = non-compliant).
- Overall policy counts: `5` compliant, `5` non-compliant.
