"""Kurumsal SSL kesmesi (self-signed sertifika zinciri) olan aglar icin CA paketi.

Bazi kurumsal aglar HTTPS trafigini keser ve kendi kok sertifikasiyla yeniden imzalar.
Python'un varsayilan sertifika deposu bu kok sertifikayi tanimadigi icin pip, HuggingFace
ve diger indirmeler CERTIFICATE_VERIFY_FAILED ile basarisiz olur.

certs/ca-bundle.pem varsa (certifi + Windows sertifika deposu birlestirilmis hali)
ilgili ortam degiskenleri isaret ettirilir. Paket yoksa hicbir sey yapilmaz --
normal aglarda dosya olusturulmaz ve varsayilan davranis korunur.

Paketi yeniden uretmek icin:  powershell -File scripts\sertifika_olustur.ps1
"""
from __future__ import annotations

import os
from pathlib import Path

KOK = Path(__file__).resolve().parent.parent
PAKET = KOK / "certs" / "ca-bundle.pem"

_DEGISKENLER = (
    "REQUESTS_CA_BUNDLE",   # requests / huggingface_hub
    "SSL_CERT_FILE",        # ssl, urllib
    "CURL_CA_BUNDLE",       # curl tabanli istemciler
    "HF_HUB_CA_BUNDLE",     # huggingface_hub
    "PIP_CERT",             # pip
)


def kur(sessiz: bool = True) -> str | None:
    """CA paketini ortam degiskenlerine yerlestirir. Kullanilan yolu doner."""
    if not PAKET.exists():
        return None
    yol = str(PAKET)
    for ad in _DEGISKENLER:
        os.environ.setdefault(ad, yol)   # kullanici kendi degerini verdiyse dokunma
    if not sessiz:
        print("[i] Kurumsal CA paketi devrede: " + yol)
    return yol
