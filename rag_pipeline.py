# -*- coding: utf-8 -*-
"""
ham_veri.csv -> RAG-ready JSON/JSONL
Katilim bankalari web icerigi icin temizleme + metadata cikarimi + chunking pipeline.
"""
import pandas as pd, re, json, hashlib, unicodedata, collections
from datetime import datetime, date
from urllib.parse import urlparse


IN = "veri/ham_veri.csv"
OUTDIR = "veri"
TODAY = date.today()

#BANKA NORMALIZASYONU
BANK_MAP = {
    "kuveyt turk": ("Kuveyt Türk Katılım Bankası A.Ş.", "kuveyt_turk"),
    "kuveyt turk katilim bankasi a.s.": ("Kuveyt Türk Katılım Bankası A.Ş.", "kuveyt_turk"),
    "ziraat katilim": ("Ziraat Katılım Bankası A.Ş.", "ziraat_katilim"),
    "ziraat katilim bankasi a.s.": ("Ziraat Katılım Bankası A.Ş.", "ziraat_katilim"),
    "albaraka turk": ("Albaraka Türk Katılım Bankası A.Ş.", "albaraka"),
    "albaraka turk katilim bankasi a.s.": ("Albaraka Türk Katılım Bankası A.Ş.", "albaraka"),
    "turkiye finans": ("Türkiye Finans Katılım Bankası A.Ş.", "turkiye_finans"),
    "vakif katilim": ("Vakıf Katılım Bankası A.Ş.", "vakif_katilim"),
    "vakif katilim bankasi a.s.": ("Vakıf Katılım Bankası A.Ş.", "vakif_katilim"),
    "turkiye emlak katilim": ("Türkiye Emlak Katılım Bankası A.Ş.", "emlak_katilim"),
    "emlak katilim": ("Türkiye Emlak Katılım Bankası A.Ş.", "emlak_katilim"),
    "hayat finans": ("Hayat Finans Katılım Bankası A.Ş.", "hayat_finans"),
    "hayat finans katilim bankasi a.s.": ("Hayat Finans Katılım Bankası A.Ş.", "hayat_finans"),
    "tom bank": ("T.O.M. Katılım Bankası A.Ş.", "tom_katilim"),
    "tom katilim": ("T.O.M. Katılım Bankası A.Ş.", "tom_katilim"),
    "t.o.m. katilim bankasi a.s.": ("T.O.M. Katılım Bankası A.Ş.", "tom_katilim"),
    "dunya katilim": ("Dünya Katılım Bankası A.Ş.", "dunya_katilim"),
    "adil katilim bankasi": ("Adil Katılım Bankası A.Ş.", "adil_katilim"),
}
DOMAIN_MAP = {
    "kuveytturk.com.tr": "kuveyt_turk", "ziraatkatilim.com.tr": "ziraat_katilim",
    "albaraka.com.tr": "albaraka", "albarakaturk.com.tr": "albaraka",
    "turkiyefinans.com.tr": "turkiye_finans", "vakifkatilim.com.tr": "vakif_katilim",
    "emlakkatilim.com.tr": "emlak_katilim", "hayatfinans.com.tr": "hayat_finans",
    "tombank.com.tr": "tom_katilim", "dunyakatilim.com.tr": "dunya_katilim",
    "adilkatilim.com.tr": "adil_katilim",
}

def tr_fold(s):
    s = str(s).replace("İ", "i").replace("I", "ı").lower()
    s = s.replace("ı", "i").replace("ş", "s").replace("ğ", "g")
    s = s.replace("ü", "u").replace("ö", "o").replace("ç", "c")
    return unicodedata.normalize("NFKC", s).strip()

def normalize_bank(raw, url):
    host = urlparse(url).netloc.lower().replace("www.", "")
    key = tr_fold(raw)
    if key in BANK_MAP:
        name, code = BANK_MAP[key]
    else:
        name, code = str(raw).strip(), tr_fold(raw).replace(" ", "_")
    # domain otoritedir (crawl'da banka_adi yanlis atanmis olabilir)
    if host in DOMAIN_MAP and DOMAIN_MAP[host] != code:
        code = DOMAIN_MAP[host]
        name = next(v[0] for v in BANK_MAP.values() if v[1] == code)
    return name, code, host

