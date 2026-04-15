$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $PSScriptRoot
$venvPython = Join-Path $projectRoot "venv\Scripts\python.exe"
$configPath = Join-Path $env:LOCALAPPDATA "SwitcherinoPc\config.json"
$certsDir = Join-Path $env:LOCALAPPDATA "SwitcherinoPc\certs"
$rpiCertPath = Join-Path $certsDir "rpi-server.crt"
$displayHelperPath = Join-Path $PSScriptRoot "display-helper.ps1"

function Ensure-Venv {
    if (-not (Test-Path $venvPython)) {
        Write-Host "Creating local venv..."
        py -m venv venv
    }
}

function Ensure-Config {
    & $venvPython -c "from src.config import load_config; load_config()"
}

function Load-ConfigJson {
    return Get-Content $configPath -Raw | ConvertFrom-Json
}

function Save-ConfigJson($config) {
    $json = $config | ConvertTo-Json -Depth 10
    $utf8NoBom = New-Object System.Text.UTF8Encoding($false)
    [System.IO.File]::WriteAllText($configPath, $json, $utf8NoBom)
}

function Invoke-JsonIgnoringTls([string]$Url) {
    Add-Type -AssemblyName System.Net.Http
    [System.Net.ServicePointManager]::ServerCertificateValidationCallback = { $true }
    $handler = New-Object System.Net.Http.HttpClientHandler
    $handler.ServerCertificateCustomValidationCallback = [System.Net.Http.HttpClientHandler]::DangerousAcceptAnyServerCertificateValidator
    $client = New-Object System.Net.Http.HttpClient($handler)
    $client.Timeout = New-TimeSpan -Seconds 10
    try {
        $response = $client.GetAsync($Url).GetAwaiter().GetResult()
        $response.EnsureSuccessStatusCode() | Out-Null
        $content = $response.Content.ReadAsStringAsync().GetAwaiter().GetResult()
        return $content | ConvertFrom-Json
    }
    finally {
        $client.Dispose()
        $handler.Dispose()
    }
}

function Prompt-DefaultYes([string]$Message) {
    $answer = Read-Host "$Message [Y/n]"
    if ([string]::IsNullOrWhiteSpace($answer)) {
        return $true
    }
    return $answer.Trim().ToLowerInvariant() -in @("y", "yes")
}

Ensure-Venv
Ensure-Config

$config = Load-ConfigJson

Write-Host ""
Write-Host "Switcherino PC initial setup"
Write-Host ""
Write-Host "Press Enter on any prompt to keep the current value or leave it blank."
Write-Host ""

$currentUrl = [string]$config.rpi_base_url
$rpiUrlPrompt = "Raspberry Pi base URL"
if (-not [string]::IsNullOrWhiteSpace($currentUrl)) {
    $rpiUrlPrompt += " [$currentUrl]"
}
$rpiUrl = Read-Host $rpiUrlPrompt
if ([string]::IsNullOrWhiteSpace($rpiUrl)) {
    $rpiUrl = $currentUrl
}
$rpiUrl = [string]$rpiUrl
$rpiUrl = $rpiUrl.Trim().TrimEnd("/")
$config.rpi_base_url = $rpiUrl

$hasExistingKey = -not [string]::IsNullOrWhiteSpace([string]$config.rpi_api_key)
$keyPrompt = "Raspberry Pi API key"
if ($hasExistingKey) {
    $keyPrompt += " [configured]"
}
$rpiKey = Read-Host $keyPrompt
if (-not [string]::IsNullOrWhiteSpace($rpiKey)) {
    $config.rpi_api_key = [string]$rpiKey
}

if (-not [string]::IsNullOrWhiteSpace($rpiUrl)) {
    if (Prompt-DefaultYes "Fetch /certs from the Raspberry Pi now?") {
        try {
            Write-Host ""
            Write-Host "Fetching certs from:"
            Write-Host "  $rpiUrl/certs"
            $certs = Invoke-JsonIgnoringTls "$rpiUrl/certs"
            if ($null -ne $certs.certs) {
                New-Item -ItemType Directory -Force -Path $certsDir | Out-Null

                if (-not [string]::IsNullOrWhiteSpace([string]$certs.certs.pem)) {
                    $utf8NoBom = New-Object System.Text.UTF8Encoding($false)
                    [System.IO.File]::WriteAllText($rpiCertPath, ([string]$certs.certs.pem), $utf8NoBom)
                    $config.rpi_ca_file = $rpiCertPath
                    $config.rpi_verify_tls = $true
                }

                if (-not [string]::IsNullOrWhiteSpace([string]$certs.certs.sha256_fingerprint)) {
                    $config.rpi_cert_fingerprint = [string]$certs.certs.sha256_fingerprint
                }

                Write-Host ""
                Write-Host "Fetched Raspberry Pi certificate info successfully."
                if (Test-Path $rpiCertPath) {
                    Write-Host "Saved certificate to:"
                    Write-Host "  $rpiCertPath"
                }
            }
            else {
                Write-Warning "The Raspberry Pi /certs response did not contain a certs object."
            }
        }
        catch {
            $message = $_.Exception.Message
            if ($_.Exception.InnerException) {
                $message = $_.Exception.InnerException.Message
            }
            Write-Warning "Unable to fetch Raspberry Pi certs automatically: $message"
            Write-Host "Common causes:"
            Write-Host "  - the Raspberry Pi URL is wrong"
            Write-Host "  - the Raspberry Pi API is not reachable yet"
            Write-Host "  - HTTPS handshake is slow and timed out during setup"
            Write-Host "You can still continue with a blank or manually edited config."
        }
    }
}
else {
    Write-Host ""
    Write-Host "No Raspberry Pi URL configured. Leaving Raspberry Pi settings blank is allowed."
}

Save-ConfigJson $config

Write-Host ""
Write-Host "Config saved:"
Write-Host "  $configPath"
Write-Host ""
Write-Host "Still worth reviewing manually:"
Write-Host "  - default_profile.display.topology"
Write-Host "  - gaming_profile.display.topology"
Write-Host "  - audio endpoint and volume settings if needed"
Write-Host ""

if (Prompt-DefaultYes "Run the interactive display/audio profile helper now?") {
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $displayHelperPath
}

if (Prompt-DefaultYes "Open the config file now?") {
    Start-Process notepad.exe $configPath
}
