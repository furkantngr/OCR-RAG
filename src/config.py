"""Yapilandirma yukleyici."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml

import sertifika

KOK = Path(__file__).resolve().parent.parent
VARSAYILAN_CONFIG = KOK / "config.yaml"


class Ayar(dict):
    """Noktali erisim destekleyen sozluk: ayar.ocr.dpi"""

    def __getattr__(self, ad: str) -> Any:
        try:
            deger = self[ad]
        except KeyError as e:
            raise AttributeError(ad) from e
        return Ayar(deger) if isinstance(deger, dict) else deger


def yukle(yol: str | Path | None = None) -> Ayar:
    # Kurumsal aglarda HTTPS indirmeleri icin CA paketini devreye al (varsa)
    sertifika.kur()

    yol = Path(yol) if yol else VARSAYILAN_CONFIG
    with open(yol, "r", encoding="utf-8") as f:
        ham = yaml.safe_load(f)

    ayar = Ayar(ham)

    # Yollari mutlaklastir ve olustur
    for anahtar, deger in ham["yollar"].items():
        p = Path(deger)
        if not p.is_absolute():
            p = KOK / p
        ham["yollar"][anahtar] = str(p)
        if anahtar.endswith("_dizini"):
            p.mkdir(parents=True, exist_ok=True)
        else:
            p.parent.mkdir(parents=True, exist_ok=True)

    # Tesseract yolu
    t_yol = ham.get("ocr", {}).get("tesseract_yolu") or ""
    if t_yol:
        os.environ["TESSERACT_CMD"] = t_yol

    return ayar


def makine_haritasi(ayar: Ayar, kisa_dahil: bool = False) -> dict[str, str]:
    """Takma ad (kucuk harf) -> makine kodu haritasi.

    kisa_dahil=False (varsayilan): 3 karakterden kisa takma adlar atlanir.
    Sebep: makine kodu cogu zaman tek harftir ("A", "B"). Bu kodlar belge METNINDE
    aranirsa Romence'deki bagimsiz "a" gibi siradan kelimelerle eslesir ve belgeler
    yanlis makineye atanir. Metin taramasinda bu yuzden kisa adlar kullanilmaz;
    "MK-A" gibi ayirt edici takma adlar kullanilir.

    kisa_dahil=True: LLM'in dondurdugu makine adayini birebir eslestirirken kullanilir;
    orada "A" cevabi gercekten A makinesi demektir.
    """
    harita: dict[str, str] = {}
    for m in ayar.makineler:
        kod = str(m["kod"])
        for ad in [m["ad"], kod, *m.get("takma_adlar", [])]:
            anahtar = str(ad).lower().strip()
            if not anahtar:
                continue
            if not kisa_dahil and len(anahtar) < 3:
                continue
            harita[anahtar] = kod
    return harita


def makine_adi(ayar: Ayar, kod: str) -> str:
    for m in ayar.makineler:
        if str(m["kod"]) == str(kod):
            return m["ad"]
    return kod
