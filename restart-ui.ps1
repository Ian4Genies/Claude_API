$ErrorActionPreference = "SilentlyContinue"
$Root = $PSScriptRoot
$Port = 8000

Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
    Where-Object { $_.Name -eq "python.exe" -and $_.CommandLine -match "uvicorn runner\.app:app" } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }

netstat -ano | Select-String ":$Port\s" | ForEach-Object {
    if ($_ -match "\s(\d+)\s*$") {
        Stop-Process -Id $Matches[1] -Force -ErrorAction SilentlyContinue
    }
}

Start-Sleep -Seconds 2

$uvicorn = Join-Path $Root ".venv\Scripts\uvicorn.exe"
if (-not (Test-Path $uvicorn)) {
    Write-Host "Run setup first: py -m venv .venv; .venv\Scripts\pip install -e ." -ForegroundColor Red
    exit 1
}

Push-Location $Root
& .venv\Scripts\pip.exe install -e . -q
Pop-Location

Start-Process $uvicorn -ArgumentList "runner.app:app", "--host", "127.0.0.1", "--port", "$Port" -WorkingDirectory $Root -WindowStyle Minimized
Start-Sleep -Seconds 3

$url = "http://127.0.0.1:$Port"
Start-Process $url
Write-Host "UI restarted at $url" -ForegroundColor Green
