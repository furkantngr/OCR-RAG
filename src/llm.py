"""Yerel Ollama istemcisi. Turkce cikti icin sistem yonergeleri burada."""
from __future__ import annotations

import json
import re

import requests

SISTEM_TR = (
    "Sen teknik dokuman uzmani bir asistansin. Kaynak belgeler Ingilizce veya Romence olabilir. "
    "CEVABI HER ZAMAN TURKCE yaz. Teknik terimlerin Turkcesini kullan, gerekiyorsa parantez icinde "
    "orijinalini ver: ornek 'yataklama (bearing)'. Sadece sana verilen baglamdaki bilgiyi kullan. "
    "Baglamda olmayan bir sey sorulursa 'Belgelerde bu bilgi bulunmuyor.' de, tahmin uretme."
)


class Ollama:
    def __init__(self, model: str, taban_url: str = "http://localhost:11434",
                 sicaklik: float = 0.1, baglam: int = 8192, zaman_asimi: int = 600):
        self.model = model
        self.taban = taban_url.rstrip("/")
        self.sicaklik = sicaklik
        self.baglam = baglam
        self.zaman_asimi = zaman_asimi

    def canli_mi(self) -> bool:
        try:
            requests.get(f"{self.taban}/api/tags", timeout=5).raise_for_status()
            return True
        except Exception:
            return False

    def uret(self, istem: str, sistem: str = SISTEM_TR, json_modu: bool = False,
             sicaklik: float | None = None) -> str:
        govde = {
            "model": self.model,
            "prompt": istem,
            "system": sistem,
            "stream": False,
            "options": {
                "temperature": self.sicaklik if sicaklik is None else sicaklik,
                "num_ctx": self.baglam,
            },
        }
        if json_modu:
            govde["format"] = "json"
        y = requests.post(f"{self.taban}/api/generate", json=govde, timeout=self.zaman_asimi)
        y.raise_for_status()
        return y.json().get("response", "").strip()

    def sohbet(self, mesajlar: list[dict], sistem: str = SISTEM_TR) -> str:
        tum = [{"role": "system", "content": sistem}] + mesajlar
        govde = {
            "model": self.model, "messages": tum, "stream": False,
            "options": {"temperature": self.sicaklik, "num_ctx": self.baglam},
        }
        y = requests.post(f"{self.taban}/api/chat", json=govde, timeout=self.zaman_asimi)
        y.raise_for_status()
        return y.json().get("message", {}).get("content", "").strip()

    def akis(self, mesajlar: list[dict], sistem: str = SISTEM_TR):
        """Streamlit icin parca parca cikti."""
        tum = [{"role": "system", "content": sistem}] + mesajlar
        govde = {
            "model": self.model, "messages": tum, "stream": True,
            "options": {"temperature": self.sicaklik, "num_ctx": self.baglam},
        }
        with requests.post(f"{self.taban}/api/chat", json=govde,
                           stream=True, timeout=self.zaman_asimi) as y:
            y.raise_for_status()
            for satir in y.iter_lines():
                if not satir:
                    continue
                try:
                    veri = json.loads(satir.decode("utf-8"))
                except json.JSONDecodeError:
                    continue
                parca = veri.get("message", {}).get("content", "")
                if parca:
                    yield parca
                if veri.get("done"):
                    break


def json_ayikla(metin: str) -> dict:
    """LLM ciktisindan ilk JSON nesnesini guvenle cikarir."""
    metin = metin.strip()
    metin = re.sub(r"^```(?:json)?|```$", "", metin, flags=re.MULTILINE).strip()
    try:
        return json.loads(metin)
    except json.JSONDecodeError:
        pass
    basla = metin.find("{")
    if basla == -1:
        return {}
    derinlik = 0
    for i in range(basla, len(metin)):
        if metin[i] == "{":
            derinlik += 1
        elif metin[i] == "}":
            derinlik -= 1
            if derinlik == 0:
                try:
                    return json.loads(metin[basla:i + 1])
                except json.JSONDecodeError:
                    return {}
    return {}


def olustur(ayar) -> Ollama:
    return Ollama(
        model=ayar.llm.model,
        taban_url=ayar.llm.taban_url,
        sicaklik=float(ayar.llm.sicaklik),
        baglam=int(ayar.llm.baglam),
    )
