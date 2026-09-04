"""Makine bazli Turkce baslik/konu cikarimi (map-reduce) ve rapor uretimi."""
from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

from tqdm import tqdm

import config as cfg
import llm as llm_mod
import metadata as meta_mod
import ocr as ocr_mod

MAP_ISTEM = """Asagida bir teknik belgenin (Ingilizce veya Romence, taranmis) metni var.
Bu belgenin icerdigi ANA BASLIKLARI ve ALT BASLIKLARI TURKCE olarak cikar.
Belgede acik baslik yoksa, iceriginden anlamli konu basliklari uret.

Sadece su JSON'u dondur:
{{
  "belge_basligi_tr": "kisa Turkce baslik",
  "basliklar": [
    {{"baslik": "Turkce ana baslik", "alt_basliklar": ["Turkce alt baslik", "..."], "sayfa": 0}}
  ]
}}

En fazla 12 ana baslik uret. Sayfa numarasini bilmiyorsan 0 yaz.

BELGE: {dosya_adi}
METIN:
---
{metin}
---"""

REDUCE_ISTEM = """Asagida "{makine}" makinesine ait {belge_sayisi} belgeden cikarilmis Turkce baslik listeleri var.
Bunlari tek bir DUZENLI KONU AGACINDA birlestir.

Kurallar:
- Tekrar eden ve es anlamli basliklari birlestir.
- Mantikli kategorilere grupla (ornek: Genel Tanitim, Teknik Ozellikler, Kurulum, Calistirma,
  Bakim ve Yaglama, Elektrik/Otomasyon, Ariza Giderme, Yedek Parca, Guvenlik, Sertifikalar).
- Ciktinin tamami TURKCE olsun.
- Her ana baslik altinda en fazla 8 alt baslik olsun.

Sadece su JSON'u dondur:
{{
  "kategoriler": [
    {{"kategori": "Turkce kategori adi",
      "basliklar": ["Turkce baslik", "..."],
      "ilgili_belgeler": ["dosya adi", "..."]}}
  ]
}}

HAM BASLIKLAR:
{ham}"""


def _doc_metni(ayar, doc_id: str, sinir: int = 14000) -> str:
    jyol = Path(ayar.yollar.ocr_dizini) / (doc_id + ".json")
    if not jyol.exists():
        return ""
    kayit = json.loads(jyol.read_text(encoding="utf-8"))
    tam = ocr_mod.tam_metin(kayit)
    if len(tam) <= sinir:
        return tam
    # bas + orta + son: uzun kilavuzlarda tum bolumleri gorebilmek icin
    p = sinir // 3
    orta = len(tam) // 2
    return tam[:p] + "\n[...]\n" + tam[orta:orta + p] + "\n[...]\n" + tam[-p:]


def belgeler(ayar, makine: str | None = None, belge_turu: str | None = None) -> list:
    """Filtreleme: makine ve/veya belge turune gore belge listesi."""
    manifest = meta_mod.manifest_oku(ayar)
    cikti = []
    for m in manifest.values():
        if makine and m.get("makine") != makine:
            continue
        if belge_turu and m.get("belge_turu") != belge_turu:
            continue
        cikti.append(m)
    return sorted(cikti, key=lambda x: (x.get("belge_turu", ""), x.get("dosya_adi", "")))


def basliklar_map(ayar, makine: str, limit: int | None = None, onbellek: bool = True) -> list:
    """Her belge icin Turkce baslik cikarimi. Sonuclar diske onbelleklenir."""
    istemci = llm_mod.olustur(ayar)
    onb_dizin = Path(ayar.yollar.rapor_dizini) / "_basliklar"
    onb_dizin.mkdir(parents=True, exist_ok=True)

    hedefler = belgeler(ayar, makine=makine)
    if limit:
        hedefler = hedefler[:limit]

    sonuclar = []
    for m in tqdm(hedefler, desc="Baslik (" + makine + ")", unit="belge"):
        onb = onb_dizin / (m["doc_id"] + ".json")
        if onbellek and onb.exists():
            sonuclar.append(json.loads(onb.read_text(encoding="utf-8")))
            continue
        metin = _doc_metni(ayar, m["doc_id"])
        if not metin.strip():
            continue
        try:
            ham = istemci.uret(
                MAP_ISTEM.format(dosya_adi=m["dosya_adi"], metin=metin),
                json_modu=True,
            )
            v = llm_mod.json_ayikla(ham)
        except Exception as e:
            print("  ! Baslik hatasi " + m["dosya_adi"] + ": " + str(e))
            continue
        kayit = {
            "doc_id": m["doc_id"],
            "dosya_adi": m["dosya_adi"],
            "belge_turu": m.get("belge_turu", "diger"),
            "belge_basligi_tr": v.get("belge_basligi_tr") or m.get("baslik_tr", ""),
            "basliklar": v.get("basliklar", []) if isinstance(v.get("basliklar"), list) else [],
        }
        onb.write_text(json.dumps(kayit, ensure_ascii=False, indent=1), encoding="utf-8")
        sonuclar.append(kayit)
    return sonuclar


