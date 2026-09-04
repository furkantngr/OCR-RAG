"""Gomme modeli karsilastirmasi -- kendi belgeleriniz uzerinde.

Leaderboard skorlari sizin belgelerinizde OCR gurultusu ve alan jargonu yaninda
kucuk kalir. Bu betik, gercek belgelerinizden bir orneklem alip birden fazla gomme
modelini ayni sorularla olcer ve hangisinin dogru belgeyi ust siralara tasidigini
gosterir.

Kullanim:

  # 1) Once sorulari uret (LLM belgelerden Turkce soru yazar, dogru cevap = kaynak belge)
  python scripts/gomme_karsilastir.py --ornek 40 --soru-uret 25

  # 2) Sorulari elle duzeltin/ekleyin:  data/degerlendirme/sorular.json
  #    (en degerlisi: gercekten soracaginiz sorulari yazmak)

  # 3) Karsilastirmayi calistirin
  python scripts/gomme_karsilastir.py --modeller BAAI/bge-m3 Qwen/Qwen3-Embedding-0.6B

Notlar:
  - Gercek Chroma indeksine dokunmaz, her sey bellekte hesaplanir.
  - Modeller sirayla yuklenip bosaltilir, 8 GB VRAM yeter.
  - Olcum sirasinda Ollama'yi durdurmak GPU'yu rahatlatir: ollama stop <model>
"""
from __future__ import annotations

import argparse
import json
import random
import re
import sys
import time
from collections import defaultdict
from pathlib import Path

KOK = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(KOK / "src"))

for _akis in (sys.stdout, sys.stderr):
    try:
        _akis.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

import numpy as np  # noqa: E402
from tqdm import tqdm  # noqa: E402

import chunk as chunk_mod    # noqa: E402
import config as cfg         # noqa: E402
import embed as embed_mod    # noqa: E402
import llm as llm_mod        # noqa: E402
import metadata as meta_mod  # noqa: E402

VARSAYILAN_MODELLER = ["BAAI/bge-m3", "Qwen/Qwen3-Embedding-0.6B"]

SORU_ISTEMI = """Asagida bir teknik belgeden alinmis bir bolum var (Ingilizce veya Romence).
Bir bakim teknisyeninin bu bolumdeki bilgiyi ogrenmek icin soracagi TURKCE bir soru yaz.

Kurallar:
- Soru Turkce olacak.
- Sadece bu bolumdeki bilgiyle cevaplanabilmeli.
- Belgeye atif yapma ("bu belgede", "yukaridaki metinde" deme). Dogrudan teknik soru sor.
- Somut ol: sayi, aralik, parca adi, hata kodu gibi seylere odaklan.

Sadece su JSON'u dondur: {{"soru": "..."}}

BOLUM:
---
{metin}
---"""


# ─────────────────────────────────────────────────────────────
# Veri hazirligi
# ─────────────────────────────────────────────────────────────
def _orneklem(ayar, ornek: int, tohum: int) -> list:
    """Makineye gore tabakali belge orneklemi."""
    manifest = meta_mod.manifest_oku(ayar)
    if not manifest:
        print("[!] manifest.jsonl bos. Once 'python src/cli.py tumu' calistirin.")
        sys.exit(1)

    ocr_dizini = Path(ayar.yollar.ocr_dizini)
    mevcut = [m for m in manifest.values() if (ocr_dizini / (m["doc_id"] + ".json")).exists()]

    # makineye gore tabakali orneklem: her makineden orantili sayida belge
    gruplar = defaultdict(list)
    for m in mevcut:
        gruplar[m.get("makine", "bilinmiyor")].append(m)

    rastgele = random.Random(tohum)
    secilen = []
    if ornek >= len(mevcut):
        secilen = list(mevcut)
    else:
        for kod, liste in gruplar.items():
            rastgele.shuffle(liste)
            pay = max(1, round(ornek * len(liste) / len(mevcut)))
            secilen.extend(liste[:pay])
        rastgele.shuffle(secilen)
        secilen = secilen[:ornek]
    return secilen


def parcalari_getir(ayar, secilen: list, strateji: str = "yapisal",
                    gommeci=None, sessiz: bool = False) -> list:
    """Secilen belgeleri verilen strateji ile parcalara boler."""
    ocr_dizini = Path(ayar.yollar.ocr_dizini)
    parcalar = []
    gezgin = secilen if sessiz else tqdm(secilen, desc="Parcalama (" + strateji + ")",
                                         unit="belge")
    for m in gezgin:
        kayit = json.loads((ocr_dizini / (m["doc_id"] + ".json")).read_text(encoding="utf-8"))
        parcalar.extend(chunk_mod.belge_parcala(
            kayit, m,
            boyut=int(ayar.parcalama.boyut),
            ortusme=int(ayar.parcalama.ortusme),
            strateji=strateji,
            onek_ekle=bool(ayar.parcalama.get("baglam_oneki", True)),
            gommeci=gommeci,
        ))
    if not sessiz:
        uzunluk = [len(p["metin"]) for p in parcalar] or [0]
        print("[+] " + strateji + ": " + str(len(parcalar)) + " parca, "
              + "ortalama " + str(int(sum(uzunluk) / len(uzunluk))) + " karakter.")
    return parcalar


