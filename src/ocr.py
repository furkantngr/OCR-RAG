"""PDF -> metin. Once gomulu metin katmani, yoksa Tesseract OCR."""
from __future__ import annotations

import hashlib
import io
import json
import os
from dataclasses import dataclass, asdict
from pathlib import Path

import fitz  # PyMuPDF


@dataclass
class SayfaMetni:
    sayfa: int
    metin: str
    ocr: bool


def dosya_kimligi(yol: Path) -> str:
    """Icerik + ad tabanli kararli kimlik (yeniden calistirmada ayni kalir)."""
    h = hashlib.sha1()
    h.update(yol.name.encode("utf-8", "ignore"))
    with open(yol, "rb") as f:
        h.update(f.read(1 << 20))  # ilk 1 MB yeterli ayirt edici
    h.update(str(yol.stat().st_size).encode())
    return h.hexdigest()[:16]


def _tesseract_hazirla(tesseract_yolu: str = "") -> None:
    import pytesseract

    yol = tesseract_yolu or os.environ.get("TESSERACT_CMD", "")
    if yol:
        pytesseract.pytesseract.tesseract_cmd = yol
        return
    # Windows kurulum yollari. winget yonetici izni olmadan kurdugunda
    # Program Files yerine LOCALAPPDATA altina yazar, bu yuzden orasi da aranir.
    yerel = os.environ.get("LOCALAPPDATA", "")
    adaylar = [
        r"C:\Program Files\Tesseract-OCR\tesseract.exe",
        r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
    ]
    if yerel:
        adaylar += [
            str(Path(yerel) / "Programs" / "Tesseract-OCR" / "tesseract.exe"),
            str(Path(yerel) / "Tesseract-OCR" / "tesseract.exe"),
        ]
    for aday in adaylar:
        if Path(aday).exists():
            pytesseract.pytesseract.tesseract_cmd = aday
            return


def _sayfa_ocr(sayfa, dpi: int, diller: str, psm: int) -> str:
    import pytesseract
    from PIL import Image

    zoom = dpi / 72.0
    pix = sayfa.get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False)
    img = Image.open(io.BytesIO(pix.tobytes("png")))
    cfg = f"--oem 1 --psm {psm}"
    return pytesseract.image_to_string(img, lang=diller, config=cfg)


def pdf_cikar(
    pdf_yolu: Path,
    diller: str = "ron+eng",
    dpi: int = 300,
    metin_esigi: int = 120,
    psm: int = 3,
    tesseract_yolu: str = "",
) -> dict:
    """Tek bir PDF'i metne cevirir. Sayfa bazli, OCR bayrakli."""
    _tesseract_hazirla(tesseract_yolu)
    sayfalar: list[SayfaMetni] = []
    ocr_sayisi = 0

    with fitz.open(pdf_yolu) as doc:
        pdf_meta = doc.metadata or {}
        for i, sayfa in enumerate(doc, start=1):
            metin = (sayfa.get_text("text") or "").strip()
            ocr_edildi = False
            if len(metin) < metin_esigi:
                try:
                    metin = (_sayfa_ocr(sayfa, dpi, diller, psm) or "").strip()
                    ocr_edildi = True
                    ocr_sayisi += 1
                except Exception as e:  # OCR basarisizsa sayfayi bos gec
                    metin = ""
                    ocr_edildi = True
                    print(f"  ! OCR hatasi {pdf_yolu.name} s.{i}: {e}")
            sayfalar.append(SayfaMetni(i, metin, ocr_edildi))

    toplam = sum(len(s.metin) for s in sayfalar)
    return {
        "doc_id": dosya_kimligi(pdf_yolu),
        "kaynak": str(pdf_yolu),
        "dosya_adi": pdf_yolu.name,
        "sayfa_sayisi": len(sayfalar),
        "ocr_sayfa_sayisi": ocr_sayisi,
        "karakter_sayisi": toplam,
        "pdf_meta": {k: v for k, v in pdf_meta.items() if v},
        "sayfalar": [asdict(s) for s in sayfalar],
    }


def kaydet(sonuc: dict, ocr_dizini: Path) -> Path:
    hedef = Path(ocr_dizini) / f"{sonuc['doc_id']}.json"
    with open(hedef, "w", encoding="utf-8") as f:
        json.dump(sonuc, f, ensure_ascii=False)
    return hedef


def oku(doc_id: str, ocr_dizini: Path) -> dict:
    with open(Path(ocr_dizini) / f"{doc_id}.json", "r", encoding="utf-8") as f:
        return json.load(f)


def tam_metin(kayit: dict, ayirici: str = "\n") -> str:
    return ayirici.join(s["metin"] for s in kayit["sayfalar"] if s["metin"])
