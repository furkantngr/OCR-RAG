"""MakineRAG HTTP API + web arayuzu sunucusu.

Calistirma:
    python server/api.py
    veya: uvicorn server.api:app --host 127.0.0.1 --port 8000
"""
from __future__ import annotations

import json
import os
import sys
import threading
import time
import traceback
import uuid
from collections import Counter
from pathlib import Path

KOK = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(KOK / "src"))

from fastapi import Body, FastAPI, HTTPException, Query          # noqa: E402
from fastapi.middleware.cors import CORSMiddleware               # noqa: E402
from fastapi.responses import FileResponse, StreamingResponse    # noqa: E402
from fastapi.staticfiles import StaticFiles                      # noqa: E402

import config as cfg          # noqa: E402
import chat as chat_mod       # noqa: E402
import llm as llm_mod         # noqa: E402
import metadata as meta_mod   # noqa: E402
import report as report_mod   # noqa: E402

WEB = KOK / "web"

app = FastAPI(title="MakineRAG API", version="1.0", docs_url="/api/docs", redoc_url=None)
app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"]
)

# MAKINERAG_CONFIG ile farkli bir yapilandirma profili kullanilabilir
AYAR = cfg.yukle(os.environ.get("MAKINERAG_CONFIG") or None)


# ----------------------------------------------------------------------------
# Tembel yuklenen arama motoru (bge-m3 + Chroma ilk istekte yuklenir)
# ----------------------------------------------------------------------------
class Motor:
    def __init__(self):
        self._sohbet = None
        self._kilit = threading.Lock()
        self._yukleniyor = False
        self._hata = None

    @property
    def durum(self) -> str:
        if self._hata:
            return "hata"
        if self._sohbet is not None:
            return "hazir"
        return "yukleniyor" if self._yukleniyor else "bekliyor"

    def al(self) -> chat_mod.Sohbet:
        if self._sohbet is not None:
            return self._sohbet
        with self._kilit:
            if self._sohbet is not None:
                return self._sohbet
            self._yukleniyor = True
            try:
                self._sohbet = chat_mod.Sohbet(AYAR)
                self._hata = None
            except Exception as e:
                self._hata = str(e)
                raise
            finally:
                self._yukleniyor = False
        return self._sohbet


MOTOR = Motor()


# ----------------------------------------------------------------------------
# Manifest onbellegi (dosya degisince kendini yeniler)
# ----------------------------------------------------------------------------
class ManifestOnbellek:
    def __init__(self):
        self.veri: dict = {}
        self.mtime = -1.0

    def al(self) -> dict:
        yol = Path(AYAR.yollar.manifest)
        if not yol.exists():
            self.veri, self.mtime = {}, -1.0
            return self.veri
        m = yol.stat().st_mtime
        if m != self.mtime:
            self.veri = meta_mod.manifest_oku(AYAR)
            self.mtime = m
        return self.veri


MANIFEST = ManifestOnbellek()


# ----------------------------------------------------------------------------
# Arka plan is yoneticisi (rapor uretimi uzun surer)
# ----------------------------------------------------------------------------
ISLER: dict = {}
ISLER_KILIT = threading.Lock()


def _is_calistir(is_id: str, fn, *a, **kw):
    with ISLER_KILIT:
        ISLER[is_id].update(durum="calisiyor", baslangic=time.time())
    try:
        sonuc = fn(*a, **kw)
        with ISLER_KILIT:
            ISLER[is_id].update(durum="bitti", sonuc=str(sonuc), bitis=time.time())
    except Exception as e:
        traceback.print_exc()
        with ISLER_KILIT:
            ISLER[is_id].update(durum="hata", hata=str(e), bitis=time.time())


def _is_baslat(baslik: str, fn, *a, **kw) -> str:
    is_id = uuid.uuid4().hex[:12]
    with ISLER_KILIT:
        ISLER[is_id] = {"id": is_id, "baslik": baslik, "durum": "kuyrukta",
                        "olusturma": time.time()}
    threading.Thread(target=_is_calistir, args=(is_id, fn, *a), kwargs=kw,
                     daemon=True).start()
    return is_id


