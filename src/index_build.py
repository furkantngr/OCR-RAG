"""Parcalari Chroma vektor veritabanina ve BM25 deposuna yazar."""
from __future__ import annotations

import json
import pickle
import re
from pathlib import Path

from tqdm import tqdm

import chunk as chunk_mod
import embed as embed_mod
import metadata as meta_mod

TOPLU = 256


def _koleksiyon(ayar, gommeci_boyutu: int):
    import chromadb
    from chromadb.config import Settings

    istemci = chromadb.PersistentClient(
        path=str(Path(ayar.yollar.index_dizini)),
        settings=Settings(anonymized_telemetry=False, allow_reset=True),
    )
    return istemci, istemci.get_or_create_collection(
        name=ayar.vektor.koleksiyon,
        metadata={"hnsw:space": "cosine", "boyut": gommeci_boyutu},
    )


def _jeton(metin: str) -> list:
    return re.findall(r"[a-z0-9à-ɏ]+", metin.lower())


def kur(ayar, yeniden: bool = False) -> dict:
    manifest = meta_mod.manifest_oku(ayar)
    if not manifest:
        print("[!] manifest.jsonl bos. Once 'meta' adimini calistirin.")
        return {"parca": 0}

    ocr_dizini = Path(ayar.yollar.ocr_dizini)
    gommeci = embed_mod.olustur(ayar)
    istemci, koleksiyon = _koleksiyon(ayar, gommeci.boyut)

    if yeniden:
        try:
            istemci.delete_collection(ayar.vektor.koleksiyon)
        except Exception:
            pass
        istemci, koleksiyon = _koleksiyon(ayar, gommeci.boyut)

    islenmis = set()
    if not yeniden and koleksiyon.count() > 0:
        # zaten indekslenmis doc_id'leri topla
        adim, ofset = 5000, 0
        while True:
            p = koleksiyon.get(limit=adim, offset=ofset, include=["metadatas"])
            if not p["ids"]:
                break
            for m in p["metadatas"]:
                islenmis.add(m["doc_id"])
            ofset += adim

    tum_parcalar = []
    for doc_id, meta in tqdm(manifest.items(), desc="Parcalama", unit="belge"):
        if doc_id in islenmis:
            continue
        jyol = ocr_dizini / (doc_id + ".json")
        if not jyol.exists():
            continue
        kayit = json.loads(jyol.read_text(encoding="utf-8"))
        tum_parcalar.extend(
            chunk_mod.belge_parcala(
                kayit, meta,
                boyut=int(ayar.parcalama.boyut),
                ortusme=int(ayar.parcalama.ortusme),
                strateji=ayar.parcalama.get("strateji", "yapisal"),
                onek_ekle=bool(ayar.parcalama.get("baglam_oneki", True)),
                gommeci=gommeci,
            )
        )

    if not tum_parcalar:
        print("[+] Yeni parca yok, indeks guncel.")
        return {"parca": koleksiyon.count()}

    print("[*] " + str(len(tum_parcalar)) + " parca gomuluyor...")
    for i in tqdm(range(0, len(tum_parcalar), TOPLU), desc="Indeks", unit="grup"):
        grup = tum_parcalar[i:i + TOPLU]
        # Gomme, bagalm oneki eklenmis metin uzerinden yapilir; saklanan ve LLM'e
        # gosterilen govde ham metindir.
        vektorler = gommeci.belgeler([p.get("gomme_metni") or p["metin"] for p in grup],
                                     ilerleme=False)
        koleksiyon.add(
            ids=[p["id"] for p in grup],
            embeddings=vektorler,
            documents=[p["metin"] for p in grup],
            metadatas=[{
                "doc_id": p["doc_id"],
                "dosya_adi": p["dosya_adi"],
                "kaynak": p["kaynak"],
                "makine": p["makine"],
                "belge_turu": p["belge_turu"],
                "baslik_tr": p["baslik_tr"],
                "bolum": p.get("bolum", ""),
                "sayfa_bas": p["sayfa_bas"],
                "sayfa_son": p["sayfa_son"],
            } for p in grup],
        )

    _bm25_kur(ayar, koleksiyon)
    toplam = koleksiyon.count()
    print("[+] Indeks hazir: " + str(toplam) + " parca.")
    return {"parca": toplam}


def _bm25_kur(ayar, koleksiyon) -> None:
    """Anahtar kelime aramasi icin BM25 deposunu (yeniden) olusturur."""
    from rank_bm25 import BM25Okapi

    ids, belgeler, metalar = [], [], []
    adim, ofset = 5000, 0
    while True:
        p = koleksiyon.get(limit=adim, offset=ofset, include=["documents", "metadatas"])
        if not p["ids"]:
            break
        ids.extend(p["ids"])
        belgeler.extend(p["documents"])
        metalar.extend(p["metadatas"])
        ofset += adim

    if not ids:
        return
    # BM25 de bagalm onekli metni indeksler: Turkce baslik/bolum kelimeleri boylece
    # anahtar kelime aramasinda da eslesir.
    onekli = [chunk_mod.baglam_oneki(m, m.get("bolum", "")) + b
              for m, b in zip(metalar, belgeler)]
    jetonlar = [_jeton(b) for b in onekli]
    bm25 = BM25Okapi(jetonlar)
    hedef = Path(ayar.yollar.index_dizini) / "bm25.pkl"
    with open(hedef, "wb") as f:
        pickle.dump({"ids": ids, "metalar": metalar, "belgeler": belgeler, "bm25": bm25}, f)
    print("[+] BM25 deposu: " + str(len(ids)) + " parca.")


def bm25_yukle(ayar):
    yol = Path(ayar.yollar.index_dizini) / "bm25.pkl"
    if not yol.exists():
        return None
    with open(yol, "rb") as f:
        return pickle.load(f)


def koleksiyon_ac(ayar):
    import chromadb
    from chromadb.config import Settings

    istemci = chromadb.PersistentClient(
        path=str(Path(ayar.yollar.index_dizini)),
        settings=Settings(anonymized_telemetry=False),
    )
    return istemci.get_or_create_collection(name=ayar.vektor.koleksiyon)
