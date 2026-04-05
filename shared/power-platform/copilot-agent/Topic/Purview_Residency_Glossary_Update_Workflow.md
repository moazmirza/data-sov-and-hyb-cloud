# Purview Residency Glossary Update Workflow

## Status

- Enabled in screenshot: Yes
- Component type: Topic

## Purpose

This topic runs a controlled Purview residency glossary update workflow for a single data product. It checks dashboard eligibility, prepares a preview of the update, and applies the change only after explicit user confirmation.

## High-level conversation flow

1. Accept contextual inputs for `dataProductId`, `targetResidencyCode`, and `dataProductName`.
2. Call `RetrieveSovDashboardInfo` to obtain dashboard and eligibility context.
3. Verify that eligible residency-update items exist.
4. If product-specific inputs are available, call `ResidencyUpdatePreview_wrapped`.
5. If preview is valid and no conflict is detected, present the preview to the user.
6. Ask for explicit confirmation.
7. If confirmed, call `ResidencyUpdateApply_wrapped`.
8. Return success/failure messaging to the user.

## Underlying flow dependencies

- [../../flows/RetrieveSovDashboardInfo/README.md](../../flows/RetrieveSovDashboardInfo/README.md)
- [../../flows/ResidencyUpdatePreview_wrapped/README.md](../../flows/ResidencyUpdatePreview_wrapped/README.md)
- [../../flows/ResidencyUpdateApply_wrapped/README.md](../../flows/ResidencyUpdateApply_wrapped/README.md)

## Notes

- This topic is the main conversational orchestration layer for safe Purview residency updates.
- It intentionally separates dashboard discovery, preview, and apply steps.
- The apply step is gated behind preview success and explicit confirmation.