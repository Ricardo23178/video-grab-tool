param(
    [Parameter(Position = 0)][string]$Link,
    [string]$OutDir,
    [string]$InputFile,
    [ValidateSet('douyin', 'bilibili')][string]$Login,
    [switch]$Setup
)

$ErrorActionPreference = 'Stop'
$pythonPath = Join-Path $PSScriptRoot '.runtime\python.exe'
if (-not (Test-Path -LiteralPath $pythonPath -PathType Leaf)) {
    $pythonPath = (Get-Command python -ErrorAction Stop).Source
}
$pythonArgs = @('-B', (Join-Path $PSScriptRoot 'grab.py'))
if ($Link) { $pythonArgs += $Link }
if ($OutDir) { $pythonArgs += @('--output', $OutDir) }
if ($InputFile) { $pythonArgs += @('--file', $InputFile) }
if ($Login) { $pythonArgs += @('--login', $Login) }
if ($Setup) { $pythonArgs += '--setup' }
& $pythonPath @pythonArgs
exit $LASTEXITCODE
