"""1000+ PDF icin paralel, kaldigi yerden devam eden OCR hatti."""
from __future__ import annotations

import json
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

from tqdm import tqdm

import ocr as ocr_mod


def _is(args) -> tuple[str, str | None]:
    pdf_yolu, opsiyon, ocr_dizini = args
    pdf_yolu = Path(pdf_yolu)
    try:
        doc_id = ocr_mod.dosya_kimligi(pdf_yolu)
        hedef = Path(ocr_dizini) / f"{doc_id}.json"
        if hedef.exists() and hedef.stat().st_size > 0:
            return (pdf_yolu.name, None)  # zaten islenmis
        sonuc = ocr_mod.pdf_cikar(pdf_yolu, **opsiyon)
        ocr_mod.kaydet(sonuc, Path(ocr_dizini))
        return (pdf_yolu.name, None)
    except Exception as e:
        return (pdf_yolu.name, f"{type(e).__name__}: {e}")


def pdf_listesi(pdf_dizini: Path) -> list[Path]:
    return sorted(p for p in Path(pdf_dizini).rglob("*") if p.suffix.lower() == ".pdf")


def calistir(ayar, yeniden: bool = False, limit: int | None = None) -> dict:
    pdf_dizini = Path(ayar.yollar.pdf_dizini)
    ocr_dizini = Path(ayar.yollar.ocr_dizini)
    ocr_dizini.mkdir(parents=True, exist_ok=True)

    dosyalar = pdf_listesi(pdf_dizini)
    if limit:
        dosyalar = dosyalar[:limit]
    if not dosyalar:
        print(f"[!] {pdf_dizini} icinde PDF bulunamadi.")
        return {"toplam": 0}

    if yeniden:
        for j in ocr_dizini.glob("*.json"):
            j.unlink()

    opsiyon = dict(
        diller=ayar.ocr.diller,
        dpi=int(ayar.ocr.dpi),
        metin_esigi=int(ayar.ocr.metin_esigi),
        psm=int(ayar.ocr.psm),
        tesseract_yolu=ayar.ocr.tesseract_yolu or "",
    )
    isci = max(1, int(ayar.ocr.isci_sayisi))
    gorevler = [(str(p), opsiyon, str(ocr_dizini)) for p in dosyalar]

    basla = time.time()
    hatalar: list[tuple[str, str]] = []
    with ProcessPoolExecutor(max_workers=isci) as havuz:
        gelecekler = [havuz.submit(_is, g) for g in gorevler]
        for gel in tqdm(as_completed(gelecekler), total=len(gelecekler), desc="OCR", unit="pdf"):
            ad, hata = gel.result()
            if hata:
                hatalar.append((ad, hata))

    sure = time.time() - basla
    if hatalar:
        hata_yolu = ocr_dizini.parent / "ocr_hatalari.log"
        with open(hata_yolu, "w", encoding="utf-8") as f:
            for ad, h in hatalar:
                f.write(f"{ad}\t{h}\n")
        print(f"[!] {len(hatalar)} dosyada hata -> {hata_yolu}")

    print(f"[+] {len(dosyalar)} PDF, {sure/60:.1f} dk, {len(hatalar)} hata.")
    return {"toplam": len(dosyalar), "hata": len(hatalar), "saniye": sure}


def durum(ayar) -> dict:
    pdf = len(pdf_listesi(Path(ayar.yollar.pdf_dizini)))
    ocr_json = list(Path(ayar.yollar.ocr_dizini).glob("*.json"))
    manifest = Path(ayar.yollar.manifest)
    man_sayisi = 0
    if manifest.exists():
        with open(manifest, "r", encoding="utf-8") as f:
            man_sayisi = sum(1 for satir in f if satir.strip())
    return {"pdf": pdf, "ocr": len(ocr_json), "manifest": man_sayisi}