def basliklar_reduce(ayar, makine: str, map_sonuclari: list) -> dict:
    istemci = llm_mod.olustur(ayar)
    satirlar = []
    for r in map_sonuclari:
        satirlar.append("## " + r["dosya_adi"] + " (" + r["belge_turu"] + ")")
        for b in r["basliklar"]:
            if isinstance(b, dict):
                satirlar.append("- " + str(b.get("baslik", "")))
                for alt in (b.get("alt_basliklar") or [])[:6]:
                    satirlar.append("  - " + str(alt))
            else:
                satirlar.append("- " + str(b))
    ham = "\n".join(satirlar)

    # Cok uzunsa parcali ozetle
    if len(ham) > 30000:
        ara_sonuclar = []
        adim = 25000
        for i in range(0, len(ham), adim):
            try:
                y = istemci.uret(
                    REDUCE_ISTEM.format(makine=makine, belge_sayisi=len(map_sonuclari),
                                        ham=ham[i:i + adim]),
                    json_modu=True,
                )
                ara_sonuclar.append(json.dumps(llm_mod.json_ayikla(y), ensure_ascii=False))
            except Exception as e:
                print("  ! Reduce hatasi: " + str(e))
        ham = "\n".join(ara_sonuclar)[:28000]

    try:
        y = istemci.uret(
            REDUCE_ISTEM.format(makine=makine, belge_sayisi=len(map_sonuclari), ham=ham),
            json_modu=True,
        )
        return llm_mod.json_ayikla(y)
    except Exception as e:
        print("  ! Reduce hatasi: " + str(e))
        return {"kategoriler": []}


def rapor_uret(ayar, makine_kodu: str, limit: int | None = None) -> Path:
    ad = cfg.makine_adi(ayar, makine_kodu)
    dokumanlar = belgeler(ayar, makine=makine_kodu)
    if not dokumanlar:
        print("[!] '" + makine_kodu + "' icin belge bulunamadi. config.yaml > makineler'i kontrol edin.")
    map_sonuclari = basliklar_map(ayar, makine_kodu, limit=limit)
    agac = basliklar_reduce(ayar, makine_kodu, map_sonuclari)

    tur_dagilim = Counter(d.get("belge_turu", "diger") for d in dokumanlar)
    sayfa_toplam = sum(int(d.get("sayfa_sayisi", 0)) for d in dokumanlar)

    satir = []
    satir.append("# " + ad + " - Belge Konu Haritasi")
    satir.append("")
    satir.append("- Belge sayisi: **" + str(len(dokumanlar)) + "**")
    satir.append("- Toplam sayfa: **" + str(sayfa_toplam) + "**")
    satir.append("- Belge turleri: " + ", ".join(k + " (" + str(v) + ")" for k, v in tur_dagilim.most_common()))
    satir.append("")
    satir.append("## Konu Basliklari")
    satir.append("")
    for kat in agac.get("kategoriler", []):
        satir.append("### " + str(kat.get("kategori", "Diger")))
        for b in kat.get("basliklar", []):
            satir.append("- " + str(b))
        ilgili = kat.get("ilgili_belgeler") or []
        if ilgili:
            satir.append("")
            satir.append("  _Ilgili belgeler:_ " + ", ".join(str(x) for x in ilgili[:10]))
        satir.append("")

    satir.append("## Belge Listesi")
    satir.append("")
    satir.append("| # | Baslik (TR) | Dosya | Tur | Sayfa |")
    satir.append("|---|---|---|---|---|")
    for i, d in enumerate(dokumanlar, start=1):
        satir.append("| " + str(i) + " | " + d.get("baslik_tr", "") + " | " + d["dosya_adi"]
                     + " | " + d.get("belge_turu", "") + " | " + str(d.get("sayfa_sayisi", "")) + " |")

    hedef = Path(ayar.yollar.rapor_dizini) / ("makine_" + makine_kodu + "_konu_haritasi.md")
    hedef.write_text("\n".join(satir), encoding="utf-8")
    print("[+] Rapor: " + str(hedef))
    return hedef
