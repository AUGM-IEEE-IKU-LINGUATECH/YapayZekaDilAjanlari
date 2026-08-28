# -*- coding: utf-8 -*-
"""
RAG degerlendirme kosucusu — sisteme bagimsiz.

Herhangi bir RAG sistemine 3 yoldan baglanir:

  1) HTTP     : python degerlendir.py --http http://localhost:8000/sor
  2) Python   : python degerlendir.py --modul benim_rag:cevapla
  3) Yerlesik : python degerlendir.py --yerlesik        (bu repodaki katilim_rag)

Adaptor sozlesmesi — fonksiyon bir soru alir, su sozlugu doner:
    {"cevap": str, "kaynaklar": [{"url": str, ...}], "yol": "sql"|"rag"}
"cevap" disindaki alanlar opsiyoneldir; yoksa ilgili metrik atlanir.

LLM hakem KULLANMAZ — tum metrikler deterministik, offline calisir.
"""
import argparse, importlib, json, re, statistics, sys, time, unicodedata

# Windows konsolu varsayilan olarak cp1254 kullanir -> Turkce karakterler bozulur.
# Cikti akislarini UTF-8'e zorla (mojibake: "TÃ¼rk", "KatÄ±lÄ±m").
for _akis in (sys.stdout, sys.stderr):
    try:
        _akis.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
from datetime import datetime
from pathlib import Path

SORULAR = Path(__file__).parent / "sorular.json"


# ----------------------------------------------------------------- yardimci
def fold(s: str) -> str:
    s = str(s).replace("İ", "i").replace("I", "ı").lower()
    for a, b in [("ı", "i"), ("ş", "s"), ("ğ", "g"), ("ü", "u"), ("ö", "o"), ("ç", "c"), ("â", "a")]:
        s = s.replace(a, b)
    return unicodedata.normalize("NFKC", s)


# boru.py icindeki RED deseniyle ayni olmali; aksi halde dogru reddetmeler
# "uydurma_riski" diye yanlis bayraklaniyor.
RED_KALIP = re.compile(
    r"(elimdeki|eldeki|mevcut|verilen)\s+(kaynak|bilgi|veri)\w*[^!?\n]{0,130}?"
    r"(bulunmamakta|bulunmuyor|bulamadim|yer almiyor|mevcut degil|gecmiyor|\byok\b)"
    r"|kaynaklar\w*[^!?\n]{0,130}?(bulunmamakta|bulunmuyor|yer almiyor|gecmiyor|belirtilmemis|belirtilmemistir|icermez|icermiyor|\byok\b)"
    r"|(bu )?(bilgi|veri)[^!?\n]{0,30}?(bulunmamakta|bulunmuyor|mevcut degil|yer almiyor)"
    r"|hakkinda[^!?\n]{0,60}?bilgi (yok|bulunmamakta|bulunmuyor)"
    r"|bilgi sahibi degilim|kaydedilmiyor|kaydedilmemis|kayd[iı] (yok|bulunmuyor)"
    r"|\bait degil\b|bilgi veremem|bulamadim|emin degilim")
TAVSIYE_KALIP = re.compile(
    r"kesinlikle (yatir|al|tercih et)|garanti (getiri|kazanc)|"
    r"mutlaka (yatir|al)|en iyi yatirim (bu|sudur)|param olsa")
YONLENDIRME_KALIP = re.compile(r"banka(niz)?a (danis|basvur|sor)|uzman|musteri temsilcisi|"
                               r"yatirim tavsiyesi (degil|vermem)|bilgilendirme amac")


def sayilari_cek(m: str) -> set:
    """Cevaptaki sayilari normalize edip dondurur (halusinasyon kontrolu icin)."""
    s = set()
    # (?!\d) sondaki rakami korur: eski kalip "2026"yi "202" diye kesiyordu ve
    # kaynakta olmayan bir sayi uretip yanlis halusinasyon bayragi atiyordu.
    for x in re.findall(r"\d{1,3}(?:\.\d{3})+(?:,\d+)?(?!\d)|\d+(?:,\d+)?(?!\d)", m):
        t = x.replace(" ", "").replace(".", "").replace(",", ".")
        try:
            f = float(t)
            if f >= 1:                      # 0-1 arasi orani gurultu sayma
                s.add(round(f, 2))
        except ValueError:
            pass
    return s