def sorulari_uret(ayar, parcalar: list, adet: int, tohum: int = 7) -> list:
    """LLM ile Turkce degerlendirme sorulari uretir. Dogru cevap = kaynagi olan belge."""
    istemci = llm_mod.olustur(ayar)
    if not istemci.canli_mi():
        print("[!] Ollama calismiyor, soru uretilemiyor.")
        sys.exit(1)

    # her belgeden en fazla bir soru -> cesitlilik
    rastgele = random.Random(tohum)
    belgeye_gore = defaultdict(list)
    for p in parcalar:
        if len(p["metin"]) > 400:
            belgeye_gore[p["doc_id"]].append(p)

    doc_idler = list(belgeye_gore)
    rastgele.shuffle(doc_idler)

    sorular = []
    for doc_id in tqdm(doc_idler[:adet], desc="Soru uretimi", unit="soru"):
        p = rastgele.choice(belgeye_gore[doc_id])
        try:
            ham = istemci.uret(SORU_ISTEMI.format(metin=p["metin"][:2200]),
                               sistem="Sen teknik bir degerlendirme seti hazirliyorsun. "
                                      "Sadece JSON dondur.",
                               json_modu=True)
            v = llm_mod.json_ayikla(ham)
        except Exception as e:
            print("  ! " + str(e)[:80])
            continue
        soru = (v.get("soru") or "").strip()
        if len(soru) < 12:
            continue
        sorular.append({
            "soru": soru,
            "dogru_doc_id": doc_id,
            "dosya": p["dosya_adi"],
            "kaynak_parca": p["metin"][:200],
        })
    return sorular


# ─────────────────────────────────────────────────────────────
# Olcum
# ─────────────────────────────────────────────────────────────
def belge_siralamasi(skorlar: np.ndarray, parca_doc: list) -> list:
    """Parca skorlarindan tekil belge siralamasi (belgenin en iyi parcasi temsil eder)."""
    sira = np.argsort(-skorlar)
    gorulen, siralama = set(), []
    for i in sira:
        d = parca_doc[i]
        if d in gorulen:
            continue
        gorulen.add(d)
        siralama.append(d)
        if len(siralama) >= 20:
            break
    return siralama


def metrikler(siralamalar: list, dogrular: list) -> dict:
    r1 = r3 = r5 = 0
    mrr = 0.0
    for sira, dogru in zip(siralamalar, dogrular):
        if dogru in sira:
            k = sira.index(dogru)
            if k == 0: r1 += 1
            if k < 3:  r3 += 1
            if k < 5:  r5 += 1
            if k < 10: mrr += 1.0 / (k + 1)
    n = max(1, len(dogrular))
    return {
        "R@1": r1 / n, "R@3": r3 / n, "R@5": r5 / n, "MRR@10": mrr / n,
    }


def dense_olc(ayar, model_adi: str, parcalar: list, sorular: list,
              etiket: str | None = None, hazir_gommeci=None) -> dict:
    import torch

    # Gomme, bagalm onekli metin uzerinden yapilir (indeksle ayni davranis)
    metinler = [p.get("gomme_metni") or p["metin"] for p in parcalar]
    parca_doc = [p["doc_id"] for p in parcalar]

    if torch.cuda.is_available():
        torch.cuda.reset_peak_memory_stats()

    t0 = time.time()
    gommeci = hazir_gommeci or embed_mod.STGommeci(
        model_adi=model_adi,
        cihaz=ayar.gomme.cihaz,
        batch=int(ayar.gomme.batch),
        yari_hassasiyet=bool(ayar.gomme.get("yari_hassasiyet", False)),
        azami_uzunluk=int(ayar.gomme.get("azami_uzunluk", 1024)),
    )
    yukleme = time.time() - t0

    t0 = time.time()
    B = np.asarray(gommeci.belgeler(metinler, ilerleme=True), dtype=np.float32)
    kodlama = time.time() - t0

    S = np.asarray([gommeci.sorgu(s["soru"]) for s in sorular], dtype=np.float32)

    vram = 0.0
    if torch.cuda.is_available():
        vram = torch.cuda.max_memory_allocated() / (1024 ** 3)

    benzerlik = S @ B.T  # vektorler normalize -> kosinus
    siralamalar = [belge_siralamasi(benzerlik[i], parca_doc) for i in range(len(sorular))]

    if hazir_gommeci is None:
        gommeci.bosalt()

    sonuc = metrikler(siralamalar, [s["dogru_doc_id"] for s in sorular])
    sonuc.update({
        "model": etiket or model_adi,
        "parca_sayisi": len(parcalar),
        "boyut": B.shape[1],
        "yukleme_sn": round(yukleme, 1),
        "kodlama_sn": round(kodlama, 1),
        "parca_sn": round(len(metinler) / max(kodlama, 0.001), 1),
        "vram_gb": round(vram, 2),
        "onek": bool(gommeci.onek_sorgu or gommeci.onek_belge),
    })
    return sonuc


