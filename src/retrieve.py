"""Hibrit arama: yogun (bge-m3) + BM25, RRF ile birlestirme, makine filtresi."""
from __future__ import annotations

import re

import embed as embed_mod
import index_build as ix
import llm as llm_mod

CEVIRI_ISTEM = """Asagidaki Turkce teknik soruyu belge aramasinda kullanilmak uzere cevir.
Belgeler Ingilizce ve Romence teknik dokumanlardir.
Sadece su JSON'u dondur:
{{"en": "Ingilizce arama ifadesi", "ro": "Romence arama ifadesi", "terimler": ["3-8 teknik anahtar terim"]}}

SORU: {soru}"""


def _jeton(metin: str) -> list:
    return re.findall(r"[a-z0-9à-ɏ]+", metin.lower())


class Arayici:
    def __init__(self, ayar):
        self.ayar = ayar
        self.gommeci = embed_mod.olustur(ayar)
        self.koleksiyon = ix.koleksiyon_ac(ayar)
        self.bm25_deposu = ix.bm25_yukle(ayar)
        self.llm = llm_mod.olustur(ayar)
        self._ceviri_onbellek = {}

    # --- sorgu genisletme -------------------------------------------------
    def sorgu_genislet(self, soru: str) -> dict:
        if not self.ayar.arama.sorgu_cevirisi:
            return {"en": "", "ro": "", "terimler": []}
        if soru in self._ceviri_onbellek:
            return self._ceviri_onbellek[soru]
        sonuc = {"en": "", "ro": "", "terimler": []}
        try:
            ham = self.llm.uret(
                CEVIRI_ISTEM.format(soru=soru),
                sistem="Sen bir teknik ceviri yardimcisisin. Sadece JSON dondur.",
                json_modu=True,
            )
            v = llm_mod.json_ayikla(ham)
            sonuc["en"] = str(v.get("en", ""))
            sonuc["ro"] = str(v.get("ro", ""))
            if isinstance(v.get("terimler"), list):
                sonuc["terimler"] = [str(t) for t in v["terimler"]][:8]
        except Exception:
            pass
        self._ceviri_onbellek[soru] = sonuc
        return sonuc

    # --- alt aramalar -----------------------------------------------------
    def _yogun(self, sorgular: list, k: int, filtre: dict | None) -> list:
        vurus = []
        for s in sorgular:
            if not s.strip():
                continue
            v = self.gommeci.sorgu(s)
            c = self.koleksiyon.query(
                query_embeddings=[v],
                n_results=k,
                where=filtre or None,
                include=["documents", "metadatas", "distances"],
            )
            for i, pid in enumerate(c["ids"][0]):
                vurus.append({
                    "id": pid,
                    "metin": c["documents"][0][i],
                    "meta": c["metadatas"][0][i],
                    "skor": 1.0 - float(c["distances"][0][i]),
                })
        return vurus

    def _bm25(self, sorgular: list, k: int, makine: str | None) -> list:
        if not self.bm25_deposu:
            return []
        jetonlar = []
        for s in sorgular:
            jetonlar.extend(_jeton(s))
        if not jetonlar:
            return []
        skorlar = self.bm25_deposu["bm25"].get_scores(jetonlar)
        sirali = sorted(range(len(skorlar)), key=lambda i: skorlar[i], reverse=True)
        cikti, sayac = [], 0
        for i in sirali:
            m = self.bm25_deposu["metalar"][i]
            if makine and m.get("makine") != makine:
                continue
            if skorlar[i] <= 0:
                break
            cikti.append({
                "id": self.bm25_deposu["ids"][i],
                "metin": self.bm25_deposu["belgeler"][i],
                "meta": m,
                "skor": float(skorlar[i]),
            })
            sayac += 1
            if sayac >= k:
                break
        return cikti

    # --- birlestirme ------------------------------------------------------
    @staticmethod
    def _rrf(listeler: list, k: int = 60) -> list:
        havuz, puan = {}, {}
        for liste in listeler:
            for sira, v in enumerate(liste):
                havuz[v["id"]] = v
                puan[v["id"]] = puan.get(v["id"], 0.0) + 1.0 / (k + sira + 1)
        siralanmis = sorted(puan.items(), key=lambda x: x[1], reverse=True)
        cikti = []
        for pid, p in siralanmis:
            v = dict(havuz[pid])
            v["rrf"] = p
            cikti.append(v)
        return cikti

    def ara(self, soru: str, makine: str | None = None, belge_turu: str | None = None,
            final_k: int | None = None) -> list:
        a = self.ayar.arama
        final_k = final_k or int(a.final_k)

        filtre = {}
        if makine:
            filtre["makine"] = makine
        if belge_turu:
            filtre["belge_turu"] = belge_turu
        if len(filtre) > 1:
            filtre = {"$and": [{k: v} for k, v in filtre.items()]}
        elif not filtre:
            filtre = None

        genis = self.sorgu_genislet(soru)
        yogun_sorgular = [soru]
        if genis["en"]:
            yogun_sorgular.append(genis["en"])
        if genis["ro"]:
            yogun_sorgular.append(genis["ro"])

        bm_sorgular = [genis["en"] or soru]
        if genis["ro"]:
            bm_sorgular.append(genis["ro"])
        if genis["terimler"]:
            bm_sorgular.append(" ".join(genis["terimler"]))

        yogun = self._yogun(yogun_sorgular, int(a.dense_k), filtre)
        anahtar = self._bm25(bm_sorgular, int(a.bm25_k), makine)

        birlesik = self._rrf([yogun, anahtar])

        # ayni belgeden en fazla 3 parca -> kaynak cesitliligi
        gorulen, secilen = {}, []
        for v in birlesik:
            d = v["meta"]["doc_id"]
            if gorulen.get(d, 0) >= 3:
                continue
            gorulen[d] = gorulen.get(d, 0) + 1
            secilen.append(v)
            if len(secilen) >= final_k:
                break
        return secilen


def baglam_metni(vurus: list, sinir: int = 12000) -> str:
    """LLM'e verilecek numarali, kaynakli baglam blogu."""
    parcalar, toplam = [], 0
    for i, v in enumerate(vurus, start=1):
        m = v["meta"]
        baslik = m.get("baslik_tr") or m.get("dosya_adi", "")
        sayfa = str(m.get("sayfa_bas", "?"))
        if m.get("sayfa_son") and m.get("sayfa_son") != m.get("sayfa_bas"):
            sayfa += "-" + str(m["sayfa_son"])
        bas = "[" + str(i) + "] " + baslik + " | " + m.get("dosya_adi", "") + " | s." + sayfa
        govde = bas + "\n" + v["metin"]
        if toplam + len(govde) > sinir:
            break
        parcalar.append(govde)
        toplam += len(govde)
    return "\n\n---\n\n".join(parcalar)