#METIN TEMIZLEME
UI_NOISE = {
    "detaylı bilgi", "devam ediyor", "kampanya detayları", "bu bağlantı yeni sekmede açılacak.",
    "site haritası", "bilgi toplumu hizmetleri", "tümünü gör", "hemen başvur", "başvur",
    "daha fazla", "tıklayın", "hemen tıklayın", "arşiv", "tüm kampanyalar", "kampanyalar",
    "ana sayfa", "iletişim", "sıkça sorulan sorular", "çerez politikası", "kvkk",
    "müşteri ol", "detaylar", "devamı", "geri dön", "paylaş", "yazdır",
}
UI_PATTERNS = re.compile(
    r"(?i)\b(detaylı bilgi|hemen başvur|hemen tıkla(?:yın)?|başvur(?:un)?\s*[»>]?|tümünü gör|"
    r"daha fazla bilgi|bu bağlantı yeni sekmede açılacak\.?|devam ediyor|site haritası|"
    r"bilgi toplumu hizmetleri|çerez politikası|yukarı çık|paylaş)\b[\s.:|-]*")

def clean_text(t):
    t = str(t)
    t = t.replace("\xa0", " ").replace("\u200b", "")
    t = re.sub(r"\s*\|\s*", " ", t)                    # pipe ayirici -> bosluk
    t = re.sub(r"\b(\d{1,2})\s+([A-ZÇĞİÖŞÜ][\wçğıöşü]+ ve [A-ZÇĞİÖŞÜ])", r"\2", t)  # "3 Market ve G.." menu sayaci
    t = re.sub(r"(.{15,80}?)\1{1,}", r"\1", t)          # bitisik tekrar eden basliklar
    t = UI_PATTERNS.sub(" ", t)
    t = re.sub(r"\s{2,}", " ", t)
    return t.strip()

def strip_nav(t, nav_set):
    # cok kisa, nokta ile bitmeyen ve corpus genelinde tekrar eden nav parcalarini at
    parts = re.split(r"(?<=[.!?:])\s+", t)
    keep = [p for p in parts if not (len(p) < 70 and tr_fold(p).rstrip(".") in nav_set)]
    return re.sub(r"\s{2,}", " ", " ".join(keep)).strip()

def build_nav_set(texts):
    c = collections.Counter()
    for t in texts:
        segs = {tr_fold(s).rstrip(".") for s in re.split(r"(?<=[.!?:])\s+", t) if 3 < len(s) < 70}
        c.update(segs)
    n = len(texts)
    auto = {s for s, k in c.items() if k > max(25, n * 0.04) and not s.endswith(".")}
    return auto | UI_NOISE

# ---------------------------------------------------------------- 3) URL'DEN METADATA
SEGMENT_RULES = [
    (r"/bireysel|kendim-icin|/tr-tr/bireysel|/kisisel", "bireysel"),
    (r"/kobi|isim-icin|/isletme|/ticari-ve-kurumsal|/ticari|/kurumsal", "ticari"),
    (r"/tarim|/ciftci", "tarim"),
]
DOCTYPE_RULES = [
    (r"kampanya|kampanyalar|/firsat", "kampanya"),
    (r"\.pdf$|sozlesme|bilgilendirme-formu|urun-bilgi|form", "sozlesme_form"),
    (r"sikca-sorulan|/sss|yardim", "sss"),
    (r"hakkimizda|yatirimci-iliskileri|surdurulebilirlik|basin|kariyer|/kurumsal-yonetim", "kurumsal_bilgi"),
]
CATEGORY_RULES = {
    "finansman": r"finansman|kredi|leasing",
    "kart": r"\bkart|bankkart|paraf|world\b|troy\b|on-odemeli",
    "katilma_hesabi": r"katilma[ -]hesab|katilim[ -]hesab|\bhesap|birikim|altin bankaci|altin-bankaci",
    "yatirim": r"yatirim|\bfon\b|sermaye piyasa|sermaye-piyasa|hisse|kiymetli maden|sukuk|kira sertifika",
    "sigorta": r"sigorta|emeklilik|\bbes\b",
    "dijital_bankacilik": r"\bmobil\b|internet sube|internet-sube|dijital|\bqr\b|\batm\b|\bsube\b",
    "odeme_hizmetleri": r"\bodeme|transfer|\beft\b|havale|fatura|tahsilat|\bpos\b|nakit yonetimi|nakit-yonetimi",
    "dis_ticaret": r"dis ticaret|dis-ticaret|akreditif|ithalat|ihracat|teminat mektub",
}
KEYWORD_RULES = {
    "taksit": r"\btaksit", "vade_farksiz": r"vade\s*farksız", "puan_iade": r"worldpuan|parafpara|bankkart lira|puan",
    "erteleme": r"erteleme|sonra öde|ödemesiz dönem", "faizsiz": r"faizsiz|kâr payı|kar payı|katılım",
    "indirim": r"indirim|iade", "genclere_ozel": r"genç|öğrenci", "kadin_girisimci": r"kadın girişimci",
    "surdurulebilir": r"sürdürülebilir|yeşil|çevre dostu|elektrikli araç|ges\b",
}

