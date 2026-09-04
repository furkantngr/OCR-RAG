"""MakineRAG komut satiri.

Kullanim:
    python src/cli.py durum
    python src/cli.py ocr
    python src/cli.py meta
    python src/cli.py index
    python src/cli.py listele --makine A
    python src/cli.py rapor --makine A
    python src/cli.py sor "A makinesinde yag degisim araligi nedir?" --makine A
    python src/cli.py sohbet
    python src/cli.py tumu
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Windows konsolu varsayilan olarak cp125x kullanir; Turkce karakterler patlar.
for _akis in (sys.stdout, sys.stderr):
    try:
        _akis.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

sys.path.insert(0, str(Path(__file__).resolve().parent))

import config as cfg  # noqa: E402


def _ayar(args):
    return cfg.yukle(args.config)


def komut_durum(args):
    import ingest
    import llm as llm_mod

    ayar = _ayar(args)
    d = ingest.durum(ayar)
    print("PDF dosyasi      : " + str(d["pdf"]))
    print("OCR cikarilmis   : " + str(d["ocr"]))
    print("Manifest kaydi   : " + str(d["manifest"]))
    try:
        import index_build as ix
        print("Indeks parcasi   : " + str(ix.koleksiyon_ac(ayar).count()))
    except Exception as e:
        print("Indeks parcasi   : - (" + str(e)[:60] + ")")
    print("Ollama           : " + ("calisiyor" if llm_mod.olustur(ayar).canli_mi() else "ULASILAMIYOR"))
    if d["manifest"]:
        import metadata as meta_mod
        from collections import Counter
        dag = Counter(m["makine"] for m in meta_mod.manifest_oku(ayar).values())
        print("Makine dagilimi  : " + str(dict(dag)))


def komut_ocr(args):
    import ingest
    ingest.calistir(_ayar(args), yeniden=args.yeniden, limit=args.limit)


def komut_meta(args):
    import metadata as meta_mod
    meta_mod.cikart(_ayar(args), yeniden=args.yeniden, llm_kullan=not args.kural_sadece)


def komut_index(args):
    import index_build as ix
    ix.kur(_ayar(args), yeniden=args.yeniden)


def komut_listele(args):
    import report
    ayar = _ayar(args)
    kayitlar = report.belgeler(ayar, makine=args.makine, belge_turu=args.tur)
    print(str(len(kayitlar)) + " belge bulundu.\n")
    for i, m in enumerate(kayitlar, start=1):
        print(str(i).rjust(4) + ". [" + m.get("makine", "?") + "] "
              + (m.get("baslik_tr") or "")[:70])
        print("      " + m["dosya_adi"] + "  |  " + m.get("belge_turu", "")
              + "  |  " + str(m.get("sayfa_sayisi", "")) + " sayfa")


def komut_rapor(args):
    import report
    ayar = _ayar(args)
    kodlar = [args.makine] if args.makine else [m["kod"] for m in ayar.makineler]
    for kod in kodlar:
        report.rapor_uret(ayar, kod, limit=args.limit)


def komut_sor(args):
    import chat
    ayar = _ayar(args)
    s = chat.Sohbet(ayar)
    cevap, kaynaklar = s.sor(args.soru, makine=args.makine, belge_turu=args.tur)
    print("\n" + cevap + "\n")
    print("KAYNAKLAR")
    for k in kaynaklar:
        print("  [" + str(k["no"]) + "] " + k["baslik"] + " - " + k["dosya"] + " s." + k["sayfa"])


def komut_sohbet(args):
    import chat
    ayar = _ayar(args)
    s = chat.Sohbet(ayar)
    makine = args.makine
    print("MakineRAG sohbet. Cikis: /q  |  Makine filtresi: /m A  |  Filtreyi kaldir: /m -")
    while True:
        try:
            soru = input("\n> ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if not soru:
            continue
        if soru in ("/q", "/quit", "/cikis"):
            break
        if soru.startswith("/m"):
            deger = soru[2:].strip()
            makine = None if deger in ("-", "") else deger
            print("Makine filtresi: " + str(makine))
            continue
        if soru == "/temizle":
            s.gecmisi_temizle()
            print("Gecmis temizlendi.")
            continue
        cevap, kaynaklar = s.sor(soru, makine=makine)
        print("\n" + cevap + "\n")
        for k in kaynaklar:
            print("  [" + str(k["no"]) + "] " + k["dosya"] + " s." + k["sayfa"])


def komut_tumu(args):
    import ingest
    import metadata as meta_mod
    import index_build as ix
    ayar = _ayar(args)
    print("\n=== 1/3 OCR ===")
    ingest.calistir(ayar, limit=args.limit)
    print("\n=== 2/3 Meta ===")
    meta_mod.cikart(ayar)
    print("\n=== 3/3 Indeks ===")
    ix.kur(ayar)
    print("\nHazir. 'python src/cli.py sohbet' ile sorabilirsiniz.")


def main():
    p = argparse.ArgumentParser(prog="makinerag", description="Yerel PDF bilgi asistani")
    p.add_argument("--config", default=None, help="config.yaml yolu")
    alt = p.add_subparsers(dest="komut", required=True)

    a = alt.add_parser("durum", help="Boru hattinin durumunu goster")
    a.set_defaults(fn=komut_durum)

    a = alt.add_parser("ocr", help="PDF'leri metne cevir (OCR)")
    a.add_argument("--yeniden", action="store_true")
    a.add_argument("--limit", type=int, default=None)
    a.set_defaults(fn=komut_ocr)

    a = alt.add_parser("meta", help="Makine/tur/Turkce baslik meta verisi cikar")
    a.add_argument("--yeniden", action="store_true")
    a.add_argument("--kural-sadece", action="store_true", help="LLM kullanma")
    a.set_defaults(fn=komut_meta)

    a = alt.add_parser("index", help="Vektor + BM25 indeksini kur")
    a.add_argument("--yeniden", action="store_true")
    a.set_defaults(fn=komut_index)

    a = alt.add_parser("listele", help="Belgeleri filtrele ve listele")
    a.add_argument("--makine", default=None)
    a.add_argument("--tur", default=None)
    a.set_defaults(fn=komut_listele)

    a = alt.add_parser("rapor", help="Makine bazli Turkce konu/baslik haritasi uret")
    a.add_argument("--makine", default=None)
    a.add_argument("--limit", type=int, default=None)
    a.set_defaults(fn=komut_rapor)

    a = alt.add_parser("sor", help="Tek soru sor")
    a.add_argument("soru")
    a.add_argument("--makine", default=None)
    a.add_argument("--tur", default=None)
    a.set_defaults(fn=komut_sor)

    a = alt.add_parser("sohbet", help="Etkilesimli sohbet")
    a.add_argument("--makine", default=None)
    a.set_defaults(fn=komut_sohbet)

    a = alt.add_parser("tumu", help="OCR + meta + indeks")
    a.add_argument("--limit", type=int, default=None)
    a.set_defaults(fn=komut_tumu)

    args = p.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