def bm25_olc(parcalar: list, sorular: list, etiket: str | None = None) -> dict:
    """Referans cizgisi: sadece anahtar kelime aramasi (ceviri yok)."""
    from rank_bm25 import BM25Okapi

    jetonla = lambda s: re.findall(r"[a-z0-9à-ɏ]+", s.lower())  # noqa: E731
    t0 = time.time()
    bm = BM25Okapi([jetonla(p.get("gomme_metni") or p["metin"]) for p in parcalar])
    parca_doc = [p["doc_id"] for p in parcalar]

    siralamalar = []
    for s in sorular:
        skor = np.asarray(bm.get_scores(jetonla(s["soru"])), dtype=np.float32)
        siralamalar.append(belge_siralamasi(skor, parca_doc))

    sonuc = metrikler(siralamalar, [s["dogru_doc_id"] for s in sorular])
    sonuc.update({"model": etiket or "BM25 (referans, cevirisiz)", "boyut": 0,
                  "parca_sayisi": len(parcalar),
                  "yukleme_sn": 0.0, "kodlama_sn": round(time.time() - t0, 1),
                  "parca_sn": 0.0, "vram_gb": 0.0, "onek": False})
    return sonuc


# ─────────────────────────────────────────────────────────────
def tablo_yaz(sonuclar: list) -> None:
    basliklar = ["Model / parcalayici", "R@1", "R@3", "R@5", "MRR@10", "Parca",
                 "Boyut", "parca/sn", "VRAM"]
    satirlar = []
    for s in sonuclar:
        satirlar.append([
            s["model"],
            "%.3f" % s["R@1"], "%.3f" % s["R@3"], "%.3f" % s["R@5"], "%.3f" % s["MRR@10"],
            str(s.get("parca_sayisi", "-")),
            str(s["boyut"]) if s["boyut"] else "-",
            "%.0f" % s["parca_sn"] if s["parca_sn"] else "-",
            ("%.1f GB" % s["vram_gb"]) if s["vram_gb"] else "-",
        ])
    genislik = [max(len(basliklar[i]), max(len(r[i]) for r in satirlar))
                for i in range(len(basliklar))]
    ayirac = "-+-".join("-" * g for g in genislik)
    print("\n" + " | ".join(b.ljust(genislik[i]) for i, b in enumerate(basliklar)))
    print(ayirac)
    for r in satirlar:
        print(" | ".join(r[i].ljust(genislik[i]) for i in range(len(r))))
    print()

    en_iyi = max(sonuclar, key=lambda s: (s["MRR@10"], s["R@5"]))
    print("En yuksek MRR@10: " + en_iyi["model"])
    dense = [s for s in sonuclar if s["boyut"]]
    if len(dense) > 1:
        a, b = sorted(dense, key=lambda s: -s["MRR@10"])[:2]
        fark = (a["MRR@10"] - b["MRR@10"]) / max(b["MRR@10"], 1e-9) * 100
        print("Fark: %s, %s modelinden %%%.1f daha iyi." % (a["model"], b["model"], fark))
        if abs(fark) < 5:
            print("NOT: %5'in altindaki fark bu orneklem buyuklugunde gurultu sayilir; "
                  "daha kucuk/hizli olani secmek mantikli.")