def from_url(url):
    u = url.lower()
    seg = next((v for p, v in SEGMENT_RULES if re.search(p, u)), "genel")
    dt = next((v for p, v in DOCTYPE_RULES if re.search(p, u)), None)
    cats = [k for k, p in CATEGORY_RULES.items() if re.search(p, u)]
    slug = urlparse(u).path.rstrip("/").split("/")[-1] or "anasayfa"
    slug = re.sub(r"\.(aspx|html?|php|pdf)$", "", slug)
    return seg, dt, cats, slug

# ---------------------------------------------------------------- 4) METINDEN VARLIK CIKARIMI
AYLAR = {"ocak":1,"şubat":2,"subat":2,"mart":3,"nisan":4,"mayıs":5,"mayis":5,"haziran":6,"temmuz":7,
         "ağustos":8,"agustos":8,"eylül":9,"eylul":9,"ekim":10,"kasım":11,"kasim":12 if False else 11,"aralık":12,"aralik":12}

def _d(y, m, d):
    try:
        dt = date(int(y), int(m), int(d))
        # makul aralik disi tarih = kaynak hatasi veya yanlis yakalama
        return dt.isoformat() if 2015 <= dt.year <= 2035 else None
    except Exception:
        return None

def parse_dates(t):
    tl = t.lower()
    out = {"baslangic": None, "bitis": None}
    m = re.search(r"(\d{1,2})[-./](\d{1,2})[-./](\d{4})\s*[-–]\s*(\d{1,2})[-./](\d{1,2})[-./](\d{4})", tl)
    if m:
        out["baslangic"] = _d(m.group(3), m.group(2), m.group(1))
        out["bitis"] = _d(m.group(6), m.group(5), m.group(4))
        return out
    m = re.search(r"(\d{1,2})\s+([a-zçğıöşü]+)\s+(\d{4})\s*[-–]\s*(\d{1,2})\s+([a-zçğıöşü]+)\s+(\d{4})", tl)
    if m and m.group(2) in AYLAR and m.group(5) in AYLAR:
        out["baslangic"] = _d(m.group(3), AYLAR[m.group(2)], m.group(1))
        out["bitis"] = _d(m.group(6), AYLAR[m.group(5)], m.group(4))
        return out
    m = re.search(r"(?:son gün|bitiş tarihi|son tarih)\s*:?\s*(\d{1,2})[-./](\d{1,2})[-./](\d{4})", tl)
    if m:
        out["bitis"] = _d(m.group(3), m.group(2), m.group(1)); return out
    m = re.search(r"(?:bitiş tarihi\s*:?|son(?:una)? kadar|kadar geçerli|tarihine kadar)\D{0,25}?(\d{1,2})\s+([a-zçğıöşü]+)\s+(\d{4})", tl) \
        or re.search(r"(\d{1,2})\s+([a-zçğıöşü]+)\s+(\d{4})\s+tarihine kadar", tl) \
        or re.search(r"bitiş tarihi\s*:?\s*(\d{1,2})\s+([a-zçğıöşü]+)\s+(\d{4})", tl)
    if m and m.group(2) in AYLAR:
        out["bitis"] = _d(m.group(3), AYLAR[m.group(2)], m.group(1))
    return out

def durum(dates):
    b = dates.get("bitis")
    if not b: return "bilinmiyor"
    return "aktif" if date.fromisoformat(b) >= TODAY else "suresi_dolmus"

