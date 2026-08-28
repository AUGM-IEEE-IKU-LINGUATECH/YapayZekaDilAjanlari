# -*- coding: utf-8 -*-
"""rag_chunks.jsonl + Veri_Set.csv -> SQLite katilim.db

!!! ONEMLI: Bu script, depoyla birlikte teslim edilen veri/katilim.db'yi
BIREBIR uretmez (teslim edilen DB daha guncel bir zenginlestirme akisinin
urunudur: 1114 kayit, genisletilmis hedef kitle sozlugu, tahsis/oran
zenginlestirmeleri). Teslim edilen DB'yi SILMEYIN/EZMEYIN; veri duzeltmeleri
icin migrasyon_2026_08.py kullanilir. Bu script sifirdan kurulum senaryosu
icindir ve cikti kalitesi teslim edilen DB'nin gerisinde kalir.

Teknofest Senaryo 2 Bilgi Çıkarımı Şeması:
1. Banka Bilgisi (Banka Adı, Kodu)
2. Finansman Bilgileri (Kâr Payı Oranı, Finansman Tutarı, Vade Süresi, Taksit Sayısı, Tahsis Ücreti, Masraf Bilgisi)
3. Kampanya Bilgileri (Kampanya Türü, Ödül Miktarı, İndirim Oranı, Alışveriş Puanı, Kampanya Süresi, Kampanya Koşulları)
4. Hedef Kitle Bilgileri (Yeni Müşteri, Mevcut Müşteri, Maaş Müşterisi, KOBİ/Esnaf vb.)
"""
import json, os, re, sqlite3, unicodedata
import pandas as pd
from pathlib import Path

from katilim_rag.config import VERI, DB_YOLU, CHUNKS_JSONL

CSV_YOLU = VERI / "Veri_Set.csv"

def fold(s):
    if not s: return ""
    s = str(s).replace("İ", "i").replace("I", "ı").lower()
    for a, b in [("ı","i"),("ş","s"),("ğ","g"),("ü","u"),("ö","o"),("ç","c")]:
        s = s.replace(a, b)
    return unicodedata.normalize("NFKC", s)

BANKA_MAP = {
    "albaraka": ("albaraka", "Albaraka Türk Katılım Bankası A.Ş."),
    "albaraka türk": ("albaraka", "Albaraka Türk Katılım Bankası A.Ş."),
    "kuveyt_turk": ("kuveyt_turk", "Kuveyt Türk Katılım Bankası A.Ş."),
    "kuveyt türk": ("kuveyt_turk", "Kuveyt Türk Katılım Bankası A.Ş."),
    "ziraat_katilim": ("ziraat_katilim", "Ziraat Katılım Bankası A.Ş."),
    "ziraat katılım": ("ziraat_katilim", "Ziraat Katılım Bankası A.Ş."),
    "vakif_katilim": ("vakif_katilim", "Vakıf Katılım Bankası A.Ş."),
    "vakıf katılım": ("vakif_katilim", "Vakıf Katılım Bankası A.Ş."),
    "turkiye_finans": ("turkiye_finans", "Türkiye Finans Katılım Bankası A.Ş."),
    "türkiye finans": ("turkiye_finans", "Türkiye Finans Katılım Bankası A.Ş."),
    "emlak_katilim": ("emlak_katilim", "Türkiye Emlak Katılım Bankası A.Ş."),
    "emlak katılım": ("emlak_katilim", "Türkiye Emlak Katılım Bankası A.Ş."),
    "türkiye emlak katılım": ("emlak_katilim", "Türkiye Emlak Katılım Bankası A.Ş."),
    "hayat_finans": ("hayat_finans", "Hayat Finans Katılım Bankası A.Ş."),
    "hayat finans": ("hayat_finans", "Hayat Finans Katılım Bankası A.Ş."),
    "dunya_katilim": ("dunya_katilim", "Dünya Katılım Bankası A.Ş."),
    "dünya katılım": ("dunya_katilim", "Dünya Katılım Bankası A.Ş."),
    "adil_katilim": ("adil_katilim", "Adil Katılım Bankası A.Ş."),
    "adil katılım": ("adil_katilim", "Adil Katılım Bankası A.Ş."),
    "tom_katilim": ("tom_katilim", "T.O.M. Katılım Bankası A.Ş."),
    "t.o.m. katılım": ("tom_katilim", "T.O.M. Katılım Bankası A.Ş."),
}

