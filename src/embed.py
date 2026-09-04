"""Cok dilli gomme. TR sorgu -> EN/RO belge eslesmesi icin cok dilli model sart.

Model onekleri: bazi gomme modelleri sorgu ve belgeyi farkli oneklerle bekler.
Onek verilmezse kalite sessizce duser (hata da vermez), bu yuzden model adina gore
otomatik secilir. config.yaml'dan elle de verilebilir:

    gomme:
      onek_sorgu: "query: "
      onek_belge: "passage: "
"""
from __future__ import annotations

import os
from pathlib import Path

import requests


def _cevrilmis_snapshot(model_adi: str) -> Path | None:
    """Safetensors'a cevrilmis yerel snapshot yolunu doner (yoksa None).

    Bazi depolar (BAAI/bge-m3) Hub'da yalnizca pytorch_model.bin ile yayinlanir.
    scripts/safetensors_cevir.py agirligi yerelde safetensors'a cevirir, ancak
    transformers repo kimligiyle cagrildiginda dosya adini Hub'dan cozer ve
    yereldeki safetensors'i gormez. Bu durumda dogrudan snapshot dizinini vermek
    gerekir.
    """
    if "/" not in model_adi or Path(model_adi).exists():
        return None
    hf_home = os.environ.get("HF_HOME")
    kok = Path(hf_home) if hf_home else Path.home() / ".cache" / "huggingface"
    temel = kok / "hub" / ("models--" + model_adi.replace("/", "--")) / "snapshots"
    if not temel.is_dir():
        return None
    for snap in temel.iterdir():
        st = snap / "model.safetensors"
        if (snap / "pytorch_model.bin").exists() and st.exists() and st.stat().st_size > 0 \
                and (snap / "config.json").exists() and (snap / "modules.json").exists():
            return snap
    return None

# Model ailesine gore (sorgu oneki, belge oneki).
# Anahtar, model adinin kucuk harfli halinde aranan parcadir; sira onemlidir.
ONEK_PROFILLERI = [
    # E5 ailesi: onek olmadan belirgin kalite kaybi olur
    ("multilingual-e5", ("query: ", "passage: ")),
    ("/e5-", ("query: ", "passage: ")),
    # Qwen3-Embedding: sorguya talimat oneki, belgeye onek yok
    ("qwen3-embedding", (
        "Instruct: Verilen teknik soruya cevap iceren belge bolumlerini bul\nQuery: ", "")),
    # GTE / mGTE
    ("gte-multilingual", ("", "")),
    # BGE-M3 ve bge-multilingual: onek gerekmez
    ("bge-m3", ("", "")),
    ("arctic-embed", ("query: ", "")),
    # Nomic
    ("nomic-embed", ("search_query: ", "search_document: ")),
]


def onek_bul(model_adi: str) -> tuple:
    ad = model_adi.lower()
    for parca, onekler in ONEK_PROFILLERI:
        if parca in ad:
            return onekler
    return ("", "")


