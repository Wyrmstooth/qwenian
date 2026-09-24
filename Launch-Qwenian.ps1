[CmdletBinding()]
param([switch]$NoBrowser)

$ErrorActionPreference = 'Stop'
& (Join-Path $PSScriptRoot 'Launch-QwenStudio.ps1') -NoBrowser:$NoBrowser