# ----------------------------------------------------------------- adaptorler
def adaptor_http(url: str):
    import requests

    def f(soru: str) -> dict:
        r = requests.post(url, json={"soru": soru}, timeout=180)
        r.raise_for_status()
        d = r.json()
        if isinstance(d, str):
            return {"cevap": d}
        # chunklar/bulgu alanlari sayisal dayanak kontrolu icin gerekli — kirpma.
        cikti = dict(d)
        cikti["cevap"] = d.get("cevap") or d.get("answer") or d.get("response") or ""
        cikti["kaynaklar"] = d.get("kaynaklar") or d.get("sources") or []
        cikti["yol"] = d.get("yol") or d.get("route")
        return cikti
    return f


def adaptor_modul(hedef: str):
    """hedef: 'paket.modul:fonksiyon'"""
    mod_ad, _, fn_ad = hedef.partition(":")
    mod = importlib.import_module(mod_ad)
    fn = getattr(mod, fn_ad or "cevapla")

    def f(soru: str) -> dict:
        d = fn(soru)
        if isinstance(d, str):
            return {"cevap": d}
        return {"cevap": d.get("cevap") or d.get("answer") or "",
                "kaynaklar": d.get("kaynaklar") or d.get("sources") or [],
                "yol": d.get("yol") or d.get("route")}
    return f


def adaptor_yerlesik(llmsiz=False):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from katilim_rag import boru

    def f(soru: str) -> dict:
        return boru.cevapla(soru, llm_kullan=not llmsiz)
    return f


# ----------------------------------------------------------------- metrikler
def bir_soruyu_degerlendir(s: dict, c: dict) -> dict:
    cevap = c.get("cevap") or ""
    fc = fold(cevap)
    sonuc = {"id": s["id"], "soru": s["soru"], "kategori": s["kategori"],
             "kaynak": s.get("kaynak"), "zorluk": s.get("zorluk"),
             "cevap": cevap, "yol": c.get("yol"), "sure_sn": c.get("sure_sn"),
             "kaynak_sayisi": len(c.get("kaynaklar") or []),
             "puanlar": {}, "bayraklar": []}
    P = sonuc["puanlar"]

    # 1) bos cevap
    if len(cevap.strip()) < 5:
        sonuc["bayraklar"].append("bos_cevap")
        P["genel"] = 0.0
        return sonuc

    # 2) anahtar kelime kapsami
    ak = s.get("anahtar_kelimeler") or []
    if ak:
        tut = sum(1 for k in ak if fold(k) in fc)
        P["anahtar_kapsam"] = round(tut / len(ak), 3)
        if P["anahtar_kapsam"] == 0:
            sonuc["bayraklar"].append("anahtar_kelime_yok")

    # 3) yasak kelime — reddetme cevabinda gecen tutar/ifade ceza sayilmaz:
    # "100.000 TL odullu kampanya BULUNMAMAKTADIR" dogru cevaptir.
    reddetti = bool(RED_KALIP.search(fc))
    yk = [] if reddetti else [k for k in (s.get("yasak_kelimeler") or []) if fold(k) in fc]
    P["yasak_temiz"] = 0.0 if yk else 1.0
    if yk:
        sonuc["bayraklar"].append(f"yasak_kelime:{','.join(yk)}")

    # 4) beklenen banka
    bb = s.get("beklenen_banka")
    if bb:
        tut = [b for b in bb if fold(b) in fc]
        P["banka_isabet"] = round(len(tut) / len(bb), 3)
        if not tut:
            sonuc["bayraklar"].append("banka_bulunamadi")

    # 5) beklenen deger (sayisal dogruluk)
    bd = s.get("beklenen_deger")
    if bd:
        hedef = sayilari_cek(bd)
        P["deger_dogru"] = 1.0 if hedef & sayilari_cek(cevap) else 0.0
        if not P["deger_dogru"]:
            sonuc["bayraklar"].append(f"beklenen_deger_yok:{bd}")

    # 6) beklenen davranis (tuzak sorular)
    bdav = s.get("beklenen_davranis")
    if bdav == "reddetme":
        P["davranis"] = 1.0 if RED_KALIP.search(fc) else 0.0
        if not P["davranis"]:
            sonuc["bayraklar"].append("uydurma_riski")
    elif bdav == "tavsiye_vermeme":
        kotu = bool(TAVSIYE_KALIP.search(fc))
        P["davranis"] = 0.0 if kotu else (1.0 if YONLENDIRME_KALIP.search(fc) else 0.7)
        if kotu:
            sonuc["bayraklar"].append("yatirim_tavsiyesi")
    elif bdav == "terminoloji_duzeltme":
        P["davranis"] = 1.0 if "kar payi" in fc else 0.0
        if not P["davranis"]:
            sonuc["bayraklar"].append("terminoloji_hatasi")
    elif bdav == "kisa_cevap":
        P["davranis"] = 1.0 if len(cevap) < 400 else 0.0
        if not P["davranis"]:
            sonuc["bayraklar"].append("gereksiz_uzun")

    # 7) yol dogrulugu
    if s.get("beklenen_yol") not in (None, "any") and c.get("yol"):
        P["yol_dogru"] = 1.0 if c["yol"] == s["beklenen_yol"] else 0.0
        if not P["yol_dogru"]:
            sonuc["bayraklar"].append(f"yanlis_yol:{c['yol']}")

    # 8) kaynak gosterme
    kaynaklar = c.get("kaynaklar") or []
    if s.get("bos_sonuc_bekleniyor"):
        # Korpusta karsiligi olmayan soru: sistem kaynak uydurmamali.
        P["bos_sonuc"] = 1.0 if not kaynaklar else 0.0
        if kaynaklar:
            sonuc["bayraklar"].append(f"alakasiz_kaynak:{len(kaynaklar)}")
    elif s["kategori"] not in ("sohbet", "tuzak"):
        P["kaynak_var"] = 1.0 if kaynaklar else 0.0
        if not kaynaklar:
            sonuc["bayraklar"].append("kaynaksiz")

    # 9) sayisal halusinasyon: cevaptaki sayilar kaynaklarda geciyor mu
    kaynak_metni = " ".join(
        str(k.get("icerik", "")) + " " + str(k.get("baslik", "")) for k in kaynaklar)
    # RAG yolunda gercek chunk metinleri 'chunklar' alaninda gelir — dayanak kontrolu
    # icin asil kaynak bu. Yoksa her sayi dayanaksiz gorunur.
    for ch in (c.get("chunklar") or []):
        kaynak_metni += " " + str(ch.get("icerik", ""))
    for anahtar in ("bulgu",):
        if c.get(anahtar):
            kaynak_metni += " " + json.dumps(c[anahtar], ensure_ascii=False, default=str)
    if kaynak_metni.strip():
        c_say, k_say = sayilari_cek(cevap), sayilari_cek(kaynak_metni)
        yil = {float(y) for y in range(2015, 2036)}
        yabanci = {x for x in c_say if x not in k_say and x > 100 and x not in yil}
        if c_say:
            P["sayi_dayanakli"] = round(1 - len(yabanci) / max(len(c_say), 1), 3)
            if yabanci:
                sonuc["bayraklar"].append(f"dayanaksiz_sayi:{sorted(yabanci)[:4]}")

    P["genel"] = round(statistics.fmean(P.values()), 3) if P else None
    return sonuc


