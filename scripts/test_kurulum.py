"""Kurulum dogrulama: her bilesen ayri ayri denenir."""
from __future__ import annotations

import sys
from pathlib import Path

KOK = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(KOK / "src"))

SONUC = []


def dene(ad, fn):
    try:
        bilgi = fn()
        SONUC.append((ad, True, bilgi or ""))
    except Exception as e:
        SONUC.append((ad, False, type(e).__name__ + ": " + str(e)[:140]))


def t_config():
    import config as cfg
    a = cfg.yukle()
    return a.proje.ad + " | makine: " + str([m["kod"] for m in a.makineler])


def t_fitz():
    import fitz
    return "PyMuPDF " + fitz.__doc__.strip().split("\n")[0]


def t_tesseract():
    import pytesseract
    import ocr
    ocr._tesseract_hazirla()
    v = str(pytesseract.get_tesseract_version())
    diller = pytesseract.get_languages()
    eksik = [d for d in ("ron", "eng") if d not in diller]
    if eksik:
        raise RuntimeError("eksik dil paketi: " + ",".join(eksik))
    return "v" + v + " | diller: ron, eng OK"


def t_torch():
    import torch
    return ("torch " + torch.__version__ + " | CUDA " + str(torch.cuda.is_available())
            + " | " + (torch.cuda.get_device_name(0) if torch.cuda.is_available() else "CPU"))


def t_chroma():
    import chromadb
    return "chromadb " + chromadb.__version__


def t_sertifika():
    import sertifika
    yol = sertifika.kur()
    if not yol:
        return "paket yok (normal ag) - gerekirse scripts/sertifika_olustur.ps1"
    import requests
    requests.get("https://huggingface.co/api/models/BAAI/bge-m3", timeout=20).raise_for_status()
    return "CA paketi calisiyor, HuggingFace erisimi OK"


def t_web():
    import fastapi
    import uvicorn
    eksik = [d.name for d in [KOK / "web" / "index.html", KOK / "web" / "style.css",
                              KOK / "web" / "app.js", KOK / "server" / "api.py"]
             if not d.exists()]
    if eksik:
        raise RuntimeError("eksik arayuz dosyasi: " + ", ".join(eksik))
    return "fastapi " + fastapi.__version__ + " | uvicorn " + uvicorn.__version__


def t_bm25():
    from rank_bm25 import BM25Okapi
    BM25Okapi([["a", "b"], ["c"]])
    return "rank-bm25 OK"


def t_ollama():
    import config as cfg
    import llm as llm_mod
    a = cfg.yukle()
    c = llm_mod.olustur(a)
    if not c.canli_mi():
        raise RuntimeError("Ollama servisine ulasilamiyor: " + a.llm.taban_url)
    y = c.uret("Sadece 'merhaba' yaz.", sicaklik=0.0)
    return a.llm.model + " -> " + y[:60].replace("\n", " ")


def t_gomme():
    import config as cfg
    import embed
    a = cfg.yukle()
    g = embed.olustur(a)
    v = g.sorgu("yaglama araligi")
    return a.gomme.model + " | boyut " + str(len(v)) + " | cihaz " + getattr(g, "cihaz", "-")


def t_parcalama():
    import chunk
    sahte = {"sayfalar": [{"sayfa": 1, "metin": "Lorem ipsum " * 300, "ocr": True},
                          {"sayfa": 2, "metin": "Dolor sit amet " * 300, "ocr": True}]}
    meta = {"doc_id": "test", "dosya_adi": "t.pdf", "kaynak": "t.pdf"}
    p = chunk.belge_parcala(sahte, meta, boyut=1400, ortusme=220)
    if not p:
        raise RuntimeError("parca uretilmedi")
    return str(len(p)) + " parca, ilk sayfa araligi " + str(p[0]["sayfa_bas"]) + "-" + str(p[0]["sayfa_son"])


if __name__ == "__main__":
    for ad, fn in [
        ("config.yaml", t_config),
        ("PyMuPDF", t_fitz),
        ("Tesseract (ron+eng)", t_tesseract),
        ("PyTorch / CUDA", t_torch),
        ("ChromaDB", t_chroma),
        ("BM25", t_bm25),
        ("Sertifika / ag", t_sertifika),
        ("Web sunucusu", t_web),
        ("Parcalama", t_parcalama),
        ("Ollama LLM", t_ollama),
        ("Gomme modeli", t_gomme),
    ]:
        dene(ad, fn)

    print("\n" + "=" * 74)
    for ad, ok, bilgi in SONUC:
        isaret = "[OK]  " if ok else "[HATA]"
        print(isaret + " " + ad.ljust(22) + " " + bilgi)
    print("=" * 74)
    basarisiz = [a for a, ok, _ in SONUC if not ok]
    if basarisiz:
        print("Eksik: " + ", ".join(basarisiz))
        sys.exit(1)
    print("Tum bilesenler hazir.")
