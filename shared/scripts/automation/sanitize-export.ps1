param(
  [string]$InputPath,
  [string]$OutputPath = "sanitized-output.json"
)

if (-not $InputPath) {
  throw "Provide -InputPath"
}

Write-Host "Sanitize export scaffold"
Write-Host "Input: $InputPath"
Write-Host "Output: $OutputPath"
Write-Host "Implement redaction for IDs, emails, URLs, and keys before publishing."