# ----------------------------------------------------------------------------
# Durum / meta uc noktalari
# ----------------------------------------------------------------------------
@app.get("/api/durum")
def durum():
    manifest = MANIFEST.al()
    dagilim = Counter(m.get("makine", "bilinmiyor") for m in manifest.values())

    parca = None
    try:
        import index_build as ix
        parca = ix.koleksiyon_ac(AYAR).count()
    except Exception:
        pass

    return {
        "belge_sayisi": len(manifest),
        "sayfa_sayisi": sum(int(m.get("sayfa_sayisi", 0)) for m in manifest.values()),
        "ocr_sayfa_sayisi": sum(int(m.get("ocr_sayfa_sayisi", 0)) for m in manifest.values()),
        "parca_sayisi": parca,
        "makine_dagilimi": dict(dagilim),
        "motor": MOTOR.durum,
        "ollama": llm_mod.olustur(AYAR).canli_mi(),
        "llm_model": AYAR.llm.model,
        "gomme_model": AYAR.gomme.model,
    }


@app.get("/api/makineler")
def makineler():
    manifest = MANIFEST.al()
    sayac = Counter(m.get("makine", "bilinmiyor") for m in manifest.values())
    sayfa = Counter()
    for m in manifest.values():
        sayfa[m.get("makine", "bilinmiyor")] += int(m.get("sayfa_sayisi", 0))

    cikti = []
    for m in AYAR.makineler:
        kod = str(m["kod"])
        cikti.append({
            "kod": kod, "ad": m["ad"],
            "takma_adlar": m.get("takma_adlar", []),
            "belge_sayisi": sayac.get(kod, 0),
            "sayfa_sayisi": sayfa.get(kod, 0),
        })
    if sayac.get("bilinmiyor"):
        cikti.append({
            "kod": "bilinmiyor", "ad": "Siniflandirilmamis", "takma_adlar": [],
            "belge_sayisi": sayac["bilinmiyor"], "sayfa_sayisi": sayfa["bilinmiyor"],
        })
    return cikti


@app.get("/api/turler")
def turler():
    sayac = Counter(m.get("belge_turu", "diger") for m in MANIFEST.al().values())
    return [{"tur": t, "sayi": n} for t, n in sayac.most_common()]


# ----------------------------------------------------------------------------
# Belgeler
# ----------------------------------------------------------------------------
@app.get("/api/belgeler")
def belgeler(
    makine: str | None = None,
    tur: str | None = None,
    q: str | None = None,
    sirala: str = "dosya_adi",
    yon: str = "asc",
    limit: int = Query(60, ge=1, le=500),
    ofset: int = Query(0, ge=0),
):
    kayitlar = report_mod.belgeler(AYAR, makine=makine, belge_turu=tur)

    if q:
        a = q.lower().strip()
        kayitlar = [
            k for k in kayitlar
            if a in (k.get("baslik_tr") or "").lower()
            or a in k.get("dosya_adi", "").lower()
            or a in (k.get("ozet_tr") or "").lower()
            or any(a in str(x).lower() for x in k.get("anahtar_kelimeler_tr", []))
        ]

    tersine = yon == "desc"
    if sirala in ("sayfa_sayisi", "ocr_sayfa_sayisi", "karakter_sayisi"):
        kayitlar.sort(key=lambda k: int(k.get(sirala, 0)), reverse=tersine)
    else:
        kayitlar.sort(key=lambda k: str(k.get(sirala, "")).lower(), reverse=tersine)

    return {
        "toplam": len(kayitlar),
        "ofset": ofset,
        "limit": limit,
        "kayitlar": kayitlar[ofset:ofset + limit],
    }


@app.get("/api/belge/{doc_id}")
def belge(doc_id: str):
    manifest = MANIFEST.al()
    if doc_id not in manifest:
        raise HTTPException(404, "Belge bulunamadi")
    m = dict(manifest[doc_id])

    jyol = Path(AYAR.yollar.ocr_dizini) / (doc_id + ".json")
    if jyol.exists():
        kayit = json.loads(jyol.read_text(encoding="utf-8"))
        m["sayfalar"] = [
            {"sayfa": s["sayfa"], "ocr": s["ocr"], "uzunluk": len(s["metin"] or ""),
             "onizleme": (s["metin"] or "")[:300]}
            for s in kayit["sayfalar"]
        ]
    m["pdf_var"] = Path(m.get("kaynak", "")).exists()
    return m