def banka_bilgisi(ham_banka):
    norm = fold(ham_banka)
    for k, v in BANKA_MAP.items():
        if fold(k) in norm:
            return v
    return ("diger", ham_banka)

URUN_TIPI = {
    "konut": r"konut|mortgage|ev sahib|yeni ev|arsa|gayrimenkul",
    "arac": r"\barac\b|tasit|otomobil|motosiklet|togg|tekne|karavan",
    "ihtiyac": r"ihtiyac|finansman basvuru|masrafsiz finansman",
    "isyeri": r"isyeri|ticari gayrimenkul|dukkan",
    "kobi_ticari": r"kobi|isletme|ticari finans|esnaf|taksitli ticari|sektor",
    "katilma_hesabi": r"katilma hesab|katilim hesab|birikim hesab|altin hesab|dijital katilma|mevduat",
    "kredi_karti": r"kredi kart|bankkart|paraf|world|troy|kart|nakit avans|harcama|alisveris|slip|pos",
    "sigorta": r"sigorta|emeklilik|dask|kasko",
    "yatirim_fonu": r"yatirim fonu|portfoy|\bfon\b|hisse|sukuk",
    "egitim": r"egitim finansman|ogrenci|okul",
    "surdurulebilir": r"surdurulebilir|yesil|elektrikli arac|ges\b|gunes",
}

def tespit_urun_tipi(baslik, text=""):
    hay = fold(str(baslik) + " " + str(text[:500]))
    for k, p in URUN_TIPI.items():
        if re.search(p, hay):
            return k
    return "diger"

# Kâr payı oran regexleri
KAR_REGEXLER = [
    re.compile(r"%\s*([0-9]{1,2}(?:[.,][0-9]{1,2})?)\s*(?:[\'’]?[a-z]{0,10}\s+)?(?:başlayan\s+)?(?:kâr|kar)\s*(?:payı|payi|oranı|orani)", re.I),
    re.compile(r"(?:kâr|kar)\s*(?:payı|payi|oranı|orani)[^0-9\n]{0,25}?%\s*([0-9]{1,2}(?:[.,][0-9]{1,2})?)", re.I),
    re.compile(r"(?:kâr|kar)\s*paylaşım\s*oranı[^0-9\n]{0,20}?([0-9]{2})\s*/\s*([0-9]{1,2})", re.I),
    re.compile(r"kâr\s*oranı\s*%\s*([0-9]{1,2}(?:[.,][0-9]{1,2})?)", re.I),
    re.compile(r"%\s*([0-9]{1,2}(?:[.,][0-9]{1,2})?)\s*kâr\s*oranı", re.I),
]

COP_ORAN = re.compile(r"ödeme planı|taksit no|0,00 tl|maliyet oranı|gecikme cezası"
                      r"|mal bedeli|peşinat tutarı|döviz tipi|hesaplama arac", re.I)  # hesaplayici formlari