def parse_numeric(t):
    vade = sorted({int(x) for x in re.findall(r"(\d{1,3})\s*ay(?:a| |'|’|\b)", t.lower()) if 0 < int(x) <= 240})
    taksit = sorted({int(x) for x in re.findall(r"(\d{1,2})\s*taksit", t.lower()) if 0 < int(x) <= 36})
    tutar = []
    for x in re.findall(r"([\d.]{1,12}(?:,\d+)?)\s*(?:tl|₺)", t.lower()):
        try: tutar.append(float(x.replace(".", "").replace(",", ".")))
        except Exception: pass
    oran = []
    for x in re.findall(r"%\s*([\d,\.]{1,6})", t):
        try: oran.append(float(x.replace(",", ".")))
        except Exception: pass
    return {"vade_ay": vade[:8], "taksit_sayisi": taksit[:8],
            "tutarlar_tl": sorted(set(tutar))[:10], "oranlar_yuzde": sorted(set(oran))[:10]}

def parse_sector(t):
    m = re.search(r"Sektör\s*:\s*([^.\n]{3,60})", t)
    return m.group(1).strip() if m else None

def is_listing(t):
    """Kategori/liste sayfasi mi? Ayni baslik defalarca tekrar ediyorsa tekil belge degildir."""
    segs = [x.strip() for x in re.split(r"(?<=[.!?])\s+|\s{2,}", t) if 25 < len(x.strip()) < 120]
    if len(segs) < 6:
        return False
    c = collections.Counter(tr_fold(x) for x in segs)
    tekrar_orani = sum(v - 1 for v in c.values()) / len(segs)
    return tekrar_orani > 0.35 or len(re.findall(r"(?i)son gün|detaylar\b", t)) >= 5

def parse_keywords(t):
    tl = t.lower()
    return [k for k, p in KEYWORD_RULES.items() if re.search(p, tl)]

def guess_title(t, slug):
    t = t.strip()
    first = re.split(r"(?<=[.!?])\s", t)[0]
    if 10 <= len(first) <= 120:
        return first.strip(" .")
    words = [w.capitalize() for w in re.split(r"[-_]", slug) if w]
    return " ".join(words)[:120] or first[:120]

def cat_from_text(t):
    tl = tr_fold(t)
    return [k for k, p in CATEGORY_RULES.items() if re.search(p, tl)]

#CHUNKING
MAX_CH, OVER, MIN_CH = 1100, 180, 250

def chunk(text):
    sents = re.split(r"(?<=[.!?])\s+", text)
    chunks, cur = [], ""
    for s in sents:
        if len(cur) + len(s) + 1 <= MAX_CH:
            cur = (cur + " " + s).strip()
        else:
            if cur: chunks.append(cur)
            tail = cur[-OVER:]
            tail = tail[tail.find(" ") + 1:] if " " in tail else tail
            cur = (tail + " " + s).strip() if cur else s
            while len(cur) > MAX_CH:                     # tek cumle cok uzunsa sert kes
                chunks.append(cur[:MAX_CH]); cur = cur[MAX_CH - OVER:]
    if cur: chunks.append(cur)
    if len(chunks) > 1 and len(chunks[-1]) < MIN_CH:     # kucuk kuyrugu onceki chunk'a birlestir
        chunks[-2] = (chunks[-2] + " " + chunks[-1])[: MAX_CH + MIN_CH]; chunks.pop()
    return chunks or [text]

