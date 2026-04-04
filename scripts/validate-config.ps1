param(
  [string]$ConfigPath = "templates/config.template.json"
)

if (-not (Test-Path $ConfigPath)) {
  throw "Config file not found: $ConfigPath"
}

Write-Host "Validation scaffold passed for $ConfigPath"