def kar_payi_cikar(text, fd_val=None):
    if fd_val:
        v = str(fd_val).replace("%", "").replace(",", ".").strip()
        try:
            f = float(v)
            if 0 < f <= 100:
                return f, f"%{f} (Veri Seti)"
        except:
            if "/" in str(fd_val):
                return None, str(fd_val)

    if not text: return None, None
    for s in re.split(r"(?<=[.!?\n])\s*", str(text)):
        if COP_ORAN.search(s): continue
        for r in KAR_REGEXLER:
            m = r.search(s)
            if m:
                if len(m.groups()) == 2 and m.group(2) and m.group(1).isdigit():
                    p1, p2 = m.group(1), m.group(2)
                    return float(p1), f"{p1}/{p2} paylaşım oranı: {s.strip()[:100]}"
                v = m.group(1)
                try:
                    f = float(v.replace(",", "."))
                    if 0 < f <= 60:
                        return f, s.strip()[:180]
                except:
                    pass
    return None, None

def vade_cikar(text, fd_vade=None, sayisal_vade=None):
    if fd_vade:
        m = re.search(r"(\d+)", str(fd_vade))
        if m: return int(m.group(1))
    if sayisal_vade:
        nums = [int(x) for x in sayisal_vade if 0 < int(x) <= 360]
        if nums: return max(nums)
    if text:
        m = re.search(r"(\d{1,3})\s*(?:aya|ay\'a|ay|yıl|yıla)?\s*varan\s*vade", str(text), re.I)
        if m: return int(m.group(1))
        m2 = re.search(r"(\d{1,3})\s*ay\s*vade", str(text), re.I)
        if m2: return int(m2.group(1))
    return None

def taksit_cikar(text, sayisal_taksit=None):
    if sayisal_taksit:
        nums = [int(x) for x in sayisal_taksit if 0 < int(x) <= 60]
        if nums: return max(nums)
    if text:
        m = re.search(r"(\d{1,2})\s*taksit", str(text), re.I)
        if m: return int(m.group(1))
    return None

def tutar_cikar(text, fd_min=None, fd_max=None, sayisal_tutar=None):
    t_min = None
    t_max = None
    if fd_min:
        try: t_min = float(str(fd_min).replace(".","").replace(",","."))
        except: pass
    if fd_max:
        try: t_max = float(str(fd_max).replace(".","").replace(",","."))
        except: pass
    
    clean_nums = []
    if sayisal_tutar:
        for x in sayisal_tutar:
            try:
                f = float(x)
                if f >= 1000:
                    clean_nums.append(f)
            except:
                pass

    if text:
        for m in re.finditer(r"([0-9]{1,3}(?:\.[0-9]{3})+|[0-9]{4,9})\s*(?:TL|tl|Türk Lirası)?", str(text)):
            try:
                num = float(m.group(1).replace(".", ""))
                if 1000 <= num <= 500_000_000:
                    clean_nums.append(num)
            except:
                pass
        for m in re.finditer(r"([0-9]+(?:[.,][0-9]+)?)\s*milyon\s*TL", str(text), re.I):
            try:
                num = float(m.group(1).replace(",", ".")) * 1_000_000
                clean_nums.append(num)
            except:
                pass

    if clean_nums:
        t_max = max(t_max or 0, max(clean_nums))
        t_min = min(t_min or 1e12, min(clean_nums))
        if t_min == 1e12: t_min = None

    return t_min, t_max

def tahsis_masraf_cikar(text, fd_masraf=None):
    tahsis = None
    masraf = fd_masraf
    if text:
        m_t = re.search(r"(?:tahsis\s*ücreti|kredi\s*tahsis\s*ücreti)[^.\n]{0,60}", str(text), re.I)
        if m_t: tahsis = m_t.group(0).strip()
        m_m = re.search(r"(?:masrafsız|masraf\s*bilgisi|ekspertiz\s*ücreti|ipotek\s*tesis\s*ücreti|hayat\s*sigortası)[^.\n]{0,80}", str(text), re.I)
        if m_m and not masraf: masraf = m_m.group(0).strip()
    return tahsis, masraf

