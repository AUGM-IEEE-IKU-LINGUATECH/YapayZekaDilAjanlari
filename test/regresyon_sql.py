# -*- coding: utf-8 -*-
"""SQL yolu + yonlendirme regresyon testi — LLM ve model GEREKTIRMEZ.

138 sorunun tamaminda deterministik katmanlari calistirir:
  - sohbet kisa devresi
  - yonlendirme karari (sql / rag) ve SQL sablonu tipi
  - siralama sorularinda nihai sablon cevabi (kullaniciya giden metin)
  - sayma / karsilastirma sorularinda LLM'e giden baglam metni

Cikti JSON'a yazilir; --karsilastir ile iki anlik goruntu diff'lenir.
Amac: kod/veri degisikliklerinin skoru dusurmedigini kanitlamak.

    python regresyon_sql.py --cikti once.json
    ... degisiklikler ...
    python regresyon_sql.py --cikti sonra.json --karsilastir once.json
"""
import argparse, json, sys, unicodedata
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from katilim_rag import sql_arac, boru  # noqa: E402


def fold(s):
    s = str(s).replace("İ", "i").replace("I", "ı").lower()
    for a, b in [("ı", "i"), ("ş", "s"), ("ğ", "g"), ("ü", "u"), ("ö", "o"), ("ç", "c"), ("â", "a")]:
        s = s.replace(a, b)
    return unicodedata.normalize("NFKC", s)


def kos(sorular):
    out = {}
    for s in sorular:
        q = s["soru"]
        kayit = {"id": s["id"], "soru": q}
        kisa = boru._sohbet_mi(q)
        if kisa:
            kayit.update({"yol": "sohbet", "metin": kisa})
            out[s["id"]] = kayit
            continue
        bulgu = sql_arac.calistir(q)
        if bulgu is None:
            kayit["yol"] = "rag"
        else:
            kayit["yol"] = "sql"
            kayit["tip"] = bulgu["tip"]
            if bulgu["tip"] in ("siralama", "esik_tekil", "esik_min", "esik_liste", "esik_bos", "tarih_liste", "tarih_bos", "tarih_tekil"):
                # kullaniciya giden nihai metin (boru.cevapla sablonla yazar)
                kayit["metin"] = sql_arac.sablonla_yaz(bulgu)
            else:
                # LLM'e giden baglam — sayilar/bankalar buradan gelir
                kayit["metin"] = sql_arac.bulguyu_metne_cevir(bulgu)
        out[s["id"]] = kayit
    return out


def degerlendir(sonuc, sorular):
    """Deterministik on-metrikler: yol tutarliligi + SQL metinlerinde
    beklenen deger/banka varligi + yasak kelime yoklugu."""
    rapor = {"yol_uyum": 0, "yol_toplam": 0, "sql_deger_ok": [], "sql_deger_fail": [],
             "sql_banka_ok": [], "sql_banka_fail": [], "yasak_ihlal": []}
    for s in sorular:
        r = sonuc[s["id"]]
        bek = s.get("beklenen_yol", "any")
        if bek in ("sql", "rag"):
            rapor["yol_toplam"] += 1
            if r["yol"] == bek:
                rapor["yol_uyum"] += 1
        m = fold(r.get("metin", ""))
        if r["yol"] == "sql" and m:
            if "beklenen_deger" in s:
                # sayi karsilastirmasi: "120 ay" -> "120", "1.99" -> "1.99"
                ham = str(s["beklenen_deger"])
                sayi = ham.replace(" ay", "").replace(".000", "000").strip()
                (rapor["sql_deger_ok"] if (sayi in m or fold(ham) in m)
                 else rapor["sql_deger_fail"]).append(s["id"])
            for b in s.get("beklenen_banka") or []:
                (rapor["sql_banka_ok"] if fold(b) in m
                 else rapor["sql_banka_fail"]).append(f"{s['id']}:{b}")
            for y in s.get("yasak_kelimeler") or []:
                if fold(y) in m:
                    rapor["yasak_ihlal"].append(f"{s['id']}:{y}")
    return rapor


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sorular", default=str(Path(__file__).parent / "sorular_birlesik.json"))
    ap.add_argument("--cikti", required=True)
    ap.add_argument("--karsilastir", help="onceki anlik goruntu (JSON)")
    a = ap.parse_args()

    sorular = json.load(open(a.sorular, encoding="utf-8"))["sorular"]
    sonuc = kos(sorular)
    rapor = degerlendir(sonuc, sorular)
    json.dump({"sonuc": sonuc, "rapor": rapor}, open(a.cikti, "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)

    print(f"yol uyumu           : {rapor['yol_uyum']}/{rapor['yol_toplam']}")
    print(f"SQL deger isabeti   : {len(rapor['sql_deger_ok'])} ok, "
          f"{len(rapor['sql_deger_fail'])} fail {rapor['sql_deger_fail']}")
    print(f"SQL banka isabeti   : {len(rapor['sql_banka_ok'])} ok, "
          f"{len(rapor['sql_banka_fail'])} fail {rapor['sql_banka_fail']}")
    print(f"yasak ihlali        : {rapor['yasak_ihlal']}")

    if a.karsilastir:
        once = json.load(open(a.karsilastir, encoding="utf-8"))
        o_sonuc, o_rapor = once["sonuc"], once["rapor"]
        print("\n" + "=" * 60 + "\nKARSILASTIRMA (once -> sonra)\n" + "=" * 60)
        gerileme = 0
        for sid, r in sonuc.items():
            o = o_sonuc.get(sid, {})
            if o.get("yol") != r["yol"]:
                print(f"  YOL DEGISTI  [{sid}] {o.get('yol')} -> {r['yol']}  | {r['soru'][:55]}")
            elif o.get("metin", "") != r.get("metin", ""):
                print(f"  metin degisti [{sid}] {r['soru'][:55]}")
        for k in ("sql_deger_fail", "sql_banka_fail", "yasak_ihlal"):
            eski, yeni = set(o_rapor.get(k, [])), set(rapor.get(k, []))
            for x in yeni - eski:
                print(f"  !! GERILEME {k}: {x}")
                gerileme += 1
            for x in eski - yeni:
                print(f"  ++ IYILESME {k}: {x}")
        if o_rapor.get("yol_uyum", 0) > rapor["yol_uyum"]:
            print(f"  !! GERILEME yol_uyum: {o_rapor['yol_uyum']} -> {rapor['yol_uyum']}")
            gerileme += 1
        print(f"\nSONUC: {'TEMIZ — gerileme yok' if gerileme == 0 else f'{gerileme} GERILEME VAR'}")
        sys.exit(1 if gerileme else 0)


if __name__ == "__main__":
    main()
