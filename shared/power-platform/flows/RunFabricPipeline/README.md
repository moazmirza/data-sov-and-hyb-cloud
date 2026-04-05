# RunFabricPipeline

## Purpose
Invokes a Fabric pipeline endpoint through HTTP and returns execution response details to the caller.

## Trigger
- Trigger name: manual
- Trigger type: Request

## Action sequence
1. Invoke_an_HTTP_request
2. URL

## Connector dependencies
- shared_webcontents (HTTP/Web Contents connector)

## Expected invocation pattern
- Typical caller: Copilot via Topic or Tool
- Typical input: pipeline trigger parameters and endpoint context
- Typical output: pipeline invocation status and response payload details

## Notes
- This flow is operational and may trigger downstream processing depending on payload.
