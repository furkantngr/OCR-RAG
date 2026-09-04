# MakineRAG web arayuzunu baslatir
# Calistirma:  powershell -ExecutionPolicy Bypass -File D:\MakineRAG\baslat.ps1

$Kok = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Kok

$Py = "$Kok\.venv\Scripts\python.exe"
if (-not (Test-Path $Py)) { $Py = "python" }

$Adres = "http://127.0.0.1:8000"

Write-Host "MakineRAG baslatiliyor..." -ForegroundColor Cyan
Write-Host "Arayuz: $Adres" -ForegroundColor Yellow
Write-Host "Durdurmak icin Ctrl+C" -ForegroundColor DarkGray
Write-Host ""

# Ollama servisi ayakta mi
try {
    Invoke-WebRequest -Uri "http://localhost:11434/api/tags" -TimeoutSec 3 -UseBasicParsing | Out-Null
    Write-Host "[OK] Ollama calisiyor" -ForegroundColor Green
} catch {
    Write-Host "[!] Ollama calismiyor. Ayri bir pencerede 'ollama serve' calistirin." -ForegroundColor Red
}

Start-Job -ScriptBlock {
    Start-Sleep -Seconds 3
    Start-Process $using:Adres
} | Out-Null

& $Py "$Kok\server\api.py"