def odul_indirim_puan_cikar(text, fd_odul=None):
    odul = fd_odul
    indirim = None
    puan = None
    if text:
        m_p = re.search(r"([0-9.,]+\s*(?:TL\s*)?(?:Worldpuan|Bankkart\s*Lira|Bonus|Puan|TL\s*indirim|TL\s*Hediye|TL\s*Puan))", str(text), re.I)
        if m_p: puan = m_p.group(1).strip()
        m_i = re.search(r"%\s*([0-9]{1,2})\s*indirim", str(text), re.I)
        if m_i: indirim = f"%{m_i.group(1)}"
    return odul, indirim, puan

def hedef_kitle_coz(hedef_str, text=""):
    s = fold(str(hedef_str) + " " + str(text[:300]))
    yeni = 1 if re.search(r"yeni\s*musteri|ilk\s*kez|yeni\s*uye|yeni\s*musterilere", s) else 0
    mevcut = 1 if re.search(r"mevcut\s*musteri|tum\s*musteri|tum\s*kart|genel", s) else 0
    maas = 1 if re.search(r"maas\s*musteri|emekli|kamu", s) else 0
    kobi = 1 if re.search(r"kobi|esnaf|ticari|tuzel|sirket|isletme", s) else 0
    troy = 1 if re.search(r"troy", s) else 0
    
    kitle_etiket = []
    if yeni: kitle_etiket.append("Yeni Müşteri")
    if maas: kitle_etiket.append("Maaş Müşterisi")
    if kobi: kitle_etiket.append("Esnaf / KOBİ")
    if troy: kitle_etiket.append("TROY Kart")
    if mevcut or not kitle_etiket: kitle_etiket.append("Genel")
    
    return ", ".join(kitle_etiket), yeni, mevcut, maas, kobi

