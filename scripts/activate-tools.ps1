# Dot-source this file to refresh tools in an existing PowerShell/Codex session:
# . .\scripts\activate-tools.ps1
# Only this process's PATH changes; no persistent system settings are modified.
$gatewayRoot = Split-Path -Parent $PSScriptRoot
$gatewayToolDirectories = @(
    (Join-Path $gatewayRoot '.venv\Scripts'),
    (Join-Path $env:LOCALAPPDATA 'Programs\DockerDesktop\resources\bin'),
    (Join-Path $env:LOCALAPPDATA 'Programs\Ollama'),
    'C:\Program Files\Docker\Docker\resources\bin',
    'C:\Program Files (x86)\GnuWin32\bin'
) | Where-Object { Test-Path -LiteralPath $_ }
$gatewayPathEntries = @($gatewayToolDirectories) + @(
    $env:Path -split ';'
) + @(
    [Environment]::GetEnvironmentVariable('Path', 'User') -split ';'
) + @(
    [Environment]::GetEnvironmentVariable('Path', 'Machine') -split ';'
)
$env:Path = ($gatewayPathEntries | Where-Object { $_ } | Select-Object -Unique) -join ';'
Get-Command python,docker,kubectl,ollama,make -ErrorAction SilentlyContinue |
    Select-Object Name,Source
