"""Her belge icin makine kodu, tur, Turkce baslik/ozet uretir -> manifest.jsonl"""
from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path

from tqdm import tqdm

import config as cfg
import llm as llm_mod
import ocr as ocr_mod

META_ISTEM = """Asagida taranmis bir teknik belgenin ilk sayfalarindan alinan metin var.
Belge Ingilizce veya Romence olabilir. Sen ciktiyi TURKCE uretmelisin.

Sadece su alanlara sahip gecerli bir JSON dondur:
{{
  "baslik_tr": "belgenin Turkce basligi (en fazla 90 karakter)",
  "ozet_tr": "2-3 cumlelik Turkce ozet",
  "belge_turu": "kilavuz|teknik sartname|bakim talimati|devre semasi|yedek parca listesi|rapor|sertifika|teklif|diger",
  "makine_adaylari": ["metinde gecen makine/model/tip adlari, aynen yazildigi gibi"],
  "kaynak_dili": "en|ro|karisik|bilinmiyor",
  "anahtar_kelimeler_tr": ["en fazla 8 Turkce anahtar kelime"]
}}

DOSYA ADI: {dosya_adi}

METIN:
---
{metin}
---"""


DOSYA_ADI_AGIRLIGI = 5   # dosya adindaki eslesme govdedekinden cok daha guvenilir


def _kural_ile_makine(metin: str, dosya_adi: str, harita: dict) -> tuple:
    """Takma ad eslesmesi ile makine kodu bulur. (kod, skor) doner."""
    ad_havuz = dosya_adi.lower()
    govde_havuz = metin.lower()
    sayac = Counter()
    for takma, kod in harita.items():
        if not takma:
            continue
        desen = r"(?<![a-z0-9])" + re.escape(takma) + r"(?![a-z0-9])"
        n_ad = len(re.findall(desen, ad_havuz))
        n_govde = len(re.findall(desen, govde_havuz))
        if n_ad or n_govde:
            sayac[kod] += n_ad * DOSYA_ADI_AGIRLIGI + n_govde
    if not sayac:
        return None, 0
    kod, n = sayac.most_common(1)[0]
    return kod, n


def _ilk_metin(kayit: dict, sayfa_sayisi: int = 4, sinir: int = 6000) -> str:
    parcalar = [s["metin"] for s in kayit["sayfalar"][:sayfa_sayisi] if s["metin"]]
    return "\n".join(parcalar)[:sinir]


def cikart(ayar, yeniden: bool = False, llm_kullan: bool = True) -> dict:
    ocr_dizini = Path(ayar.yollar.ocr_dizini)
    manifest_yolu = Path(ayar.yollar.manifest)
    harita = cfg.makine_haritasi(ayar)                    # metin taramasi icin
    tam_harita = cfg.makine_haritasi(ayar, kisa_dahil=True)  # LLM adayi eslestirmesi icin

    mevcut = {}
    if manifest_yolu.exists() and not yeniden:
        with open(manifest_yolu, "r", encoding="utf-8") as f:
            for satir in f:
                satir = satir.strip()
                if satir:
                    k = json.loads(satir)
                    mevcut[k["doc_id"]] = k

    istemci = llm_mod.olustur(ayar) if llm_kullan else None
    if istemci and not istemci.canli_mi():
        print("[!] Ollama'ya ulasilamiyor, sadece kural tabanli meta uretilecek.")
        istemci = None

    dosyalar = sorted(ocr_dizini.glob("*.json"))
    for jyol in tqdm(dosyalar, desc="Meta", unit="belge"):
        doc_id = jyol.stem
        if doc_id in mevcut:
            continue
        kayit = json.loads(jyol.read_text(encoding="utf-8"))
        bas = _ilk_metin(kayit)
        tam = ocr_mod.tam_metin(kayit)[:200000]

        kod, gecme = _kural_ile_makine(tam, kayit["dosya_adi"], harita)

        meta = {
            "doc_id": doc_id,
            "dosya_adi": kayit["dosya_adi"],
            "kaynak": kayit["kaynak"],
            "sayfa_sayisi": kayit["sayfa_sayisi"],
            "ocr_sayfa_sayisi": kayit["ocr_sayfa_sayisi"],
            "karakter_sayisi": kayit["karakter_sayisi"],
            "makine": kod or "bilinmiyor",
            "makine_guven": gecme,
            "baslik_tr": "",
            "ozet_tr": "",
            "belge_turu": "diger",
            "kaynak_dili": "bilinmiyor",
            "anahtar_kelimeler_tr": [],
            "makine_adaylari": [],
        }

        if istemci and bas.strip():
            try:
                ham = istemci.uret(
                    META_ISTEM.format(dosya_adi=kayit["dosya_adi"], metin=bas),
                    json_modu=True,
                )
                v = llm_mod.json_ayikla(ham)
                for alan in ("baslik_tr", "ozet_tr", "belge_turu", "kaynak_dili"):
                    if v.get(alan):
                        meta[alan] = str(v[alan]).strip()
                for alan in ("anahtar_kelimeler_tr", "makine_adaylari"):
                    if isinstance(v.get(alan), list):
                        meta[alan] = [str(x).strip() for x in v[alan]][:8]
                # LLM'in buldugu aday adlari kural haritasinda tekrar ara.
                # Burada kisa kodlar da gecerli: LLM "A" dediyse gercekten A demektir.
                if meta["makine"] == "bilinmiyor":
                    for aday in meta["makine_adaylari"]:
                        k2 = tam_harita.get(aday.lower().strip())
                        if k2:
                            meta["makine"] = k2
                            meta["makine_guven"] = 1
                            break
            except Exception as e:
                print("  ! Meta LLM hatasi " + kayit["dosya_adi"] + ": " + str(e))

        if not meta["baslik_tr"]:
            meta["baslik_tr"] = Path(kayit["dosya_adi"]).stem

        mevcut[doc_id] = meta

    manifest_yolu.parent.mkdir(parents=True, exist_ok=True)
    with open(manifest_yolu, "w", encoding="utf-8") as f:
        for m in mevcut.values():
            f.write(json.dumps(m, ensure_ascii=False) + "\n")

    dagilim = Counter(m["makine"] for m in mevcut.values())
    print("[+] " + str(len(mevcut)) + " belge. Makine dagilimi: " + str(dict(dagilim)))
    return {"toplam": len(mevcut), "dagilim": dict(dagilim)}


def manifest_oku(ayar) -> dict:
    yol = Path(ayar.yollar.manifest)
    if not yol.exists():
        return {}
    cikti = {}
    with open(yol, "r", encoding="utf-8") as f:
        for satir in f:
            satir = satir.strip()
            if satir:
                k = json.loads(satir)
                cikti[k["doc_id"]] = k
    return cikti


def bilinmeyenler(ayar) -> list:
    return [m for m in manifest_oku(ayar).values() if m["makine"] == "bilinmiyor"]
