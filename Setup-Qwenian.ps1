[CmdletBinding()]
param(
    [switch]$SkipModels,
    [switch]$SkipTorch,
    [switch]$NoLaunch
)

$ErrorActionPreference = 'Stop'
& (Join-Path $PSScriptRoot 'Setup-QwenImage21.ps1') -SkipModels:$SkipModels -SkipTorch:$SkipTorch -NoLaunch:$NoLaunch