def main():
    print(f"katilim.db yapilandiriliyor: {DB_YOLU}")
    DB_YOLU.parent.mkdir(parents=True, exist_ok=True)
    if DB_YOLU.exists():
        try: DB_YOLU.unlink()
        except: pass

    con = sqlite3.connect(DB_YOLU)
    con.execute("""CREATE TABLE urunler(
        doc_id TEXT PRIMARY KEY,
        banka_kodu TEXT,
        banka_adi TEXT,
        baslik TEXT,
        urun_tipi TEXT,
        belge_turu TEXT,
        segment TEXT,
        kategoriler TEXT,
        -- Finansman Bilgileri (Senaryo 2 Tablo Sutun 2)
        kar_payi_orani REAL,
        kar_payi_kaynak TEXT,
        finansman_tutari_min REAL,
        tutar_max REAL,
        vade_ay_min INTEGER,
        vade_ay_max INTEGER,
        taksit_min INTEGER,
        taksit_max INTEGER,
        tahsis_ucreti TEXT,
        masraf_bilgisi TEXT,
        -- Kampanya Bilgileri (Senaryo 2 Tablo Sutun 3)
        kampanya_turu TEXT,
        odul_miktari TEXT,
        indirim_orani TEXT,
        alisveris_puani TEXT,
        kampanya_baslangic TEXT,
        kampanya_bitis TEXT,
        kampanya_suresi TEXT,
        kampanya_kosullari TEXT,
        -- Hedef Kitle Bilgileri (Senaryo 2 Tablo Sutun 4)
        hedef_kitle TEXT,
        yeni_musteri INTEGER DEFAULT 0,
        mevcut_musteri INTEGER DEFAULT 0,
        maas_musterisi INTEGER DEFAULT 0,
        kobi_esnaf INTEGER DEFAULT 0,
        -- Genel meta
        gecerlilik TEXT,
        sektor TEXT,
        anahtar_kelimeler TEXT,
        kaynak_url TEXT,
        karakter_sayisi INTEGER,
        rag_oncelik TEXT
    )""")

    docs = {}
    if CHUNKS_JSONL.exists():
        for line in CHUNKS_JSONL.open(encoding="utf-8"):
            c = json.loads(line)
            did = c["doc_id"]
            if did not in docs:
                docs[did] = {
                    "doc_id": did,
                    "metadata": c["metadata"],
                    "content": c["content"],
                    "all_content": c["content"]
                }
            else:
                docs[did]["all_content"] += "\n" + c["content"]
        print(f"rag_chunks.jsonl: {len(docs)} dokuman yuklendi.")

    csv_records = []
    if CSV_YOLU.exists():
        df = pd.read_csv(CSV_YOLU)
        for _, r in df.iterrows():
            fd = {}
            if pd.notna(r.get("Finansal_Detaylar")):
                try: fd = json.loads(r["Finansal_Detaylar"])
                except: pass
            csv_records.append({
                "banka_adi": r.get("Banka_Adi", ""),
                "baslik": r.get("Kampanya_Basligi", ""),
                "kampanya_turu": r.get("Kampanya_Turu", ""),
                "metin": r.get("Temiz_Metin", ""),
                "finansal": fd
            })
        print(f"Veri_Set.csv: {len(csv_records)} satir yuklendi.")

    islenen_kayitlar = {}

    for did, d in docs.items():
        m = d["metadata"]
        t = d["all_content"]
        s = m.get("sayisal_bilgiler", {})
        baslik = m.get("baslik", "")
        banka_kodu, banka_adi = banka_bilgisi(m.get("banka_adi") or m.get("banka_kodu", ""))
        
        fd_match = {}
        for cr in csv_records:
            if fold(baslik) in fold(cr["baslik"]) or fold(cr["baslik"]) in fold(baslik):
                fd_match = cr["finansal"]
                break

        oran, oran_kaynak = kar_payi_cikar(t, fd_match.get("kar_payi"))
        vade = vade_cikar(t, fd_match.get("vade"), s.get("vade_ay"))
        taksit = taksit_cikar(t, s.get("taksit_sayisi"))
        t_min, t_max = tutar_cikar(t, fd_match.get("min_tutar"), fd_match.get("max_tutar"), s.get("tutarlar_tl"))
        tahsis, masraf = tahsis_masraf_cikar(t, fd_match.get("masraf_durumu"))
        odul, indirim, puan = odul_indirim_puan_cikar(t, fd_match.get("odul_fayda"))
        
        kitle_raw = fd_match.get("hedef_kitle") or m.get("musteri_segmenti") or "Genel"
        hedef_kitle_str, ym, mm, maas, kobi = hedef_kitle_coz(kitle_raw, t)

        u_tip = tespit_urun_tipi(baslik, t)
        
        islenen_kayitlar[did] = (
            did, banka_kodu, banka_adi, baslik,
            u_tip, m.get("belge_turu", "bilgi"), m.get("musteri_segmenti", "bireysel"),
            ",".join(m.get("urun_kategorileri", [])),
            oran, oran_kaynak,
            t_min, t_max,
            vade, vade,
            taksit, taksit,
            tahsis, masraf,
            m.get("belge_turu", "bilgi"), odul, indirim, puan,
            m.get("kampanya_baslangic"), m.get("kampanya_bitis"),
            f"{m.get('kampanya_baslangic','')} - {m.get('kampanya_bitis','')}".strip(" -"),
            t[:400],
            hedef_kitle_str, ym, mm, maas, kobi,
            m.get("gecerlilik_durumu", "aktif"), m.get("sektor", ""),
            ",".join(m.get("anahtar_kelimeler", [])), m.get("kaynak_url", ""),
            m.get("karakter_sayisi", len(t)), m.get("rag_oncelik", "normal")
        )

    eklenen_csv = 0
    for idx, cr in enumerate(csv_records):
        baslik = cr["baslik"]
        banka_kodu, banka_adi = banka_bilgisi(cr["banka_adi"])
        fd = cr["finansal"]
        t = cr["metin"]
        
        zaten_var = False
        for did, r_val in islenen_kayitlar.items():
            if fold(baslik) in fold(r_val[3]) or fold(r_val[3]) in fold(baslik):
                zaten_var = True
                break
        if zaten_var: continue

        new_did = f"{banka_kodu}__csv_{idx:04d}"
        oran, oran_kaynak = kar_payi_cikar(t, fd.get("kar_payi"))
        vade = vade_cikar(t, fd.get("vade"))
        taksit = taksit_cikar(t)
        t_min, t_max = tutar_cikar(t, fd.get("min_tutar"), fd.get("max_tutar"))
        tahsis, masraf = tahsis_masraf_cikar(t, fd.get("masraf_durumu"))
        odul, indirim, puan = odul_indirim_puan_cikar(t, fd.get("odul_fayda"))
        
        kitle_raw = fd.get("hedef_kitle") or "Genel"
        hedef_kitle_str, ym, mm, maas, kobi = hedef_kitle_coz(kitle_raw, t)

        u_tip = tespit_urun_tipi(baslik, t)
        
        b_tarih = fd.get("baslangic_tarihi")
        bit_tarih = fd.get("bitis_tarihi")
        suresi = f"{b_tarih or ''} - {bit_tarih or ''}".strip(" -")
        
        gecerlilik = "aktif"
        if bit_tarih and bit_tarih < "2026-08-01":
            gecerlilik = "suresi_dolmus"

        islenen_kayitlar[new_did] = (
            new_did, banka_kodu, banka_adi, baslik,
            u_tip, cr.get("kampanya_turu", "kampanya"), "bireysel",
            cr.get("kampanya_turu", ""),
            oran, oran_kaynak,
            t_min, t_max,
            vade, vade,
            taksit, taksit,
            tahsis, masraf,
            cr.get("kampanya_turu", "kampanya"), odul, indirim, puan,
            b_tarih, bit_tarih, suresi,
            t[:400],
            hedef_kitle_str, ym, mm, maas, kobi,
            gecerlilik, "",
            "", "", len(t), "normal"
        )
        eklenen_csv += 1

    rows = list(islenen_kayitlar.values())
    con.executemany(f"INSERT INTO urunler VALUES({','.join('?'*len(rows[0]))})", rows)
    
    for c in ["banka_kodu", "urun_tipi", "belge_turu", "gecerlilik", "kampanya_bitis", "hedef_kitle"]:
        con.execute(f"CREATE INDEX IF NOT EXISTS idx_{c} ON urunler({c})")
    con.commit()

    print(f"katilim.db basariyla olusturuldu! Toplam kayit: {len(rows)} (CSV'den yeni eklenen: {eklenen_csv})")
    
    q = lambda s: con.execute(s).fetchall()
    print("\n--- DOLULUK ORANLARI ---")
    alanlar = ["kar_payi_orani", "vade_ay_max", "taksit_max", "tutar_max", "tahsis_ucreti", "masraf_bilgisi", "odul_miktari", "indirim_orani", "alisveris_puani", "hedef_kitle"]
    for al in alanlar:
        n = q(f"SELECT COUNT({al}) FROM urunler WHERE {al} IS NOT NULL AND {al} != ''")[0][0]
        print(f"  {al:22s}: {n:4d} / {len(rows)} (%{100*n/len(rows):.1f})")

    print("\n--- BANKALARA GORE FINANSMAN VE KAR PAYI DURUMU ---")
    for r in q("""SELECT banka_adi, 
                  COUNT(*) toplam, 
                  COUNT(kar_payi_orani) kar_sayisi,
                  COUNT(vade_ay_max) vade_sayisi,
                  COUNT(tutar_max) tutar_sayisi
                  FROM urunler GROUP BY banka_kodu"""):
        print(f"  {r[0][:30]:32s} | Toplam: {r[1]:3d} | Kâr Payı: {r[2]:2d} | Vade: {r[3]:3d} | Tutar: {r[4]:3d}")

    con.close()

if __name__ == "__main__":
    main()
