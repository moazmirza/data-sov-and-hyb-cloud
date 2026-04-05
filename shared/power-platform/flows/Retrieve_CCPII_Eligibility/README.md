# Retrieve_CCPII_Eligibility

## Purpose
Retrieves CC/PII eligibility context for data products by combining Power BI lookup/output shaping logic and returns a structured response to the agent.

## Trigger
- Trigger name: manual
- Trigger type: Request

## Action sequence
1. Initialize_variable_1
2. Initialize_variable_2
3. Initialize_variable_3
4. Initialize_variable_4
5. Initialize_variable_5
6. pbiDataProductsLookup
7. Initialize_variable_6
8. composeDpRows
9. Condition
10. Condition_1
11. Respond_to_the_agent
12. Initialize_variable
13. Initialize_variable_7
14. Initialize_variable_8
15. Initialize_variable_9
16. Initialize_variable_10

## Connector dependencies
- shared_powerbi (Power BI connector)

## Expected invocation pattern
- Typical caller: Copilot via Topic or Tool
- Typical input: data product filters/identifiers in request payload
- Typical output: eligibility data and derived response properties

## Notes
- This flow is read-oriented and suitable for synchronous agent lookups.