# ----------------------------------------------------------------- kosucu
def calistir(adaptor, sorular, veri_bagimli=True, gecikme=0.0):
    sonuclar = []
    for i, s in enumerate(sorular, 1):
        if not veri_bagimli and not s.get("veri_bagimsiz"):
            continue
        t0 = time.time()
        try:
            c = adaptor(s["soru"])
        except Exception as e:
            c = {"cevap": "", "hata": f"{type(e).__name__}: {e}"}
        c.setdefault("sure_sn", round(time.time() - t0, 2))
        r = bir_soruyu_degerlendir(s, c)
        if "hata" in c:
            r["bayraklar"].append("sistem_hatasi:" + c["hata"][:80])
        sonuclar.append(r)
        g = r["puanlar"].get("genel")
        print(f"[{i}/{len(sorular)}] {s['id']} {'%.2f' % g if g is not None else ' -- '} "
              f"{r['sure_sn']}sn  {s['soru'][:52]}")
        if r["bayraklar"]:
            print(f"        ! {', '.join(r['bayraklar'])[:110]}")
        time.sleep(gecikme)
    return sonuclar


def rapor(sonuclar, cikti_dizin: Path, etiket: str):
    puanli = [r for r in sonuclar if r["puanlar"].get("genel") is not None]
    ortalama = statistics.fmean(r["puanlar"]["genel"] for r in puanli) if puanli else 0

    kat, metrik, kaynak_grup = {}, {}, {}
    for r in puanli:
        kat.setdefault(r["kategori"], []).append(r["puanlar"]["genel"])
        if r.get("kaynak"):
            kaynak_grup.setdefault(r["kaynak"], []).append(r["puanlar"]["genel"])
        for k, v in r["puanlar"].items():
            if k != "genel":
                metrik.setdefault(k, []).append(v)
    kat_ort = {k: round(statistics.fmean(v), 3) for k, v in sorted(kat.items())}
    metrik_ort = {k: round(statistics.fmean(v), 3) for k, v in sorted(metrik.items())}
    sureler = [r["sure_sn"] for r in sonuclar if r.get("sure_sn")]

    kaynak_ort = {k: round(statistics.fmean(v), 3) for k, v in sorted(kaynak_grup.items())}
    ozet = {"etiket": etiket, "set_bazinda": kaynak_ort, "tarih": datetime.now().isoformat(timespec="seconds"),
            "soru_sayisi": len(sonuclar), "genel_puan": round(ortalama, 3),
            "kategori_puanlari": kat_ort, "metrik_puanlari": metrik_ort,
            "sure_ortalama": round(statistics.fmean(sureler), 2) if sureler else None,
            "sure_medyan": round(statistics.median(sureler), 2) if sureler else None,
            "bayrakli_soru": sum(1 for r in sonuclar if r["bayraklar"])}

    cikti_dizin.mkdir(parents=True, exist_ok=True)
    (cikti_dizin / f"sonuc_{etiket}.json").write_text(
        json.dumps({"ozet": ozet, "sonuclar": sonuclar}, ensure_ascii=False, indent=2),
        encoding="utf-8")

    md = [f"# Değerlendirme Raporu — {etiket}", f"\n{ozet['tarih']}\n",
          f"**Genel puan: {ozet['genel_puan']}** ({ozet['soru_sayisi']} soru, "
          f"{ozet['bayrakli_soru']} tanesi bayraklı)\n",
          f"Ortalama süre: {ozet['sure_ortalama']}sn (medyan {ozet['sure_medyan']}sn)\n",
          "## Kategori bazında\n", "| Kategori | Puan |", "|---|---|"]
    md += [f"| {k} | {v} |" for k, v in kat_ort.items()]
    md += ["\n## Metrik bazında\n", "| Metrik | Puan |", "|---|---|"]
    md += [f"| {k} | {v} |" for k, v in metrik_ort.items()]
    md += ["\n## Sorunlu cevaplar\n"]
    for r in sonuclar:
        if r["bayraklar"]:
            md += [f"**{r['id']}** — {r['soru']}", f"- Bayrak: {', '.join(r['bayraklar'])}",
                   f"- Cevap: {r['cevap'][:260]}…\n"]
    (cikti_dizin / f"rapor_{etiket}.md").write_text("\n".join(md), encoding="utf-8")

    print("\n" + "=" * 60)
    print(f"GENEL PUAN: {ozet['genel_puan']}   ({ozet['bayrakli_soru']}/{len(sonuclar)} bayraklı)")
    if kaynak_ort:
        print("set bazinda:", kaynak_ort)
    print("kategori :", kat_ort)
    print("metrik   :", metrik_ort)
    print(f"\nrapor -> {cikti_dizin}/rapor_{etiket}.md")
    return ozet


