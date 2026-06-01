$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $PSScriptRoot
$venvPython = Join-Path $projectRoot "venv\Scripts\python.exe"
$configPath = Join-Path $env:LOCALAPPDATA "SwitcherinoPc\config.json"
$audioHelperPath = Join-Path $PSScriptRoot "audio-helper.ps1"

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

function Prompt-DefaultYes([string]$Message) {
    $answer = Read-Host "$Message [Y/n]"
    if ([string]::IsNullOrWhiteSpace($answer)) {
        return $true
    }
    return $answer.Trim().ToLowerInvariant() -in @("y", "yes")
}

function Get-TopologyPrompt([string]$ProfileName, [string]$CurrentValue) {
    if (-not [string]::IsNullOrWhiteSpace($CurrentValue)) {
        return "Topology for $ProfileName [$CurrentValue]"
    }
    return "Topology for $ProfileName"
}

function Resolve-TopologyChoice([string]$InputValue, [string]$DefaultValue) {
    $text = [string]$InputValue
    if ([string]::IsNullOrWhiteSpace($text)) {
        return [string]$DefaultValue
    }

    switch ($text.Trim().ToLowerInvariant()) {
        "1" { return "internal_only" }
        "internal" { return "internal_only" }
        "internal_only" { return "internal_only" }
        "pc" { return "internal_only" }
        "2" { return "external_only" }
        "external" { return "external_only" }
        "external_only" { return "external_only" }
        "tv" { return "external_only" }
        "3" { return "clone" }
        "clone" { return "clone" }
        "duplicate" { return "clone" }
        "4" { return "extend" }
        "extend" { return "extend" }
        default { return "" }
    }
}

function Get-DisplaySnapshot {
    Add-Type -AssemblyName System.Windows.Forms
    $screens = [System.Windows.Forms.Screen]::AllScreens
    $displayLines = @()

    foreach ($screen in $screens) {
        $displayLines += "{0} | primary={1} | bounds={2},{3},{4}x{5}" -f `
            $screen.DeviceName, `
            $screen.Primary, `
            $screen.Bounds.X, `
            $screen.Bounds.Y, `
            $screen.Bounds.Width, `
            $screen.Bounds.Height
    }

    return $displayLines
}

function Show-DisplaySnapshot([string[]]$DisplayLines) {
    if (-not $DisplayLines -or $DisplayLines.Count -eq 0) {
        Write-Warning "No active displays were detected."
        return
    }

    Write-Host "Detected active displays:"
    foreach ($line in $DisplayLines) {
        Write-Host "  $line"
    }
}

function Capture-AudioState {
    if (-not (Test-Path $audioHelperPath)) {
        throw "Missing audio helper script: $audioHelperPath"
    }

    $json = & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $audioHelperPath -Action capture
    if ($LASTEXITCODE -ne 0) {
        throw "audio-helper.ps1 failed while capturing the current audio device."
    }
    return $json | ConvertFrom-Json
}

function Ensure-ModeProfileObject($profile) {
    if ($null -eq $profile) {
        $profile = [pscustomobject]@{}
    }
    if ($null -eq $profile.display) {
        $profile | Add-Member -NotePropertyName "display" -NotePropertyValue ([pscustomobject]@{})
    }
    $existingAudio = $profile.audio
    $normalizedAudio = [pscustomobject]@{
        enabled = if ($null -ne $existingAudio) { [bool]$existingAudio.enabled } else { $false }
        device_name = if ($null -ne $existingAudio) { [string]$existingAudio.device_name } else { "" }
        volume_scalar = if ($null -ne $existingAudio) { $existingAudio.volume_scalar } else { $null }
    }
    if ($null -eq $profile.audio) {
        $profile | Add-Member -NotePropertyName "audio" -NotePropertyValue $normalizedAudio
    }
    else {
        $profile.audio = $normalizedAudio
    }
    return $profile
}

function Configure-Profile($config, [string]$ProfileKey, [string]$DisplayDefault, [bool]$CaptureAudio) {
    $profile = Ensure-ModeProfileObject $config.$ProfileKey
    $config.$ProfileKey = $profile

    Write-Host ""
    Write-Host "Prepare Windows for the '$ProfileKey' profile now, then press Enter to capture."
    [void](Read-Host)

    $displayLines = Get-DisplaySnapshot
    Show-DisplaySnapshot $displayLines

    $currentTopology = [string]$profile.display.topology
    if ([string]::IsNullOrWhiteSpace($currentTopology)) {
        $currentTopology = $DisplayDefault
    }

    Write-Host ""
    Write-Host "Choose the topology that matches the current Windows state:"
    Write-Host "  1. internal_only (PC screen only)"
    Write-Host "  2. external_only (second screen only)"
    Write-Host "  3. clone (duplicate)"
    Write-Host "  4. extend"

    do {
        $topologyInput = Read-Host (Get-TopologyPrompt $ProfileKey $currentTopology)
        $topology = Resolve-TopologyChoice $topologyInput $currentTopology
        if ([string]::IsNullOrWhiteSpace($topology)) {
            Write-Warning "Please choose 1, 2, 3, 4, or type a supported topology name."
        }
    } while ([string]::IsNullOrWhiteSpace($topology))

    $profile.display.topology = $topology

    if ($CaptureAudio) {
        try {
            $audioState = Capture-AudioState
            $profile.audio.enabled = $true
            $profile.audio.device_name = [string]$audioState.device_name
            $profile.audio.volume_scalar = [double]$audioState.volume_scalar

            Write-Host ""
            Write-Host "Captured audio device:"
            Write-Host "  $($profile.audio.device_name)"
            Write-Host "Captured volume:"
            Write-Host ("  {0:P0}" -f [double]$profile.audio.volume_scalar)
        }
        catch {
            Write-Warning "Unable to capture audio for '$ProfileKey': $($_.Exception.Message)"
            $profile.audio.enabled = $false
            $profile.audio.device_name = ""
            $profile.audio.volume_scalar = $null
        }
    }
    else {
        $profile.audio.enabled = $false
        $profile.audio.device_name = ""
        $profile.audio.volume_scalar = $null
    }
}

Ensure-Venv
Ensure-Config

$config = Load-ConfigJson

Write-Host ""
Write-Host "Switcherino PC display helper"
Write-Host ""
Write-Host "This script captures two Windows profiles:"
Write-Host "  - default_profile"
Write-Host "  - gaming_profile"
Write-Host ""
Write-Host "For each profile, put Windows in the desired state before pressing Enter."
Write-Host ""

$captureAudio = Prompt-DefaultYes "Capture the default audio device name and volume too?"

Configure-Profile -config $config -ProfileKey "default_profile" -DisplayDefault "internal_only" -CaptureAudio $captureAudio
Configure-Profile -config $config -ProfileKey "gaming_profile" -DisplayDefault "external_only" -CaptureAudio $captureAudio

Save-ConfigJson $config

Write-Host ""
Write-Host "Profiles saved:"
Write-Host "  $configPath"
Write-Host ""
Write-Host "Saved topologies:"
Write-Host "  - default_profile.display.topology = $($config.default_profile.display.topology)"
Write-Host "  - gaming_profile.display.topology = $($config.gaming_profile.display.topology)"
if ($captureAudio) {
    Write-Host "Saved audio device names:"
    Write-Host "  - default_profile.audio.device_name = $($config.default_profile.audio.device_name)"
    Write-Host "  - gaming_profile.audio.device_name = $($config.gaming_profile.audio.device_name)"
}
Write-Host ""

if (Prompt-DefaultYes "Open the config file now?") {
    Start-Process notepad.exe $configPath
}
