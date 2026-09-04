"""Parcalama stratejileri.

Uc strateji var, config.yaml > parcalama.strateji ile secilir:

  sabit    - sabit boyutlu, cumle/paragraf sinirinda kesen basit yontem
  yapisal  - (varsayilan) bolum basliklarinda boler, tablo ve listeleri bolmez
  anlamsal - ardisik paragraflari gomup kosinus kirilma noktasindan boler

Teknik kilavuzlarda "yapisal" genellikle en iyisidir: belgeler zaten numarali
bolumlerden olusur ve tablolar (hata kodlari, yedek parca listeleri) bolununce
anlamlarini kaybeder. "anlamsal" pahalidir ve OCR metninde cumle sinirlari
guvenilmez oldugu icin beklendigi kadar iyi calismayabilir -- olcmeden secmeyin:

    python scripts/gomme_karsilastir.py --parcalayici sabit yapisal anlamsal

Her parca hem "metin" (LLM'e ve kullaniciya gosterilen ham govde) hem de
"gomme_metni" (basina belge/bolum/makine bagalmi eklenmis hali) tasir. Vektor ve
BM25 indeksleri gomme_metni uzerinden kurulur; Turkce baslik boylece gomulen
metnin icine girer ve Turkce sorgu ile eslesme belirgin kolaylasir.
"""
from __future__ import annotations

import re

BOSLUK = re.compile(r"[ \t]+")
COK_SATIR = re.compile(r"\n{3,}")

# ── Baslik desenleri ────────────────────────────────────────────────────────
# "5.2 Lubrication", "3. SAFETY", "10.1.4 Hydraulic block"
NUMARALI = re.compile(r"^\s*\d{1,2}(\.\d{1,2}){0,3}[.)]?\s+\S")
# "FC-902", "LS-4471", "CAL-88" gibi dokuman/bolum kodlari
KOD_BASLIK = re.compile(r"^\s*[A-Z]{2,5}[-\s]?\d{2,5}\b")
# Buyuk harfli baslik satiri (Turkce/Romence harfler dahil)
BUYUK_HARF = re.compile(r"^[A-ZÄÖÜŞİĞÇÎÂĂȘȚ0-9][A-ZÄÖÜŞİĞÇÎÂĂȘȚ0-9 \-/&().,:'’]{5,78}$")
# Cumle sonu isareti
CUMLE_SONU = re.compile(r"[.!?:;]\s*$")

# ── Tablo/liste satiri isaretleri ───────────────────────────────────────────
COK_BOSLUK = re.compile(r"\S {2,}\S")          # sutun ayirici olarak coklu bosluk
SAYI_YOGUN = re.compile(r"\d")
MADDE = re.compile(r"^\s*([-*•]|\d{1,3}[.)])\s+")


def temizle(metin: str) -> str:
    metin = metin.replace("\r", "\n")
    metin = BOSLUK.sub(" ", metin)
    metin = COK_SATIR.sub("\n\n", metin)
    # OCR'da sik gorulen satir sonu tirelemesi: "mainte-\nnance" -> "maintenance"
    metin = re.sub(r"(\w)-\n(\w)", r"\1\2", metin)
    return metin.strip()


def _baslik_mi(satir: str) -> bool:
    s = satir.strip()
    if not s or len(s) > 90:
        return False
    if MADDE.match(s):
        return False
    if NUMARALI.match(s) and not CUMLE_SONU.search(s) and len(s) < 90:
        return True
    if KOD_BASLIK.match(s) and len(s) < 90:
        return True
    if BUYUK_HARF.match(s):
        # sadece sayilardan olusan satirlar (tablo) baslik degildir
        harf = sum(c.isalpha() for c in s)
        return harf >= 4
    return False


def _tablo_satiri_mi(satir: str) -> bool:
    s = satir.strip()
    if not s:
        return False
    if MADDE.match(s):
        return True
    if COK_BOSLUK.search(s):
        return True
    rakam = sum(c.isdigit() for c in s)
    return len(s) < 90 and rakam >= max(3, len(s) * 0.18)


def baglam_oneki(meta: dict, bolum: str = "") -> str:
    """Gomulen metnin basina eklenen kisa bagalm satiri."""
    parcalar = []
    baslik = (meta.get("baslik_tr") or meta.get("dosya_adi") or "").strip()
    if baslik:
        parcalar.append("Belge: " + baslik)
    makine = meta.get("makine_adi") or meta.get("makine")
    if makine and makine != "bilinmiyor":
        parcalar.append("Makine: " + str(makine))
    tur = meta.get("belge_turu")
    if tur and tur != "diger":
        parcalar.append("Tur: " + str(tur))
    if bolum:
        parcalar.append("Bolum: " + bolum.strip()[:90])
    if not parcalar:
        return ""
    return "[" + " | ".join(parcalar) + "]\n"


