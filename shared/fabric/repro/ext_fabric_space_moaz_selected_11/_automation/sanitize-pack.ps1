param(
    [string]$RootPath = (Split-Path -Parent $PSScriptRoot)
)

$ErrorActionPreference = "Stop"

$root = (Resolve-Path -LiteralPath $RootPath).Path
$sanitizedRoot = Join-Path $root "sanitized"
$automationRoot = Join-Path $root "_automation"
$sanitizationReportPath = Join-Path $automationRoot "sanitization-report.json"

if (Test-Path -LiteralPath $sanitizedRoot) {
    Remove-Item -LiteralPath $sanitizedRoot -Recurse -Force
}
New-Item -ItemType Directory -Path $sanitizedRoot -Force | Out-Null

# Copy source tree except sanitized and automation folders, and transient temp files.
$sourceFiles = Get-ChildItem -LiteralPath $root -Recurse -File | Where-Object {
    $_.FullName -notlike "$sanitizedRoot*" -and
    $_.FullName -notlike "$automationRoot*" -and
    $_.Name -notlike ".tmp*"
}

foreach ($file in $sourceFiles) {
    $relativePath = $file.FullName.Substring($root.Length).TrimStart('\\')
    $targetPath = Join-Path $sanitizedRoot $relativePath
    $targetDir = Split-Path -Parent $targetPath
    if (-not (Test-Path -LiteralPath $targetDir)) {
        New-Item -ItemType Directory -Path $targetDir -Force | Out-Null
    }
    Copy-Item -LiteralPath $file.FullName -Destination $targetPath -Force
}

# Build deterministic replacements for selected artifact IDs from manifest.
$exactReplacements = [ordered]@{
    "66d5a770-33db-4274-a2fc-dad6a76b7c6f" = "<FABRIC_WORKSPACE_ID>"
    "30c6fd04-b13e-43b1-906e-eed50b203685" = "<TENANT_ID>"
    "16b3c013-d300-468d-ac64-7eda0820b6d3" = "<TENANT_ID_2>"
    "17d52165-9be5-418b-a7f4-6b3e7d82d155" = "<SUBSCRIPTION_ID_1>"
    "3557eaf8-74a8-4e8a-b260-b28c90fc9379" = "<SUBSCRIPTION_ID_2>"
    "05d107b2-6b35-48e5-93fe-824663d5fb8e" = "<APP_CLIENT_ID>"
    "8c98bd9e-6f84-44a6-b663-7ae2aec7135d" = "<APP_CLIENT_ID_2>"
    "a99598e5-cd1e-49bf-a3d4-a6ab04f23b12" = "<APP_CLIENT_ID_3>"
    "789e24ac-10c1-41c4-bea6-73e5728cce00" = "<APP_CLIENT_ID_4>"
    "fec2dea8-4aa7-4903-bab4-7139a09b9056" = "<RESOURCE_APP_CLIENT_ID>"
    "033d0650-add4-471d-a1d7-66cdfaa42700" = "<FABRIC_ENVIRONMENT_ID>"
    "c8273dfa-93e9-4a6a-8358-fdb8152bc658" = "<PURVIEW_GLOSSARY_PARENT_ID>"
    "https://func-purv-contoso-gkcbavefesdqhre2.eastus2-01.azurewebsites.net" = "https://<FUNCTION_APP>.azurewebsites.net"
    "https://kv-purview-sap.vault.azure.net/" = "https://<KEYVAULT_NAME>.vault.azure.net/"
    "momirza@MngEnvMCAP960910.onmicrosoft.com" = "<OWNER_EMAIL>"
    "your_email@yourdomain.com" = "<OWNER_EMAIL>"
    "19:CsqyIBpg9_oQvmxiaZG6z_8B5wApph-uS7figeiPqpc1@thread.tacv2" = "<TEAMS_CHANNEL_ID>"
    "ext_fabric_space_moaz" = "<SOURCE_WORKSPACE_NAME>"
    "AT64MMB6WGYUHEDO53KQWIBWQU-OCT5KZW3GN2EFIX43LLKO234N4.datawarehouse.fabric.microsoft.com" = "<FABRIC_SQL_ENDPOINT_HOST>"
    "adlsfordfsapfabric.dfs.core.windows.net" = "<EXTERNAL_ADLS_HOST>"
}