class STGommeci:
    """sentence-transformers tabanli (onerilen). Ilk calistirmada model indirilir."""

    def __init__(self, model_adi: str = "BAAI/bge-m3", cihaz: str = "cuda", batch: int = 8,
                 onek_sorgu: str | None = None, onek_belge: str | None = None,
                 yari_hassasiyet: bool = False, azami_uzunluk: int | None = 1024):
        from sentence_transformers import SentenceTransformer
        import torch

        if cihaz == "cuda" and not torch.cuda.is_available():
            print("[!] CUDA yok, CPU'ya dusuluyor.")
            cihaz = "cpu"

        kwargs = {}
        if yari_hassasiyet and cihaz == "cuda":
            # 8 GB VRAM'de LLM ile yan yana yasayabilmek icin
            kwargs["model_kwargs"] = {"torch_dtype": torch.float16}

        try:
            self.model = SentenceTransformer(model_adi, device=cihaz, **kwargs)
        except ValueError as e:
            if "torch.load" not in str(e) and "at least v2.6" not in str(e):
                raise
            snap = _cevrilmis_snapshot(model_adi)
            if snap is None:
                raise RuntimeError(
                    model_adi + " modeli Hub'da sadece pytorch_model.bin ile yayinlanmis ve "
                    "transformers bunu torch < 2.6 ile yuklemiyor.\n"
                    "Cozum (tek seferlik, ~30 sn):\n"
                    "    python scripts/safetensors_cevir.py " + model_adi
                ) from e
            print("[i] " + model_adi + " yerel safetensors surumunden yukleniyor.")
            self.model = SentenceTransformer(str(snap), device=cihaz, **kwargs)

        self.model_adi = model_adi
        self.batch = batch

        # Modellerin varsayilan azami uzunlugu cok buyuk olabilir (Qwen3-Embedding
        # 32768, bge-m3 8192). Parcalarimiz ~400 token; siniri dusurmek kaliteyi
        # etkilemez ama kodlamayi belirgin hizlandirir ve VRAM'i dusurur.
        if azami_uzunluk:
            mevcut = getattr(self.model, "max_seq_length", None)
            if mevcut and mevcut > azami_uzunluk:
                self.model.max_seq_length = azami_uzunluk
                print("[i] azami dizi uzunlugu " + str(mevcut) + " -> " + str(azami_uzunluk))

        self.boyut = self.model.get_sentence_embedding_dimension()
        self.cihaz = cihaz

        varsayilan = onek_bul(model_adi)
        self.onek_sorgu = varsayilan[0] if onek_sorgu is None else onek_sorgu
        self.onek_belge = varsayilan[1] if onek_belge is None else onek_belge
        if self.onek_sorgu or self.onek_belge:
            print("[i] " + model_adi + " onekleri -> sorgu: " + repr(self.onek_sorgu)
                  + " belge: " + repr(self.onek_belge))

    def belgeler(self, metinler: list, ilerleme: bool = True) -> list:
        if self.onek_belge:
            metinler = [self.onek_belge + m for m in metinler]
        v = self.model.encode(
            metinler,
            batch_size=self.batch,
            normalize_embeddings=True,
            show_progress_bar=ilerleme,
            convert_to_numpy=True,
        )
        return v.tolist()

    def sorgu(self, metin: str) -> list:
        v = self.model.encode([self.onek_sorgu + metin], normalize_embeddings=True,
                              convert_to_numpy=True)
        return v[0].tolist()

    def bosalt(self) -> None:
        """GPU bellegini birak (model karsilastirmasi icin)."""
        import gc

        import torch

        del self.model
        self.model = None
        gc.collect()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()


class OllamaGommeci:
    """Yedek secenek: ollama uzerinden gomme (nomic-embed-text).

    Not: nomic-embed-text tek dillidir; Turkce sorgu ile Ingilizce/Romence belge
    eslesmesinde zayif kalir. Sadece hizli deneme icin kullanin.
    """

    def __init__(self, model_adi: str = "nomic-embed-text",
                 taban_url: str = "http://localhost:11434", batch: int = 8):
        self.model = model_adi
        self.model_adi = model_adi
        self.taban = taban_url.rstrip("/")
        self.batch = batch
        self.onek_sorgu, self.onek_belge = onek_bul(model_adi)
        self.cihaz = "ollama"
        self.boyut = len(self.sorgu("test"))

    def _tek(self, metin: str) -> list:
        y = requests.post(
            self.taban + "/api/embeddings",
            json={"model": self.model, "prompt": metin},
            timeout=120,
        )
        y.raise_for_status()
        return y.json()["embedding"]

    def belgeler(self, metinler: list, ilerleme: bool = True) -> list:
        from tqdm import tqdm

        gezgin = tqdm(metinler, desc="Gomme", unit="parca") if ilerleme else metinler
        return [self._tek(self.onek_belge + m) for m in gezgin]

    def sorgu(self, metin: str) -> list:
        return self._tek(self.onek_sorgu + metin)

    def bosalt(self) -> None:
        pass


def olustur(ayar, model_adi: str | None = None):
    """Yapilandirmadan gommeci uretir. model_adi verilirse config'i ezer."""
    saglayici = str(ayar.gomme.saglayici).lower()
    g = ayar.gomme

    if saglayici.startswith("ollama"):
        return OllamaGommeci(
            model_adi=model_adi or g.ollama_model,
            taban_url=ayar.llm.taban_url,
            batch=int(g.batch),
        )
    return STGommeci(
        model_adi=model_adi or g.model,
        cihaz=g.cihaz,
        batch=int(g.batch),
        onek_sorgu=g.get("onek_sorgu"),
        onek_belge=g.get("onek_belge"),
        yari_hassasiyet=bool(g.get("yari_hassasiyet", False)),
        azami_uzunluk=int(g.get("azami_uzunluk", 1024)),
    )