def _bol(metin: str, boyut: int, ortusme: int) -> list:
    """Sabit boyutlu bolme; cumle veya paragraf sinirini tercih eder."""
    if len(metin) <= boyut:
        return [metin] if metin else []
    parcalar = []
    i = 0
    while i < len(metin):
        son = min(i + boyut, len(metin))
        if son < len(metin):
            pencere = metin[i:son]
            for ayirici in ("\n\n", ". ", ".\n", "\n"):
                p = pencere.rfind(ayirici)
                if p > boyut * 0.5:
                    son = i + p + len(ayirici)
                    break
        parca = metin[i:son].strip()
        if parca:
            parcalar.append(parca)
        if son >= len(metin):
            break
        i = max(son - ortusme, i + 1)
    return parcalar


def _parca_kaydi(meta: dict, sira: int, govde: str, bolum: str,
                 sayfa_bas: int, sayfa_son: int, onek_ekle: bool) -> dict:
    onek = baglam_oneki(meta, bolum) if onek_ekle else ""
    return {
        "id": meta["doc_id"] + ":" + format(sira, "04d"),
        "metin": govde,
        "gomme_metni": onek + govde,
        "bolum": bolum,
        "doc_id": meta["doc_id"],
        "dosya_adi": meta["dosya_adi"],
        "kaynak": meta["kaynak"],
        "makine": meta.get("makine", "bilinmiyor"),
        "belge_turu": meta.get("belge_turu", "diger"),
        "baslik_tr": meta.get("baslik_tr", ""),
        "sayfa_bas": sayfa_bas or 0,
        "sayfa_son": sayfa_son or 0,
    }


# ════════════════════════════════════════════════════════════════════════════
# 1) Sabit boyutlu (eski davranis)
# ════════════════════════════════════════════════════════════════════════════
def sabit_parcala(kayit: dict, meta: dict, boyut: int = 1400, ortusme: int = 220,
                  onek_ekle: bool = True) -> list:
    parcalar = []
    durum = {"tampon": "", "bas": None, "son": None}

    def bosalt():
        if durum["tampon"].strip():
            for govde in _bol(temizle(durum["tampon"]), boyut, ortusme):
                parcalar.append(_parca_kaydi(meta, len(parcalar), govde, "",
                                             durum["bas"], durum["son"], onek_ekle))
        durum.update(tampon="", bas=None, son=None)

    for s in kayit["sayfalar"]:
        m = (s["metin"] or "").strip()
        if not m:
            continue
        if durum["bas"] is None:
            durum["bas"] = s["sayfa"]
        durum["son"] = s["sayfa"]
        durum["tampon"] += ("\n\n" if durum["tampon"] else "") + m
        if len(durum["tampon"]) >= boyut * 2:
            bosalt()
    bosalt()
    return parcalar


# ════════════════════════════════════════════════════════════════════════════
# 2) Yapisal (varsayilan)
# ════════════════════════════════════════════════════════════════════════════
def yapisal_parcala(kayit: dict, meta: dict, boyut: int = 1400, ortusme: int = 220,
                    onek_ekle: bool = True, tablo_carpani: float = 2.2) -> list:
    """Bolum basliklarinda boler; tablo/liste bloklarini bolmemeye calisir."""
    # 1) Tum satirlari sayfa numarasiyla birlikte topla
    satirlar = []
    for s in kayit["sayfalar"]:
        ham = (s["metin"] or "")
        if not ham.strip():
            continue
        for satir in temizle(ham).split("\n"):
            satirlar.append((satir, s["sayfa"]))

    if not satirlar:
        return []

    # 2) Basliklara gore bloklara ayir
    bloklar = []          # [{baslik, satirlar:[(metin, sayfa)]}]
    simdiki = {"baslik": "", "satirlar": []}
    for satir, sayfa in satirlar:
        if _baslik_mi(satir) and simdiki["satirlar"]:
            bloklar.append(simdiki)
            simdiki = {"baslik": satir.strip(), "satirlar": []}
        elif _baslik_mi(satir) and not simdiki["satirlar"]:
            simdiki["baslik"] = satir.strip()
        else:
            simdiki["satirlar"].append((satir, sayfa))
    if simdiki["satirlar"] or simdiki["baslik"]:
        bloklar.append(simdiki)

    # 3) Bloklari parcalara cevir; kucuk bloklari birlestir, buyukleri bol
    parcalar = []
    birikim = {"metin": "", "baslik": "", "bas": None, "son": None}

    def yaz(govde: str, baslik: str, bas: int, son: int):
        if govde.strip():
            parcalar.append(_parca_kaydi(meta, len(parcalar), govde.strip(),
                                         baslik, bas, son, onek_ekle))

    def birikimi_bosalt():
        if birikim["metin"].strip():
            yaz(birikim["metin"], birikim["baslik"], birikim["bas"], birikim["son"])
        birikim.update(metin="", baslik="", bas=None, son=None)

    for blok in bloklar:
        if not blok["satirlar"] and not blok["baslik"]:
            continue
        govde = "\n".join(x[0] for x in blok["satirlar"]).strip()
        sayfalar = [x[1] for x in blok["satirlar"]]
        bas = min(sayfalar) if sayfalar else (birikim["son"] or 0)
        son = max(sayfalar) if sayfalar else bas
        baslik = blok["baslik"]

        tam = ((baslik + "\n") if baslik else "") + govde
        if not tam.strip():
            continue

        # Blok tablo agirlikliysa daha buyuk kalmasina izin ver
        veri_satiri = sum(1 for x in blok["satirlar"] if _tablo_satiri_mi(x[0]))
        tabloya_benzer = blok["satirlar"] and veri_satiri >= len(blok["satirlar"]) * 0.6
        ust_sinir = int(boyut * (tablo_carpani if tabloya_benzer else 1.0))

        if len(tam) > ust_sinir:
            birikimi_bosalt()
            if tabloya_benzer:
                # tabloyu satir butunlugunu koruyarak bol
                gecici, g_bas = "", bas
                for satir, sayfa in blok["satirlar"]:
                    if gecici and len(gecici) + len(satir) > ust_sinir:
                        yaz(((baslik + "\n") if baslik else "") + gecici, baslik, g_bas, sayfa)
                        gecici, g_bas = "", sayfa
                    gecici += ("\n" if gecici else "") + satir
                if gecici:
                    yaz(((baslik + "\n") if baslik else "") + gecici, baslik, g_bas, son)
            else:
                for i, g in enumerate(_bol(tam, boyut, ortusme)):
                    # her parcaya bolum basligini tasi
                    govde_i = g if (i == 0 or not baslik) else baslik + "\n" + g
                    yaz(govde_i, baslik, bas, son)
            continue

        # Kucuk blok: bir oncekiyle birlestir (cok kucuk parcalar aramayi bozar)
        if birikim["metin"] and len(birikim["metin"]) + len(tam) > boyut:
            birikimi_bosalt()
        if not birikim["metin"]:
            birikim.update(baslik=baslik, bas=bas)
        birikim["metin"] += ("\n\n" if birikim["metin"] else "") + tam
        birikim["son"] = son

    birikimi_bosalt()
    return parcalar