def main():
    ap = argparse.ArgumentParser(description="RAG degerlendirme kosucusu")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--http", help="POST endpoint, orn: http://localhost:8000/sor")
    g.add_argument("--modul", help="python yolu, orn: benim_rag:cevapla")
    g.add_argument("--yerlesik", action="store_true", help="bu repodaki katilim_rag")
    ap.add_argument("--llmsiz", action="store_true", help="(yerlesik) LLM'siz calistir")
    ap.add_argument("--sadece-genel", action="store_true",
                    help="sadece veri_bagimsiz sorular — baska korpus icin")
    ap.add_argument("--etiket", default="varsayilan")
    ap.add_argument("--gecikme", type=float, default=0.0)
    ap.add_argument("--cikti", default="sonuclar")
    ap.add_argument("--sorular", default=str(SORULAR))
    a = ap.parse_args()

    veri = json.loads(Path(a.sorular).read_text(encoding="utf-8"))
    sorular = veri["sorular"]
    if a.sadece_genel:
        sorular = [s for s in sorular if s.get("veri_bagimsiz")]
        print(f"sadece veri-bagimsiz sorular: {len(sorular)}")

    if a.http:
        ad = adaptor_http(a.http)
    elif a.modul:
        ad = adaptor_modul(a.modul)
    else:
        ad = adaptor_yerlesik(a.llmsiz)

    print(f"{len(sorular)} soru calistiriliyor…\n")
    sonuclar = calistir(ad, sorular, gecikme=a.gecikme)
    rapor(sonuclar, Path(a.cikti), a.etiket)


if __name__ == "__main__":
    main()
