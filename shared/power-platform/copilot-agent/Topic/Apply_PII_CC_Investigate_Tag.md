# Apply PII CC Investigate Tag

## Status

- Enabled in screenshot: Yes
- Component type: Topic

## Purpose

This topic evaluates whether a selected data product has exactly one eligible CC/PII Azure resource that requires investigation tagging, presents a preview to the user, asks for confirmation, and then applies the tag and sends a notification.

## High-level conversation flow

1. Prompt the user for the target data product.
2. Call the `Retrieve_CCPII_Eligibility` flow.
3. Validate that the data product match is verified.
4. Validate that exactly one eligible resource exists.
5. Show preview details to the user.
6. Ask for explicit confirmation.
7. If confirmed, call the `Apply_CCPII_Tag_And_Notify` flow.
8. Return success/failure messaging to the user.

## Underlying flow dependencies

- [../../flows/Retrieve_CCPII_Eligibility/README.md](../../flows/Retrieve_CCPII_Eligibility/README.md)
- [../../flows/Apply_CCPII_Tag_And_Notify/README.md](../../flows/Apply_CCPII_Tag_And_Notify/README.md)

## Notes

- This is a guarded topic with explicit user confirmation before making changes.
- It combines read/eligibility logic with a write/apply operation.
- It is a good example of a Topic orchestrating multiple lower-level flows.