@app.get("/api/belge/{doc_id}/pdf")
def belge_pdf(doc_id: str):
    manifest = MANIFEST.al()
    if doc_id not in manifest:
        raise HTTPException(404, "Belge bulunamadi")
    yol = Path(manifest[doc_id]["kaynak"]).resolve()
    kok = Path(AYAR.yollar.pdf_dizini).resolve()
    if kok not in yol.parents and yol.parent != kok:
        raise HTTPException(403, "Yol izinli dizin disinda")
    if not yol.exists():
        raise HTTPException(404, "PDF dosyasi diskte yok")
    return FileResponse(yol, media_type="application/pdf", filename=yol.name)


# ----------------------------------------------------------------------------
# Sohbet (SSE akisi)
# ----------------------------------------------------------------------------
def _sse(olay: str, veri) -> str:
    return "event: " + olay + "\ndata: " + json.dumps(veri, ensure_ascii=False) + "\n\n"


@app.post("/api/sor")
def sor(govde: dict = Body(...)):
    soru = (govde.get("soru") or "").strip()
    if not soru:
        raise HTTPException(400, "Soru bos olamaz")
    makine = govde.get("makine") or None
    tur = govde.get("tur") or None
    gecmis = govde.get("gecmis") or []
    gecmis = [{"role": m["role"], "content": m["content"]} for m in gecmis
              if m.get("role") in ("user", "assistant") and m.get("content")][-4:]

    def uret():
        basla = time.time()
        try:
            sohbet = MOTOR.al()
        except Exception as e:
            yield _sse("hata", {"mesaj": "Arama motoru yuklenemedi: " + str(e)})
            return
        try:
            akis, kaynaklar = sohbet.sor(soru, makine=makine, belge_turu=tur,
                                         akis=True, gecmis=gecmis)
            yield _sse("kaynaklar", kaynaklar)
            for parca in akis:
                yield _sse("parca", {"t": parca})
            yield _sse("bitti", {"sure": round(time.time() - basla, 1)})
        except Exception as e:
            traceback.print_exc()
            yield _sse("hata", {"mesaj": str(e)})

    return StreamingResponse(
        uret(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no",
                 "Connection": "keep-alive"},
    )


# ----------------------------------------------------------------------------
# Raporlar
# ----------------------------------------------------------------------------
@app.get("/api/raporlar")
def raporlar():
    dizin = Path(AYAR.yollar.rapor_dizini)
    cikti = []
    for d in sorted(dizin.glob("*.md")):
        st = d.stat()
        cikti.append({"ad": d.name, "boyut": st.st_size, "guncelleme": st.st_mtime})
    return cikti


@app.get("/api/raporlar/{ad}")
def rapor(ad: str):
    if "/" in ad or "\\" in ad or ".." in ad or not ad.endswith(".md"):
        raise HTTPException(400, "Gecersiz dosya adi")
    yol = Path(AYAR.yollar.rapor_dizini) / ad
    if not yol.exists():
        raise HTTPException(404, "Rapor bulunamadi")
    return {"ad": ad, "icerik": yol.read_text(encoding="utf-8")}


@app.post("/api/raporlar/uret")
def rapor_uret(govde: dict = Body(...)):
    kod = str(govde.get("makine") or "").strip()
    if not kod:
        raise HTTPException(400, "makine kodu gerekli")
    limit = govde.get("limit")
    ad = cfg.makine_adi(AYAR, kod)
    is_id = _is_baslat("Konu haritasi: " + ad, report_mod.rapor_uret, AYAR, kod,
                       limit=int(limit) if limit else None)
    return {"is_id": is_id}


@app.get("/api/isler")
def isler():
    with ISLER_KILIT:
        return sorted(ISLER.values(), key=lambda x: x["olusturma"], reverse=True)[:20]


# ----------------------------------------------------------------------------
# Statik web arayuzu (en sona monte edilir ki /api yollarini golgelemesin)
# ----------------------------------------------------------------------------
if WEB.exists():
    app.mount("/", StaticFiles(directory=str(WEB), html=True), name="web")


if __name__ == "__main__":
    import uvicorn

    print("MakineRAG -> http://127.0.0.1:8000")
    uvicorn.run(app, host="127.0.0.1", port=8000, log_level="info")