#PIPELINE
def main():
    df = pd.read_csv(IN)
    df["ham_metin"] = df["ham_metin"].astype(str)
    cleaned = [clean_text(t) for t in df["ham_metin"]]
    nav = build_nav_set(cleaned)

    docs, chunks_out, seen = [], [], {}
    stats = collections.Counter()

    for i, row in df.iterrows():
        url = str(row["kaynak_url"]).strip()
        text = strip_nav(cleaned[i], nav)
        if len(text) < 120:
            stats["atlandi_kisa"] += 1
            continue

        h = hashlib.sha1(re.sub(r"\W+", "", tr_fold(text)).encode()).hexdigest()[:16]
        if h in seen:                                    # icerik tekrari -> alternatif url olarak kaydet
            docs[seen[h]]["metadata"]["alternatif_urller"].append(url)
            stats["tekrar_birlestirildi"] += 1
            continue

        bank_name, bank_code, host = normalize_bank(row["banka_adi"], url)
        seg, dt_url, cats_url, slug = from_url(url)
        dates = parse_dates(text)
        cats = sorted(set(cats_url) | set(cat_from_text(text[:600]))) or ["genel"]
        doctype = dt_url or ("kampanya" if (dates["bitis"] or "kampanya" in tr_fold(text[:300])) else "urun_hizmet")
        if is_listing(text):
            doctype = "liste_sayfasi"      # RAG'de dusuk oncelik: tekil bilgi tasimaz, link listesidir
        title = guess_title(text, slug)
        num = parse_numeric(text)
        kws = parse_keywords(text)
        doc_id = f"{bank_code}__{h}"

        meta = {
            "banka_adi": bank_name, "banka_kodu": bank_code, "kaynak_url": url,
            "alternatif_urller": [], "domain": host, "baslik": title, "slug": slug,
            "belge_turu": doctype, "musteri_segmenti": seg, "urun_kategorileri": cats,
            "anahtar_kelimeler": kws, "sektor": parse_sector(text),
            "kampanya_baslangic": dates["baslangic"], "kampanya_bitis": dates["bitis"],
            "gecerlilik_durumu": durum(dates) if doctype == "kampanya" else ("yok" if doctype == "liste_sayfasi" else "surekli"),
            "rag_oncelik": "dusuk" if doctype == "liste_sayfasi" else "normal",
            "sayisal_bilgiler": num, "dil": "tr",
            "karakter_sayisi": len(text), "tahmini_token": round(len(text) / 3.4),
            "icerik_hash": h, "islenme_tarihi": TODAY.isoformat(), "kaynak_dosya": "ham_veri.csv",
        }
        seen[h] = len(docs)
        docs.append({"doc_id": doc_id, "content": text, "metadata": meta})
        stats["belge"] += 1

    # chunk'lama + embedding metni
    for d in docs:
        parts = chunk(d["content"])
        for ci, c in enumerate(parts):
            m = dict(d["metadata"])
            m.update({"chunk_index": ci, "chunk_sayisi": len(parts),
                      "karakter_sayisi": len(c), "tahmini_token": round(len(c) / 3.4)})
            ctx = (f"[{m['banka_adi']}] [{m['belge_turu']}] [{m['musteri_segmenti']}] "
                   f"[{', '.join(m['urun_kategorileri'])}] {m['baslik']}")
            chunks_out.append({
                "chunk_id": f"{d['doc_id']}__c{ci:02d}", "doc_id": d["doc_id"],
                "content": c, "embedding_text": f"{ctx}\n\n{c}", "metadata": m,
            })
        stats["chunk"] += len(parts)

    with open(f"{OUTDIR}/rag_chunks.jsonl", "w", encoding="utf-8") as f:
        for c in chunks_out: f.write(json.dumps(c, ensure_ascii=False) + "\n")
    with open(f"{OUTDIR}/rag_documents.json", "w", encoding="utf-8") as f:
        json.dump(docs, f, ensure_ascii=False, indent=2)

    ozet = {
        "kaynak_satir": len(df), "islenen_belge": stats["belge"], "toplam_chunk": stats["chunk"],
        "atlanan_kisa": stats["atlandi_kisa"], "tekrar_birlestirilen": stats["tekrar_birlestirildi"],
        "banka_dagilimi": dict(collections.Counter(d["metadata"]["banka_adi"] for d in docs)),
        "belge_turu_dagilimi": dict(collections.Counter(d["metadata"]["belge_turu"] for d in docs)),
        "segment_dagilimi": dict(collections.Counter(d["metadata"]["musteri_segmenti"] for d in docs)),
        "kategori_dagilimi": dict(collections.Counter(k for d in docs for k in d["metadata"]["urun_kategorileri"])),
        "kampanya_durumu": dict(collections.Counter(d["metadata"]["gecerlilik_durumu"] for d in docs)),
        "bitis_tarihi_yakalanan": sum(1 for d in docs if d["metadata"]["kampanya_bitis"]),
        "ort_chunk_karakter": round(sum(len(c["content"]) for c in chunks_out) / max(1, len(chunks_out))),
    }
    with open(f"{OUTDIR}/pipeline_ozet.json", "w", encoding="utf-8") as f:
        json.dump(ozet, f, ensure_ascii=False, indent=2)
    print(json.dumps(ozet, ensure_ascii=False, indent=2))

if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="ham veri CSV -> rag_chunks.jsonl")
    ap.add_argument("--girdi", default=IN, help="ham veri CSV yolu")
    ap.add_argument("--cikti", default=OUTDIR, help="cikti klasoru")
    ap.add_argument("--tarih", default=None, help="aktiflik referans tarihi (YYYY-AA-GG)")
    a = ap.parse_args()
    IN, OUTDIR = a.girdi, a.cikti
    if a.tarih:
        TODAY = date.fromisoformat(a.tarih)
    main()
