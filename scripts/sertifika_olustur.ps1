# Windows sertifika deposundaki kok/ara sertifikalari certifi paketiyle birlestirir.
# Kurumsal SSL kesmesi olan aglarda pip ve HuggingFace indirmelerini calisir hale getirir.
#
# Calistirma:  powershell -ExecutionPolicy Bypass -File D:\MakineRAG\scripts\sertifika_olustur.ps1

$ErrorActionPreference = "Stop"
$Kok = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$Hedef = Join-Path $Kok "certs"
New-Item -ItemType Directory -Force -Path $Hedef | Out-Null

$Kurumsal = Join-Path $Hedef "kurumsal-ca.pem"
$Birlesik = Join-Path $Hedef "ca-bundle.pem"

Write-Host "Windows sertifika deposu okunuyor..." -ForegroundColor Yellow

$magazalar = @("Cert:\LocalMachine\Root", "Cert:\LocalMachine\CA",
               "Cert:\CurrentUser\Root", "Cert:\CurrentUser\CA")
$satirlar = New-Object System.Collections.Generic.List[string]
$gorulen  = New-Object System.Collections.Generic.HashSet[string]
$sayi = 0

foreach ($m in $magazalar) {
    try { $sertler = Get-ChildItem $m -ErrorAction Stop } catch { continue }
    foreach ($s in $sertler) {
        if (-not $gorulen.Add($s.Thumbprint)) { continue }
        $satirlar.Add("# " + $s.Subject)
        $satirlar.Add("-----BEGIN CERTIFICATE-----")
        $satirlar.Add([Convert]::ToBase64String($s.RawData, 'InsertLineBreaks'))
        $satirlar.Add("-----END CERTIFICATE-----")
        $satirlar.Add("")
        $sayi++
    }
}
[System.IO.File]::WriteAllLines($Kurumsal, $satirlar)
Write-Host "  $sayi sertifika -> $Kurumsal" -ForegroundColor Green

$Py = Join-Path $Kok ".venv\Scripts\python.exe"
if (-not (Test-Path $Py)) { $Py = "python" }

& $Py -c @"
import certifi, pathlib, sys
kurumsal = pathlib.Path(r'$Kurumsal').read_text(encoding='utf-8')
temel = pathlib.Path(certifi.where()).read_text(encoding='utf-8')
pathlib.Path(r'$Birlesik').write_text(temel + '\n' + kurumsal, encoding='utf-8')
print('  birlesik paket ->', r'$Birlesik')
"@

Write-Host ""
Write-Host "Dogrulaniyor..." -ForegroundColor Yellow
& $Py -c @"
import requests
for u in ['https://pypi.org/simple/', 'https://huggingface.co/api/models/BAAI/bge-m3']:
    try:
        r = requests.get(u, timeout=20, verify=r'$Birlesik')
        print('  [OK]', r.status_code, u)
    except Exception as e:
        print('  [HATA]', type(e).__name__, str(e)[:100])
"@

Write-Host ""
Write-Host "Tamam. src/sertifika.py bu paketi otomatik devreye alir." -ForegroundColor Cyan
