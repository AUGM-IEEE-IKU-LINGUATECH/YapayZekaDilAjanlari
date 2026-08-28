# -*- coding: utf-8 -*-
"""ADIMLAR
1. Kâr payı artefakt temizligi (8 hucre):
   - Hesaplayici formu metninden yakalanan sahte %1.0 (Kuveyt, leasing araci)
   - Urun semantigiyle celisen Veri Seti degerleri (kart cashback'i %1.0,
     katilma hesabinda %1.0 "getiri")
   - Kâr PAYLASIM oranlarinin (92/8, 98/2) kâr payi ORANI sanilmasi
   - Birikim hesabi tanitim metinlerinden gelen %20/%25
   Deger NULL yapilir, kar_payi_kaynak'a "[elendi: ...]" izi eklenir —
   hicbir kayit silinmez, karar denetlenebilir kalir.
2. kampanya_turu kanonlestirme (sartname 5.4): belge_turu ile capraz
   kirlenmis kolon, sartnamenin 8 kategorisine (+bos) esitlenir.
   belge_turu'na ve sayimlara DOKUNULMAZ (kampanya_turu hicbir WHERE
   filtresinde kullanilmiyor; yalnizca gosterim/panel duzelir).
3. dolayli_kar_payi kolonu (sartname 5.2): "avantajli kâr payi",
   "ozel oranli finansman", "dusuk maliyetli finansman", "masrafsiz
   finansman" gibi dolayli ifadeler belge metninden taranip etiketlenir.

    python migrasyon_2026_08.py            # uygula
    python migrasyon_2026_08.py --kuru     # sadece ne yapacagini goster
"""
import argparse, json, re, sqlite3, unicodedata
from pathlib import Path

KOK = Path(__file__).resolve().parent
DB = KOK / "veri" / "katilim.db"
CHUNKS = KOK / "veri" / "rag_chunks.jsonl"


def fold(s):
    s = str(s or "").replace("İ", "i").replace("I", "ı").lower()
    for a, b in [("ı", "i"), ("ş", "s"), ("ğ", "g"), ("ü", "u"), ("ö", "o"), ("ç", "c"), ("â", "a")]:
        s = s.replace(a, b)
    return unicodedata.normalize("NFKC", s)


ELEME_KURALLARI = [
    ("hesaplayici formu metni (oran degil, form alani)",
     "kar_payi_orani IS NOT NULL AND kar_payi_kaynak LIKE '%Mal Bedeli%Peşinat%'", ()),
    ("kart kampanyasinda %1.0 — cashback/iade oraninin kâr payi sanilmasi",
     "kar_payi_orani = 1.0 AND urun_tipi = 'kredi_karti' AND kar_payi_kaynak LIKE '%(Veri Seti)%'", ()),
    ("katilma hesabinda %1.0 — getiri orani olarak anlamsiz (TL katilma ~%30-45)",
     "kar_payi_orani = 1.0 AND urun_tipi = 'katilma_hesabi' AND kar_payi_kaynak LIKE '%(Veri Seti)%'", ()),
    ("kâr PAYLASIM orani (92/8, 98/2) — kâr payi ORANI degil, havuz bolusum orani",
     "kar_payi_orani >= 90 AND urun_tipi = 'katilma_hesabi'", ()),
    ("birikim hesabi tanitim metni (%20/%25) — kâr payi orani degil",
     "kar_payi_orani IN (20.0, 25.0) AND kar_payi_kaynak LIKE '%birikim%'", ()),
]


def kar_payi_temizle(c, kuru):
    n_toplam = 0
    for aciklama, kosul, par in ELEME_KURALLARI:
        satirlar = c.execute(
            f"SELECT rowid, banka_adi, baslik, kar_payi_orani FROM urunler WHERE {kosul}", par
        ).fetchall()
        for rowid, banka, baslik, oran in satirlar:
            print(f"  ELENDI  %{oran:<6} {banka[:20]:20s} {baslik[:44]:44s} | {aciklama}")
            if not kuru:
                c.execute(
                    "UPDATE urunler SET kar_payi_orani = NULL, "
                    "kar_payi_kaynak = '[elendi: ' || ? || '] ' || COALESCE(kar_payi_kaynak,'') "
                    "WHERE rowid = ?", (aciklama, rowid))
        n_toplam += len(satirlar)
    return n_toplam


