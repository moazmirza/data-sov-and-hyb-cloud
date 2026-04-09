param(
    [string]$RootPath = (Split-Path -Parent $PSScriptRoot)
)

$ErrorActionPreference = "Stop"

$root = (Resolve-Path -LiteralPath $RootPath).Path
$sanitizedRoot = Join-Path $root "sanitized"
$automationRoot = Join-Path $root "_automation"
$validationReportPath = Join-Path $automationRoot "sanitization-validation-report.json"

if (-not (Test-Path -LiteralPath $sanitizedRoot)) {
    throw "Sanitized path not found: $sanitizedRoot"
}

$forbiddenLiterals = @(
    "66d5a770-33db-4274-a2fc-dad6a76b7c6f",
    "30c6fd04-b13e-43b1-906e-eed50b203685",
    "16b3c013-d300-468d-ac64-7eda0820b6d3",
    "<SOURCE_SUBSCRIPTION_ID_1>",
    "<SOURCE_SUBSCRIPTION_ID_2>",
    "05d107b2-6b35-48e5-93fe-824663d5fb8e",
    "8c98bd9e-6f84-44a6-b663-7ae2aec7135d",
    "a99598e5-cd1e-49bf-a3d4-a6ab04f23b12",
    "789e24ac-10c1-41c4-bea6-73e5728cce00",
    "fec2dea8-4aa7-4903-bab4-7139a09b9056",
    "https://func-purv-contoso-gkcbavefesdqhre2.eastus2-01.azurewebsites.net",
    "https://kv-purview-sap.vault.azure.net/",
    "<SOURCE_OWNER_EMAIL>",
    "<SOURCE_WORKSPACE_NAME>",
    "AT64MMB6WGYUHEDO53KQWIBWQU-OCT5KZW3GN2EFIX43LLKO234N4.datawarehouse.fabric.microsoft.com",
    "adlsfordfsapfabric.dfs.core.windows.net",
    "<SOURCE_TEAMS_CHANNEL_ID>"
)

$forbiddenPatterns = @(
    [ordered]@{ Name = "TenantIdAssignment"; Regex = '(?im)^(TENANT_ID|tenant_id)\s*=\s*"[0-9a-fA-F-]{36}"' },
    [ordered]@{ Name = "ClientIdAssignment"; Regex = '(?im)^(CLIENT_ID|client_id|RESOURCE_APP_CLIENT_ID)\s*=\s*"[0-9a-fA-F-]{36}"' },
    [ordered]@{ Name = "SubscriptionGuidArray"; Regex = '(?im)subscriptions?\s*[=:]\s*\[[^\]]*[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}[^\]]*\]' },
    [ordered]@{ Name = "OwnerEmail"; Regex = '(?im)OWNER_EMAIL.*@[A-Za-z0-9.-]+' }
)

$textExtensions = @(
    ".json", ".md", ".txt", ".py", ".tmdl", ".pbir", ".pbism", ""
)
$textFileNames = @(".platform", ".schedules")

$findings = New-Object System.Collections.Generic.List[object]

$files = Get-ChildItem -LiteralPath $sanitizedRoot -Recurse -File
foreach ($file in $files) {
    $extension = [System.IO.Path]::GetExtension($file.Name)
    $isTextCandidate = $textExtensions -contains $extension -or $textFileNames -contains $file.Name
    if (-not $isTextCandidate) {
        continue
    }

    $content = Get-Content -LiteralPath $file.FullName -Raw -ErrorAction SilentlyContinue
    if ($null -eq $content) {
        continue
    }

    $relativePath = $file.FullName.Substring($sanitizedRoot.Length).TrimStart('\\')

    foreach ($literal in $forbiddenLiterals) {
        if ($content.Contains($literal)) {
            $findings.Add([ordered]@{
                file = $relativePath
                type = "literal"
                rule = $literal
            })
        }
    }

    foreach ($pattern in $forbiddenPatterns) {
        if ([regex]::IsMatch($content, $pattern.Regex)) {
            $findings.Add([ordered]@{
                file = $relativePath
                type = "pattern"
                rule = $pattern.Name
            })
        }
    }
}

$report = [ordered]@{
    generatedAtUtc = (Get-Date).ToUniversalTime().ToString("o")
    sanitizedPath = $sanitizedRoot
    totalFindings = $findings.Count
    findings = $findings
}

$reportJson = $report | ConvertTo-Json -Depth 10
Set-Content -LiteralPath $validationReportPath -Value $reportJson -Encoding UTF8

if ($findings.Count -gt 0) {
    Write-Error "Sanitization validation failed. Findings: $($findings.Count). See $validationReportPath"
    exit 1
}

Write-Output "Sanitization validation passed."
Write-Output "Report: $validationReportPath"
