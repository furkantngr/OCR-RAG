"""HuggingFace onbellegindeki pytorch_model.bin dosyasini safetensors'a cevirir.

Neden gerekli:
  Bazi modeller (ornegin BAAI/bge-m3) Hub'da yalnizca pytorch_model.bin ile yayinlanir.
  transformers 5.x, torch surumu 2.6'nin altindaysa guvenlik gerekcesiyle .bin yuklemeyi
  reddeder ve su hatayi verir:

      ValueError: Due to a serious vulnerability issue in `torch.load` ... upgrade torch
      to at least v2.6

  Iki cozum var: 2,5 GB'lik torch yukseltmesi, ya da agirligi bir kez safetensors'a
  cevirmek. Bu betik ikincisini yapar -- daha hizli, daha guvenli ve CUDA surumunu
  riske atmaz. Cevrildikten sonra model normal sekilde yuklenir.

Kullanim:
    python scripts/safetensors_cevir.py BAAI/bge-m3
    python scripts/safetensors_cevir.py            # onbellekteki tum .bin modelleri
"""
from __future__ import annotations

import sys
from pathlib import Path

KOK = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(KOK / "src"))

for _akis in (sys.stdout, sys.stderr):
    try:
        _akis.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass


def onbellek_kokleri() -> list:
    import os

    kok = os.environ.get("HF_HOME")
    if kok:
        return [Path(kok) / "hub"]
    return [Path.home() / ".cache" / "huggingface" / "hub"]


def snapshot_bul(repo: str) -> list:
    """Verilen repo icin .bin iceren ama safetensors icermeyen snapshot dizinleri."""
    klasor = "models--" + repo.replace("/", "--")
    bulunan = []
    for kok in onbellek_kokleri():
        temel = kok / klasor / "snapshots"
        if not temel.exists():
            continue
        for snap in temel.iterdir():
            if not snap.is_dir():
                continue
            bin_yolu = snap / "pytorch_model.bin"
            st_yolu = snap / "model.safetensors"
            if bin_yolu.exists() and not (st_yolu.exists() and st_yolu.stat().st_size > 0):
                bulunan.append(snap)
    return bulunan


def tum_bin_modeller() -> list:
    cikti = []
    for kok in onbellek_kokleri():
        if not kok.exists():
            continue
        for klasor in kok.glob("models--*"):
            repo = klasor.name.replace("models--", "").replace("--", "/", 1)
            if snapshot_bul(repo):
                cikti.append(repo)
    return sorted(set(cikti))


def cevir(snap: Path) -> bool:
    import torch
    from safetensors.torch import save_file

    bin_yolu = snap / "pytorch_model.bin"
    hedef = snap / "model.safetensors"
    print("  okunuyor: " + str(bin_yolu))

    durum = torch.load(bin_yolu, map_location="cpu", weights_only=True)
    if not isinstance(durum, dict):
        print("  [!] beklenmedik dosya icerigi, atlaniyor")
        return False

    # safetensors paylasilan bellek kullanan tensorleri kabul etmez (bagli gomme
    # katmanlari gibi); bunlari kopyalayarak ayirmak gerekir.
    gorulen = {}
    temiz = {}
    paylasilan = 0
    for ad, t in durum.items():
        if not isinstance(t, torch.Tensor):
            continue
        anahtar = (t.data_ptr(), t.shape, t.stride())
        if t.data_ptr() != 0 and anahtar in gorulen:
            t = t.clone()
            paylasilan += 1
        else:
            gorulen[anahtar] = ad
        temiz[ad] = t.contiguous()

    if paylasilan:
        print("  " + str(paylasilan) + " paylasilan tensor kopyalandi")

    print("  yaziliyor: " + str(hedef))
    save_file(temiz, str(hedef), metadata={"format": "pt"})
    mb = hedef.stat().st_size / (1024 ** 2)
    print("  [OK] " + ("%.0f" % mb) + " MB")
    return True


def main():
    repolar = sys.argv[1:]
    if not repolar:
        repolar = tum_bin_modeller()
        if not repolar:
            print("Cevrilecek model yok (safetensors zaten mevcut).")
            return
        print("Onbellekte .bin ile duran modeller: " + ", ".join(repolar) + "\n")

    for repo in repolar:
        print("=== " + repo + " ===")
        snaplar = snapshot_bul(repo)
        if not snaplar:
            print("  safetensors zaten var ya da model onbellekte degil, atlandi")
            continue
        for snap in snaplar:
            try:
                cevir(snap)
            except Exception as e:
                print("  [HATA] " + type(e).__name__ + ": " + str(e)[:200])


if __name__ == "__main__":
    main()
