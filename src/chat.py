"""Turkce cevap ureten RAG sohbet katmani."""
from __future__ import annotations

import llm as llm_mod
import retrieve as ret_mod

SISTEM = (
    "Sen bir endustriyel makine dokumantasyon uzmanisin. Kaynak belgeler Ingilizce veya "
    "Romence taranmis teknik dokumanlardir; metinde OCR kaynakli kucuk hatalar olabilir.\n"
    "KURALLAR:\n"
    "1. CEVABI HER ZAMAN TURKCE yaz.\n"
    "2. Sadece sana verilen BAGLAM bolumundeki bilgiyi kullan. Disaridan bilgi ekleme.\n"
    "3. Her iddianin sonuna kullandigin kaynagin numarasini koy: [1], [2] gibi.\n"
    "4. Baglamda cevap yoksa aynen soyle yaz: 'Belgelerde bu bilgi bulunmuyor.'\n"
    "5. Teknik terimi Turkce yaz, ilk gectiginde parantez icinde orijinalini ver: "
    "ornek 'yaglama araligi (lubrication interval)'.\n"
    "6. Sayilari, olcu birimlerini ve parca numaralarini belgedeki gibi aynen aktar, cevirme.\n"
    "7. Kisa ve maddeli yaz; gereksiz giris cumlesi kurma."
)

SORU_KALIBI = """BAGLAM:
{baglam}

SORU: {soru}

Yukaridaki baglami kullanarak soruyu Turkce yanitla ve kaynak numaralarini belirt."""


class Sohbet:
    def __init__(self, ayar):
        self.ayar = ayar
        self.arayici = ret_mod.Arayici(ayar)
        self.llm = llm_mod.olustur(ayar)
        self.gecmis = []

    def kaynak_satiri(self, vurus: list) -> list:
        satirlar = []
        for i, v in enumerate(vurus, start=1):
            m = v["meta"]
            sayfa = str(m.get("sayfa_bas", "?"))
            if m.get("sayfa_son") and m["sayfa_son"] != m["sayfa_bas"]:
                sayfa += "-" + str(m["sayfa_son"])
            alinti = (v.get("metin") or "").strip().replace("\n", " ")
            satirlar.append({
                "no": i,
                "baslik": m.get("baslik_tr") or m.get("dosya_adi", ""),
                "dosya": m.get("dosya_adi", ""),
                "kaynak": m.get("kaynak", ""),
                "makine": m.get("makine", ""),
                "belge_turu": m.get("belge_turu", ""),
                "doc_id": m.get("doc_id", ""),
                "sayfa": sayfa,
                "sayfa_no": int(m.get("sayfa_bas") or 1),
                "alinti": alinti[:420] + ("..." if len(alinti) > 420 else ""),
            })
        return satirlar

    def sor(self, soru: str, makine: str | None = None, belge_turu: str | None = None,
            akis: bool = False, gecmis: list | None = None):
        vurus = self.arayici.ara(soru, makine=makine, belge_turu=belge_turu)
        if not vurus:
            bos = "Belgelerde bu bilgi bulunmuyor."
            return (iter([bos]), []) if akis else (bos, [])

        baglam = ret_mod.baglam_metni(vurus)
        istem = SORU_KALIBI.format(baglam=baglam, soru=soru)

        # son 2 tur konusma hafizasi (web arayuzu gecmisi disaridan gonderir)
        onceki = self.gecmis if gecmis is None else gecmis
        mesajlar = onceki[-4:] + [{"role": "user", "content": istem}]
        kaynaklar = self.kaynak_satiri(vurus)

        if akis:
            return self.llm.akis(mesajlar, sistem=SISTEM), kaynaklar

        cevap = self.llm.sohbet(mesajlar, sistem=SISTEM)
        self.gecmis.append({"role": "user", "content": soru})
        self.gecmis.append({"role": "assistant", "content": cevap})
        return cevap, kaynaklar

    def gecmisi_temizle(self):
        self.gecmis = []
