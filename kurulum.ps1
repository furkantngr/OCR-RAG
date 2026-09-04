# MakineRAG kurulum betigi
# Calistirma:  powershell -ExecutionPolicy Bypass -File D:\MakineRAG\kurulum.ps1

$ErrorActionPreference = "Stop"
$Kok = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Kok

Write-Host "=== MakineRAG kurulumu ===" -ForegroundColor Cyan

# --- 1) Sanal ortam (global torch/CUDA'yi tekrar indirmemek icin system-site-packages) ---
if (-not (Test-Path "$Kok\.venv")) {
    Write-Host "[1/6] Sanal ortam olusturuluyor..." -ForegroundColor Yellow
    python -m venv --system-site-packages "$Kok\.venv"
} else {
    Write-Host "[1/6] Sanal ortam zaten var." -ForegroundColor Green
}
$Py = "$Kok\.venv\Scripts\python.exe"

# --- 2) Sertifika paketi (kurumsal SSL kesmesi olan aglar icin) ---
# HuggingFace model indirmeleri --trusted-host bayragini kullanamaz, gercek bir CA
# paketi ister. Paket yoksa bir kez uretilir; normal aglarda zararsizdir.
if (-not (Test-Path "$Kok\certs\ca-bundle.pem")) {
    Write-Host "[2/6] Sertifika paketi hazirlaniyor..." -ForegroundColor Yellow
    try {
        & powershell -ExecutionPolicy Bypass -File "$Kok\scripts\sertifika_olustur.ps1"
    } catch {
        Write-Host "  [!] Sertifika paketi uretilemedi: $_" -ForegroundColor Red
    }
} else {
    Write-Host "[2/6] Sertifika paketi mevcut." -ForegroundColor Green
}
if (Test-Path "$Kok\certs\ca-bundle.pem") {
    $env:SSL_CERT_FILE      = "$Kok\certs\ca-bundle.pem"
    $env:REQUESTS_CA_BUNDLE = "$Kok\certs\ca-bundle.pem"
    $env:PIP_CERT           = "$Kok\certs\ca-bundle.pem"
}

# --- 3) Python paketleri ---
Write-Host "[3/6] Python paketleri kuruluyor..." -ForegroundColor Yellow
$Guvenli = @("--trusted-host", "pypi.org", "--trusted-host", "files.pythonhosted.org",
             "--trusted-host", "pypi.python.org")
& $Py -m pip install --upgrade pip --quiet @Guvenli
& $Py -m pip install -r "$Kok\requirements.txt" @Guvenli

# --- 4) Torch/CUDA kontrolu ---
Write-Host "[4/6] GPU kontrolu..." -ForegroundColor Yellow
& $Py -c "import torch; print('torch', torch.__version__, '| CUDA:', torch.cuda.is_available(), '|', (torch.cuda.get_device_name(0) if torch.cuda.is_available() else 'CPU'))"

# --- 5) Tesseract OCR ---
Write-Host "[5/6] Tesseract kontrolu..." -ForegroundColor Yellow
$tess = Get-Command tesseract -ErrorAction SilentlyContinue
if (-not $tess) {
    $aday = "C:\Program Files\Tesseract-OCR\tesseract.exe"
    if (Test-Path $aday) {
        $tess = @{ Source = $aday }
        Write-Host "  Tesseract bulundu: $aday" -ForegroundColor Green
    } else {
        Write-Host "  Tesseract KURULU DEGIL. Kurmak icin:" -ForegroundColor Red
        Write-Host "    winget install --id UB-Mannheim.TesseractOCR -e --source winget" -ForegroundColor White
        Write-Host "  Kurulum sirasinda 'Additional language data' altindan Romanian + English secin." -ForegroundColor White
    }
}
if ($tess) {
    $exe = if ($tess.Source) { $tess.Source } else { "tesseract" }
    $diller = & $exe --list-langs 2>&1
    Write-Host "  Yuklu diller: $($diller -join ' ')"
    $tessdata = Join-Path (Split-Path -Parent $exe) "tessdata"
    foreach ($d in @("ron", "eng")) {
        if ($diller -notcontains $d) {
            Write-Host "  '$d' dil paketi eksik, indiriliyor..." -ForegroundColor Yellow
            $url = "https://github.com/tesseract-ocr/tessdata_best/raw/main/$d.traineddata"
            try {
                Invoke-WebRequest -Uri $url -OutFile (Join-Path $tessdata "$d.traineddata")
                Write-Host "  '$d' kuruldu." -ForegroundColor Green
            } catch {
                Write-Host "  '$d' indirilemedi (yonetici izni gerekebilir): $_" -ForegroundColor Red
            }
        }
    }
}

# --- 6) Ollama modelleri ---
Write-Host "[6/6] Ollama kontrolu..." -ForegroundColor Yellow
$ollama = Get-Command ollama -ErrorAction SilentlyContinue
if ($ollama) {
    $modeller = (& ollama list) -join "`n"
    foreach ($m in @("llama3.1:8b", "nomic-embed-text")) {
        if ($modeller -notmatch [regex]::Escape($m)) {
            Write-Host "  $m indiriliyor..." -ForegroundColor Yellow
            & ollama pull $m
        } else {
            Write-Host "  $m hazir." -ForegroundColor Green
        }
    }
} else {
    Write-Host "  Ollama bulunamadi: https://ollama.com/download" -ForegroundColor Red
}

Write-Host ""
Write-Host "=== Kurulum tamam ===" -ForegroundColor Cyan
Write-Host "Sonraki adimlar:" -ForegroundColor White
Write-Host "  1. PDF'leri D:\MakineRAG\data\pdf klasorune kopyalayin"
Write-Host "  2. config.yaml > makineler bolumune makine adlarinizi yazin"
Write-Host "  3. .\.venv\Scripts\python.exe src\cli.py tumu"
Write-Host "  4. .\baslat.ps1   ->  http://127.0.0.1:8000"