def main():
    p = argparse.ArgumentParser(description="Gomme modeli karsilastirmasi")
    p.add_argument("--config", default=None)
    p.add_argument("--ornek", type=int, default=40, help="orneklemdeki belge sayisi")
    p.add_argument("--soru-uret", type=int, default=0, metavar="N",
                   help="LLM ile N adet Turkce degerlendirme sorusu uret ve cik")
    p.add_argument("--modeller", nargs="+", default=VARSAYILAN_MODELLER)
    p.add_argument("--parcalayici", nargs="+", default=None,
                   metavar="STRATEJI",
                   help="karsilastirilacak parcalama stratejileri: sabit yapisal anlamsal "
                        "(varsayilan: config.yaml'daki strateji)")
    p.add_argument("--bm25", action="store_true", default=True,
                   help="BM25 referans cizgisini de olc")
    p.add_argument("--tohum", type=int, default=42)
    args = p.parse_args()

    ayar = cfg.yukle(args.config)
    deg_dizini = Path(ayar.yollar.manifest).parent / "degerlendirme"
    deg_dizini.mkdir(parents=True, exist_ok=True)
    soru_yolu = deg_dizini / "sorular.json"

    stratejiler = args.parcalayici or [ayar.parcalama.get("strateji", "yapisal")]
    secilen = _orneklem(ayar, args.ornek, args.tohum)
    print("[+] " + str(len(secilen)) + " belge secildi.")

    if args.soru_uret:
        temel = parcalari_getir(ayar, secilen, "yapisal")
        sorular = sorulari_uret(ayar, temel, args.soru_uret)
        soru_yolu.write_text(json.dumps(sorular, ensure_ascii=False, indent=1), encoding="utf-8")
        print("\n[+] " + str(len(sorular)) + " soru -> " + str(soru_yolu))
        print("    Dosyayi acip sorulari duzeltin, kendi gercek sorularinizi ekleyin,")
        print("    sonra --soru-uret olmadan tekrar calistirin.")
        return

    if not soru_yolu.exists():
        print("[!] Soru seti yok: " + str(soru_yolu))
        print("    Once uretin:  python scripts/gomme_karsilastir.py --ornek "
              + str(args.ornek) + " --soru-uret 25")
        sys.exit(1)

    sorular = json.loads(soru_yolu.read_text(encoding="utf-8"))
    gecerli_docs = {m["doc_id"] for m in secilen}
    atlanan = [s for s in sorular if s["dogru_doc_id"] not in gecerli_docs]
    sorular = [s for s in sorular if s["dogru_doc_id"] in gecerli_docs]
    if atlanan:
        print("[!] " + str(len(atlanan)) + " soru orneklem disinda kaldi, atlandi "
              "(--ornek degerini buyutun ya da ayni --tohum ile calistirin).")
    if not sorular:
        print("[!] Olculecek soru kalmadi."); sys.exit(1)

    print("[*] " + str(len(sorular)) + " soru, " + str(len(gecerli_docs)) + " belge, "
          + "parcalayici: " + ", ".join(stratejiler) + "\n")

    tek_strateji = len(stratejiler) == 1
    sonuclar = []

    for strateji in stratejiler:
        # "anlamsal" parcalama bir gommeci ister. Tum modeller icin ayni parcalari
        # kullanmak karsilastirmayi adil kilar, bu yuzden ilk model ile bir kez uretilir.
        yardimci = None
        if strateji == "anlamsal":
            print("[i] anlamsal parcalar " + args.modeller[0] + " ile uretiliyor "
                  "(tum modellerde ayni parcalar kullanilir).")
            yardimci = embed_mod.STGommeci(
                model_adi=args.modeller[0], cihaz=ayar.gomme.cihaz,
                batch=int(ayar.gomme.batch),
                yari_hassasiyet=bool(ayar.gomme.get("yari_hassasiyet", False)),
                azami_uzunluk=int(ayar.gomme.get("azami_uzunluk", 1024)),
            )
        try:
            parcalar = parcalari_getir(ayar, secilen, strateji, gommeci=yardimci)
        except Exception as e:
            print("  [HATA] " + strateji + " parcalanamadi: " + str(e)[:160])
            if yardimci:
                yardimci.bosalt()
            continue

        def ad(temel):
            return temel if tek_strateji else temel + " @ " + strateji

        if args.bm25:
            sonuclar.append(bm25_olc(parcalar, sorular, ad("BM25 (cevirisiz)")))
        for m in args.modeller:
            print("=== " + m + " @ " + strateji + " ===")
            try:
                sonuclar.append(dense_olc(
                    ayar, m, parcalar, sorular, etiket=ad(m),
                    hazir_gommeci=yardimci if (yardimci and m == args.modeller[0]) else None,
                ))
            except Exception as e:
                print("  [HATA] " + type(e).__name__ + ": " + str(e)[:200])

        if yardimci:
            yardimci.bosalt()

    if not sonuclar:
        print("[!] Hicbir olcum yapilamadi."); sys.exit(1)

    tablo_yaz(sonuclar)

    rapor = deg_dizini / "gomme_karsilastirma.json"
    rapor.write_text(json.dumps(
        {"soru_sayisi": len(sorular), "belge_sayisi": len(gecerli_docs),
         "stratejiler": stratejiler, "modeller": args.modeller, "sonuclar": sonuclar},
        ensure_ascii=False, indent=1), encoding="utf-8")
    print("Ayrinti: " + str(rapor))
    print("\nSectiginiz modeli config.yaml > gomme.model alanina yazip")
    print("'python src/cli.py index --yeniden' ile indeksi kurun.")


if __name__ == "__main__":
    main()
