# -*- coding: utf-8 -*-
"""Parametre taramasi: farkli esik/top_k degerlerini ayni sette olcup karsilastirir.

    py tara.py --http http://localhost:8000/sor

DIKKAT: Sunucu parametreleri baslangicta okur. Bu script her kombinasyon icin
sunucuyu YENIDEN BASLATMANI ister — otomatik degistiremez. Onun yerine
--yerlesik ile calistirmak daha pratiktir (ortam degiskenini kendi ayarlar):

    py tara.py --yerlesik
"""
import argparse, itertools, json, os, statistics, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import degerlendir as D   # noqa: E402

KOMBINASYONLAR = {
    "MIN_VEKTOR_SKOR": ["0.50", "0.55", "0.60"],
    "GORELI_BANT": ["0.10", "0.15", "0.25"],
    "TOP_K_CEVAP": ["4", "6", "8"],
}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--yerlesik", action="store_true")
    ap.add_argument("--http")
    ap.add_argument("--sorular", default="sorular_birlesik.json")
    ap.add_argument("--hizli", action="store_true", help="sadece veri_bagimsiz sorular")
    a = ap.parse_args()
    if not (a.yerlesik or a.http):
        sys.exit("--yerlesik veya --http gerekli")

    sorular = json.loads(Path(a.sorular).read_text(encoding="utf-8"))["sorular"]
    if a.hizli:
        sorular = [s for s in sorular if s.get("veri_bagimsiz")]

    anahtarlar = list(KOMBINASYONLAR)
    sonuclar = []
    for degerler in itertools.product(*KOMBINASYONLAR.values()):
        ayar = dict(zip(anahtarlar, degerler))
        etiket = "_".join(f"{k.split('_')[-1]}{v}" for k, v in ayar.items())
        print(f"\n{'='*60}\n{ayar}\n{'='*60}")

        if a.yerlesik:
            os.environ.update(ayar)
            # modulleri yeniden yukle ki yeni ayarlar okunsun
            for m in [m for m in list(sys.modules) if m.startswith("katilim_rag")]:
                del sys.modules[m]
            ad = D.adaptor_yerlesik()
        else:
            print("  sunucuyu su ayarlarla yeniden baslat, sonra Enter'a bas:")
            print("  " + " ".join(f"set {k}={v} &&" for k, v in ayar.items()) +
                  " py -m uvicorn katilim_rag.api:app --port 8000")
            input()
            ad = D.adaptor_http(a.http)

        r = D.calistir(ad, sorular)
        o = D.rapor(r, Path("sonuclar/tarama"), etiket)
        sonuclar.append({**ayar, "puan": o["genel_puan"],
                         "bayrakli": o["bayrakli_soru"], "sure": o["sure_ortalama"]})

    sonuclar.sort(key=lambda x: x["puan"], reverse=True)
    Path("sonuclar/tarama").mkdir(parents=True, exist_ok=True)
    Path("sonuclar/tarama/ozet.json").write_text(
        json.dumps(sonuclar, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n{'='*60}\nSIRALAMA\n{'='*60}")
    for s in sonuclar:
        print(f"  {s['puan']:.3f}  bayrak={s['bayrakli']:>3}  {s['sure']}sn  "
              f"taban={s['MIN_VEKTOR_SKOR']} bant={s['GORELI_BANT']} k={s['TOP_K_CEVAP']}")


if __name__ == "__main__":
    main()