# ---------------------------------------------------------------- 2) KAMPANYA TURU
KANON = {
    "konut": "Konut Finansmanı Kampanyası",
    "arac": "Taşıt Finansmanı Kampanyası",
    "ihtiyac": "İhtiyaç Finansmanı Kampanyası",
    "kredi_karti": "Kart Kampanyası",
    "katilma_hesabi": "Yatırım Ürünü Kampanyası",
    "yatirim_fonu": "Yatırım Ürünü Kampanyası",
    "isyeri": "Finansman Kampanyası",
    "kobi_ticari": "Finansman Kampanyası",
    "egitim": "Finansman Kampanyası",
    "surdurulebilir": "Finansman Kampanyası",
    "sigorta": "Diğer Kampanya",
}
KAMPANYA_DISI_BASLIK = re.compile(r"danisma komitesi|^belgeler$|nedir\??$|urun ve hizmetleri")
KAMPANYA_BELGE = ("kampanya",)


def kampanya_turu_hesapla(urun_tipi, alisveris_puani, baslik, kosullar, yeni_musteri):
    f = fold(f"{baslik} {kosullar}")
    if yeni_musteri and re.search(r"yeni musteri|ilk kez|hos ?geldin", f):
        return "Yeni Müşteri Kampanyası"
    if urun_tipi == "kredi_karti" and alisveris_puani:
        return "Alışveriş Puanı Kampanyası"
    return KANON.get(urun_tipi, "Finansman Kampanyası")


def kampanya_turu_duzelt(c, kuru):
    satirlar = c.execute(
        "SELECT rowid, doc_id, belge_turu, urun_tipi, alisveris_puani, baslik, "
        "kampanya_kosullari, yeni_musteri, kampanya_turu FROM urunler").fetchall()
    n = 0
    for (rowid, doc_id, belge, urun, puan, baslik, kosul, yeni, eski) in satirlar:
        csv_kokenli = "__csv_" in (doc_id or "")
        kampanya_mi = (belge in KAMPANYA_BELGE) or csv_kokenli
        if csv_kokenli and KAMPANYA_DISI_BASLIK.search(fold(baslik)):
            kampanya_mi = False
        yeni_tur = kampanya_turu_hesapla(urun, puan, baslik, kosul, yeni) if kampanya_mi else ""
        if yeni_tur != (eski or ""):
            n += 1
            if not kuru:
                c.execute("UPDATE urunler SET kampanya_turu = ? WHERE rowid = ?", (yeni_tur, rowid))
    return n


# ---------------------------------------------------------------- 3) DOLAYLI KAR PAYI
# NOT: metin fold() ile katlanmis gelir (kâr->kar, ı->i); desenler ona goredir.
DOLAYLI = [
    ("avantajli_kar_payi", r"avantajli kar pay|kar payi avantaj|kar payi firsat|cazip kar pay"),
    ("ozel_oranli", r"ozel oranli|ozel kar pay"),
    ("dusuk_maliyetli", r"dusuk maliyetli|uygun maliyetli|dusuk kar payi"),
    ("masrafsiz", r"masrafsiz finansman|dosya masrafi alinm|dosya masrafi yok|masraf alinmamaktadir"),
]


def dolayli_doldur(c, kuru):
    kolonlar = [r[1] for r in c.execute("PRAGMA table_info(urunler)")]
    if "dolayli_kar_payi" not in kolonlar:
        if kuru:
            print("  (kuru) kolon eklenecek: dolayli_kar_payi")
            return 0
        c.execute("ALTER TABLE urunler ADD COLUMN dolayli_kar_payi TEXT DEFAULT ''")
        print("  kolon eklendi: dolayli_kar_payi")

    metinler = {}
    if CHUNKS.exists():
        for satir in CHUNKS.open(encoding="utf-8"):
            ch = json.loads(satir)
            metinler[ch["doc_id"]] = metinler.get(ch["doc_id"], "") + " " + ch["content"]

    n = 0
    for rowid, doc_id, kosul, mevcut in c.execute(
            "SELECT rowid, doc_id, kampanya_kosullari, dolayli_kar_payi FROM urunler").fetchall():
        metin = fold(metinler.get(doc_id, "") or kosul or "")
        etiketler = ",".join(ad for ad, p in DOLAYLI if re.search(p, metin))
        if etiketler != (mevcut or ""):
            n += 1
            if not kuru:
                c.execute("UPDATE urunler SET dolayli_kar_payi = ? WHERE rowid = ?", (etiketler, rowid))
    return n


