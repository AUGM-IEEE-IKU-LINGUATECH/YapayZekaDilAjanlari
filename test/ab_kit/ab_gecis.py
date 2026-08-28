# -*- coding: utf-8 -*-
"""A/B testi gecis araci — yamali ve orijinal (yama oncesi) surumler arasinda gecis.

Amac: 0.864 (bu makine, yamali) ile 0.875 (eski makine, orijinal) farkinin
kaynagini ayirmak. Orijinal surum BU makinede de ~0.864 verirse fark ortamdan
demektir; ~0.875 verirse yamada aranir.

KULLANIM (once uvicorn'u KAPAT — Windows acik DB dosyasinin ustune yazdirmaz):
    python ab_kit\\ab_gecis.py --orijinal   # yama oncesi kod+DB'ye gec
    python ab_kit\\ab_gecis.py --yamali     # yamali surume geri don
    python ab_kit\\ab_gecis.py --durum      # su an hangisi aktif?

Ilk --orijinal cagrisinda mevcut (yamali) dosyalar ab_kit/yamali/ altina
yedeklenir; --yamali oradan geri yukler. Yedek bir kez alinir, ustune yazilmaz.
"""
import argparse, shutil, sqlite3, sys
from pathlib import Path

KIT = Path(__file__).resolve().parent
PROJE = KIT.parent
DOSYALAR = [
    "katilim_rag/analiz.py", "katilim_rag/config.py", "katilim_rag/sql_arac.py",
    "katilim_rag/getir.py", "katilim_rag/api.py", "veri/katilim.db",
]


def kopyala(kaynak_kok: Path, hedef_kok: Path):
    for r in DOSYALAR:
        k, h = kaynak_kok / r, hedef_kok / r
        h.parent.mkdir(parents=True, exist_ok=True)
        try:
            shutil.copy2(k, h)
        except PermissionError:
            sys.exit(f"HATA: {h} yazilamiyor — uvicorn/CLI hala acik olabilir. "
                     f"Sunucuyu kapatip (Ctrl+C) tekrar dene.")


def durum():
    analiz = (PROJE / "katilim_rag/analiz.py").read_text(encoding="utf-8")
    kod = "YAMALI" if "yon_bul" in analiz else "ORIJINAL"
    c = sqlite3.connect(PROJE / "veri/katilim.db")
    kolonlar = [r[1] for r in c.execute("PRAGMA table_info(urunler)")]
    db = "YAMALI (migrasyonlu)" if "dolayli_kar_payi" in kolonlar else "ORIJINAL"
    c.close()
    print(f"  kod : {kod}\n  DB  : {db}")
    if (kod == "YAMALI") != db.startswith("YAMALI"):
        print("  UYARI: kod ile DB farkli surumde — gecisi tekrar calistir.")


def main():
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--orijinal", action="store_true")
    g.add_argument("--yamali", action="store_true")
    g.add_argument("--durum", action="store_true")
    a = ap.parse_args()

    if a.durum:
        durum(); return

    if a.orijinal:
        yedek = KIT / "yamali"
        if not yedek.exists():                      # yedek BIR KEZ alinir
            print("mevcut (yamali) dosyalar ab_kit/yamali/ altina yedekleniyor…")
            kopyala(PROJE, yedek)
        else:
            print("yamali yedek zaten var, ustune yazilmiyor.")
        print("orijinal (yama oncesi) dosyalar yukleniyor…")
        kopyala(KIT / "orijinal", PROJE)
    else:
        yedek = KIT / "yamali"
        if not yedek.exists():
            sys.exit("HATA: ab_kit/yamali yedegi yok. Yamali surume donmek icin "
                     "LinguaTech_yama_2026-08-27.zip'i proje kokune yeniden ac.")
        print("yamali dosyalar geri yukleniyor…")
        kopyala(yedek, PROJE)

    print("tamam. SUNUCUYU YENIDEN BASLAT (modeller ve modul onbellegi tazelensin).")
    durum()


if __name__ == "__main__":
    main()