# ════════════════════════════════════════════════════════════════════════════
# 3) Anlamsal (deneysel, pahali)
# ════════════════════════════════════════════════════════════════════════════
def anlamsal_parcala(kayit: dict, meta: dict, gommeci, boyut: int = 1400,
                     ortusme: int = 220, esik_yuzdesi: int = 88,
                     onek_ekle: bool = True) -> list:
    """Ardisik paragraflari gomup kosinus mesafesinin sicradigi yerden boler.

    Not: her paragrafi ayrica gommek gerekir; 1000 PDF'te indeks suresine saatler
    ekler. OCR metninde paragraf sinirlari da guvenilmez oldugu icin kazanci
    olcmeden varsaymayin.
    """
    import numpy as np

    birimler = []  # (metin, sayfa)
    for s in kayit["sayfalar"]:
        ham = (s["metin"] or "")
        if not ham.strip():
            continue
        for p in re.split(r"\n\s*\n", temizle(ham)):
            p = p.strip()
            if len(p) > 25:
                birimler.append((p, s["sayfa"]))

    if len(birimler) < 2:
        return yapisal_parcala(kayit, meta, boyut, ortusme, onek_ekle)

    vektorler = np.asarray(gommeci.belgeler([b[0] for b in birimler], ilerleme=False),
                           dtype=np.float32)
    mesafeler = 1.0 - np.sum(vektorler[:-1] * vektorler[1:], axis=1)
    if len(mesafeler) == 0:
        return yapisal_parcala(kayit, meta, boyut, ortusme, onek_ekle)
    esik = float(np.percentile(mesafeler, esik_yuzdesi))

    parcalar = []
    gecici, bas, son = "", birimler[0][1], birimler[0][1]
    for i, (p, sayfa) in enumerate(birimler):
        if gecici and (len(gecici) + len(p) > boyut * 1.6
                       or (i > 0 and mesafeler[i - 1] > esik and len(gecici) > boyut * 0.4)):
            parcalar.append(_parca_kaydi(meta, len(parcalar), gecici, "", bas, son, onek_ekle))
            gecici, bas = "", sayfa
        gecici += ("\n\n" if gecici else "") + p
        son = sayfa
    if gecici.strip():
        parcalar.append(_parca_kaydi(meta, len(parcalar), gecici, "", bas, son, onek_ekle))
    return parcalar


# ════════════════════════════════════════════════════════════════════════════
def belge_parcala(kayit: dict, meta: dict, boyut: int = 1400, ortusme: int = 220,
                  strateji: str = "yapisal", onek_ekle: bool = True, gommeci=None) -> list:
    """Yapilandirmaya gore uygun parcalayiciyi calistirir."""
    s = (strateji or "yapisal").lower()
    if s == "sabit":
        return sabit_parcala(kayit, meta, boyut, ortusme, onek_ekle)
    if s == "anlamsal":
        if gommeci is None:
            raise ValueError("anlamsal parcalama icin gommeci gerekli")
        return anlamsal_parcala(kayit, meta, gommeci, boyut, ortusme, onek_ekle=onek_ekle)
    return yapisal_parcala(kayit, meta, boyut, ortusme, onek_ekle)