ESIK_DESEN = [
    re.compile(r"(\d[\d.,]*)\s*tl[^.\n]{0,30}?(?:ve\s+)?uzer\w*[^.\n]{0,60}?(harcama|alisveris|odeme|islem|tutar)"),
    re.compile(r"(harcama|alisveris|odeme|islem)\w*[^.\n]{0,60}?(\d[\d.,]*)\s*tl[^.\n]{0,20}?(?:ve\s+)?uzer"),
    re.compile(r"en az\s+(\d[\d.,]*)\s*tl[^.\n]{0,25}?(harcama|alisveris|odeme|islem)"),
    re.compile(r"minimum\s+(\d[\d.,]*)\s*tl"),
    re.compile(r"asgari\s+(\d[\d.,]*)\s*tl"),
]


def _sayi(t):
    t = t.replace(".", "").replace(",", ".")
    try:
        return float(t)
    except ValueError:
        return None


def esik_doldur(c, kuru):
    kolonlar = [r[1] for r in c.execute("PRAGMA table_info(urunler)")]
    if "esik_tutar" not in kolonlar:
        if kuru:
            print("  (kuru) kolon eklenecek: esik_tutar"); return 0
        c.execute("ALTER TABLE urunler ADD COLUMN esik_tutar REAL")
        print("  kolon eklendi: esik_tutar")

    metinler = {}
    if CHUNKS.exists():
        for satir in CHUNKS.open(encoding="utf-8"):
            ch = json.loads(satir)
            metinler[ch["doc_id"]] = metinler.get(ch["doc_id"], "") + " " + ch["content"]

    n = 0
    for rowid, doc_id, kosul, belge, ktur, mevcut in c.execute(
            "SELECT rowid, doc_id, kampanya_kosullari, belge_turu, kampanya_turu, esik_tutar "
            "FROM urunler").fetchall():
        kampanya_mi = (belge == "kampanya") or (ktur or "") != ""
        yeni = None
        if kampanya_mi:
            metin = fold((metinler.get(doc_id, "") or "") + " " + (kosul or ""))
            adaylar = []
            for d in ESIK_DESEN:
                for m in d.finditer(metin):
                    grup = next((g for g in m.groups() if g and g[0].isdigit()), None)
                    v = _sayi(grup) if grup else None
                    if v and 50 <= v <= 500000:
                        adaylar.append(v)
            if adaylar:
                yeni = min(adaylar)
        if yeni != mevcut:
            n += 1
            if not kuru:
                c.execute("UPDATE urunler SET esik_tutar = ? WHERE rowid = ?", (yeni, rowid))
    return n


AYLAR_TR = {"ocak":1,"şubat":2,"subat":2,"mart":3,"nisan":4,"mayıs":5,"mayis":5,
            "haziran":6,"temmuz":7,"ağustos":8,"agustos":8,"eylül":9,"eylul":9,
            "ekim":10,"kasım":11,"kasim":11,"aralık":12,"aralik":12}


def _tarih(y, m, d):
    import datetime
    try:
        dt = datetime.date(int(y), int(m), int(d))
        return dt.isoformat() if 2015 <= dt.year <= 2035 else None
    except Exception:
        return None


def tarihleri_ayikla(t):
    tl = (t or "").lower()
    out = {"baslangic": None, "bitis": None}
    m = re.search(r"(\d{1,2})[-./](\d{1,2})[-./](\d{4})\s*[-–]\s*(\d{1,2})[-./](\d{1,2})[-./](\d{4})", tl)
    if m:
        out["baslangic"] = _tarih(m.group(3), m.group(2), m.group(1))
        out["bitis"] = _tarih(m.group(6), m.group(5), m.group(4)); return out
    m = re.search(r"(\d{1,2})\s+([a-zçğıöşü]+)\s+(\d{4})\s*[-–]\s*(\d{1,2})\s+([a-zçğıöşü]+)\s+(\d{4})", tl)
    if m and m.group(2) in AYLAR_TR and m.group(5) in AYLAR_TR:
        out["baslangic"] = _tarih(m.group(3), AYLAR_TR[m.group(2)], m.group(1))
        out["bitis"] = _tarih(m.group(6), AYLAR_TR[m.group(5)], m.group(4)); return out
    m = re.search(r"(?:son gün|bitiş tarihi|son tarih)\s*:?\s*(\d{1,2})[-./](\d{1,2})[-./](\d{4})", tl)
    if m:
        out["bitis"] = _tarih(m.group(3), m.group(2), m.group(1)); return out
    m = (re.search(r"(?:bitiş tarihi\s*:?|son(?:una)? kadar|kadar geçerli|tarihine kadar)\D{0,25}?(\d{1,2})\s+([a-zçğıöşü]+)\s+(\d{4})", tl)
         or re.search(r"(\d{1,2})\s+([a-zçğıöşü]+)\s+(\d{4})\s+tarihine kadar", tl))
    if m and m.group(2) in AYLAR_TR:
        out["bitis"] = _tarih(m.group(3), AYLAR_TR[m.group(2)], m.group(1))
    return out