$manifestPath = Join-Path $root "manifest.selected-items.json"
if (Test-Path -LiteralPath $manifestPath) {
    $manifest = Get-Content -LiteralPath $manifestPath -Raw | ConvertFrom-Json
    $index = 1
    foreach ($item in $manifest) {
        if ($item.id -and -not $exactReplacements.Contains($item.id)) {
            $exactReplacements[$item.id] = "<FABRIC_ITEM_ID_$index>"
            $index += 1
        }
    }
}

$rules = @(
    @{
        Name = "EmailReplacement"
        Regex = [regex]"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\\.[A-Za-z]{2,}"
        Evaluator = { param($m) "<OWNER_EMAIL>" }
    },
    @{
        Name = "FunctionAppUrlReplacement"
        Regex = [regex]"https://[A-Za-z0-9-]+\\.azurewebsites\\.net"
        Evaluator = { param($m) "https://<FUNCTION_APP>.azurewebsites.net" }
    },
    @{
        Name = "KeyVaultUrlReplacement"
        Regex = [regex]"https://[A-Za-z0-9-]+\\.vault\\.azure\\.net/?"
        Evaluator = { param($m) "https://<KEYVAULT_NAME>.vault.azure.net/" }
    }
)

# Text-like files only. Keep binary report assets (png) untouched.
$textExtensions = @(
    ".json", ".md", ".txt", ".py", ".tmdl", ".pbir", ".pbism", ""
)
$textFileNames = @(".platform", ".schedules")

$changedFileCount = 0
$replacementCountByRule = [ordered]@{}

foreach ($key in $exactReplacements.Keys) {
    $replacementCountByRule["Exact:$key"] = 0
}
foreach ($rule in $rules) {
    $replacementCountByRule["Regex:$($rule.Name)"] = 0
}

$sanitizedFiles = Get-ChildItem -LiteralPath $sanitizedRoot -Recurse -File
foreach ($file in $sanitizedFiles) {
    $extension = [System.IO.Path]::GetExtension($file.Name)
    $isTextCandidate = $textExtensions -contains $extension -or $textFileNames -contains $file.Name
    if (-not $isTextCandidate) {
        continue
    }

    $content = Get-Content -LiteralPath $file.FullName -Raw -ErrorAction SilentlyContinue
    if ($null -eq $content) {
        continue
    }

    $updated = $content

    foreach ($key in $exactReplacements.Keys) {
        if ($updated.Contains($key)) {
            $occurrences = [regex]::Matches($updated, [regex]::Escape($key)).Count
            if ($occurrences -gt 0) {
                $updated = $updated.Replace($key, $exactReplacements[$key])
                $replacementCountByRule["Exact:$key"] += $occurrences
            }
        }
    }

    foreach ($rule in $rules) {
        $matches = $rule.Regex.Matches($updated)
        if ($matches.Count -gt 0) {
            $updated = $rule.Regex.Replace($updated, $rule.Evaluator)
            $replacementCountByRule["Regex:$($rule.Name)"] += $matches.Count
        }
    }

    if ($updated -ne $content) {
        Set-Content -LiteralPath $file.FullName -Value $updated -Encoding UTF8
        $changedFileCount += 1
    }
}

$report = [ordered]@{
    generatedAtUtc = (Get-Date).ToUniversalTime().ToString("o")
    rootPath = $root
    sanitizedPath = $sanitizedRoot
    sourceFilesCopied = $sourceFiles.Count
    filesUpdatedBySanitization = $changedFileCount
    replacementCounts = $replacementCountByRule
}

$reportJson = $report | ConvertTo-Json -Depth 10
Set-Content -LiteralPath $sanitizationReportPath -Value $reportJson -Encoding UTF8

Write-Output "Sanitization complete. Updated files: $changedFileCount"
Write-Output "Report: $sanitizationReportPath"