def tarih_doldur(c, kuru):
    kolonlar = [r[1] for r in c.execute("PRAGMA table_info(urunler)")]
    for k in ("baslangic_tarihi", "bitis_tarihi"):
        if k not in kolonlar:
            if kuru:
                print(f"  (kuru) kolon eklenecek: {k}")
            else:
                c.execute(f"ALTER TABLE urunler ADD COLUMN {k} TEXT")
                print(f"  kolon eklendi: {k}")
    if kuru and ("bitis_tarihi" not in kolonlar):
        return 0

    metinler = {}
    if CHUNKS.exists():
        for satir in CHUNKS.open(encoding="utf-8"):
            ch = json.loads(satir)
            metinler[ch["doc_id"]] = metinler.get(ch["doc_id"], "") + " " + ch["content"]

    n = 0
    for (rowid, doc_id, kosul, belge, ktur, mb, mbit) in c.execute(
            "SELECT rowid, doc_id, kampanya_kosullari, belge_turu, kampanya_turu, "
            "baslangic_tarihi, bitis_tarihi FROM urunler").fetchall():
        kampanya_mi = ((belge == "kampanya") or (ktur or "") != "") and belge != "liste_sayfasi"
        yb = yt = None
        if kampanya_mi:
            d = tarihleri_ayikla((metinler.get(doc_id, "") or "") + " " + (kosul or ""))
            yb, yt = d["baslangic"], d["bitis"]
        if (yb, yt) != (mb, mbit):
            n += 1
            if not kuru:
                c.execute("UPDATE urunler SET baslangic_tarihi = ?, bitis_tarihi = ? "
                          "WHERE rowid = ?", (yb, yt, rowid))
    return n


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--kuru", action="store_true", help="degisiklik yazma, sadece raporla")
    a = ap.parse_args()
    c = sqlite3.connect(DB)

    print("=" * 70)
    print("[1] Kâr payı artefakt temizligi")
    n1 = kar_payi_temizle(c, a.kuru)
    print(f"    -> {n1} hucre")

    print("[2] kampanya_turu kanonlestirme (sartname 5.4)")
    n2 = kampanya_turu_duzelt(c, a.kuru)
    print(f"    -> {n2} kayit guncellendi")

    print("[3] dolayli_kar_payi etiketleme (sartname 5.2)")
    n3 = dolayli_doldur(c, a.kuru)
    print(f"    -> {n3} kayit etiketlendi")

    print("[4] esik_tutar (harcama katilim esigi) cikarimi")
    n4 = esik_doldur(c, a.kuru)
    print(f"    -> {n4} kayit guncellendi")

    print("[5] kampanya tarihleri (baslangic/bitis) cikarimi")
    n5 = tarih_doldur(c, a.kuru)
    print(f"    -> {n5} kayit guncellendi")

    if not a.kuru:
        c.commit()
        print("\nOZET (migrasyon sonrasi):")
        for tur, n in c.execute("SELECT kampanya_turu, COUNT(*) FROM urunler "
                                "WHERE kampanya_turu != '' GROUP BY 1 ORDER BY 2 DESC"):
            print(f"  {tur:32s} {n}")
        kp = c.execute("SELECT COUNT(kar_payi_orani) FROM urunler").fetchone()[0]
        dl = c.execute("SELECT COUNT(*) FROM urunler WHERE dolayli_kar_payi != ''").fetchone()[0]
        print(f"  kar_payi_orani dolu: {kp} | dolayli ifade etiketli: {dl}")
    c.close()
    print("bitti" + (" (KURU KOSU — yazilmadi)" if a.kuru else ""))


if __name__ == "__main__":
    main()
