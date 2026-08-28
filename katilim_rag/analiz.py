# -*- coding: utf-8 -*-
"""Soru analizi: Turkce normalizasyon + slot (banka, urun, metrik, zaman) cikarimi.

Bu katman kural tabanli ve deterministik. LLM'e birakilmamasinin sebebi:
yonlendirme hatasi tum cevabi bozuyor, kural tabanli olan test edilebilir.
"""
import re, unicodedata
from .config import BANKALAR

def fold(s: str) -> str:
    s = str(s).replace("İ", "i").replace("I", "ı").lower()
    for a, b in [("ı", "i"), ("ş", "s"), ("ğ", "g"), ("ü", "u"), ("ö", "o"), ("ç", "c"), ("â", "a"), ("w", "v"), ("q", "k")]:
        s = s.replace(a, b)
    return unicodedata.normalize("NFKC", s)

BANKA_TAKMA = {
    "kuveyt_turk": ["kuveyt turk", "kuveytturk", "kuveyt tur", "kuveyt", "kuvey", "kuvey turk", "kt katilim", "kt"],
    "ziraat_katilim": ["ziraat katilim", "ziraat", "ziraatkatilim", "zk"],
    "albaraka": ["albaraka", "albaraka turk", "albarakaturk", "al baraka"],
    "turkiye_finans": ["turkiye finans", "turkiyefinans", "tf katilim", "tf"],
    "vakif_katilim": ["vakif katilim", "vakifkatilim", "vakif", "vk"],
    "emlak_katilim": ["emlak katilim", "emlakkatilim", "turkiye emlak", "emlak"],
    "hayat_finans": ["hayat finans", "hayatfinans", "hayat"],
    "tom_katilim": ["tom katilim", "tom bank", "tombank", "tom"],
    "dunya_katilim": ["dunya katilim", "dunyakatilim", "dunya"],
    "adil_katilim": ["adil katilim", "adilkatilim", "adil"],
    # BDDK faaliyet izni 26.02.2026 (RG 04.03.2026). Urun verisi henuz yok;
    # sistem adi tanisin diye eklendi. "iktisat" tek basina eslenmez (genel kelime).
    "iktisat_katilim": ["iktisat katilim", "iktisatkatilim", "iktisat bankasi"],
}
URUN_TAKMA = {
    "konut": ["konut", "mortgage", "ev kredisi", "konut finansman"],
    "arac": ["tasit", "otomobil", "motosiklet", "arac finansman"],
    "ihtiyac": ["ihtiyac finansman", "bireysel finansman"],
    "isyeri": ["isyeri finansman", "dukkan finansman", "ticari gayrimenkul"],
    "kobi_ticari": ["kobi finansman", "isletme finansman", "esnaf finansman"],
    "katilma_hesabi": ["katilma hesab", "vadeli hesap", "birikim hesab", "mevduat"],
    "kredi_karti": ["kredi kart", "bankkart", "paraf", "world kart", "troy kart"],
    "sigorta": ["sigorta", "emeklilik", "bes"],
    "yatirim_fonu": ["yatirim fonu", "portfoy"],
    "surdurulebilir": ["surdurulebilir finansman", "yesil finansman", "gunes enerji finansman"],
}

# metrik: hangi sayisal alan soruluyor
METRIK = {
    "vade_ay_max": r"vade|kac ay|en uzun|taksit sayis",
    "kar_payi_orani": r"kar pay|kâr pay|oran|getiri|faiz",
    # "azami" tek basina tutar degildir: "azami vade" sorusunda iki metrik
    # birden secilmesi grafik/siralama yolunu bozuyordu.
    "tutar_max": r"tutar|limit|ne kadar|azami (tutar|finansman)|en fazla para",
    "taksit_max": r"taksit",
}
# siralama YONU: kullanici "en yuksek" mi "en dusuk" mu istiyor?
# Not: "avantajli/iyi" bilinçli olarak eslenmedi — urune gore yonu degisir
# (finansmanda dusuk oran avantajli, katilma hesabinda yuksek getiri avantajli).
YON_YUKSEK = r"en (yuksek|fazla|cok|uzun)"
YON_DUSUK  = r"en (dusuk|az|ucuz|kisa)"

# harcama-esigi niyetleri (aralik_mantigi / guncellik sorulari)
TUTAR_TL = re.compile(r"(\d[\d.,]*)\s*tl")
TUTAR_ARALIK = re.compile(r"(\d[\d.,]*)\s*(?:tl)?\s*(?:-|–|ile)\s*(\d[\d.,]*)\s*tl\s*aras")
ESIK_VARMI = re.compile(r"kampanya var mi|kampanyalar (var mi|neler|hangileri)|hangi kampanyalar")

# tarih niyetleri (fold edilmis soruda; ay adlari fold sonrasi ascii'dir)
AY_NO = {"ocak":1,"subat":2,"mart":3,"nisan":4,"mayis":5,"haziran":6,"temmuz":7,
         "agustos":8,"eylul":9,"ekim":10,"kasim":11,"aralik":12}
TARIH_AY = re.compile(
    r"(ocak|subat|mart|nisan|mayis|haziran|temmuz|agustos|eylul|ekim|kasim|aralik)"
    r"(?:\s+(\d{4}))?.{0,15}?(sona er|bit)")
TARIH_GORELI = re.compile(r"(bu|onumuzdeki|gelecek) ay\w*.{0,12}?(sona er|bit)")
TARIH_NE_ZAMAN = re.compile(
    r"ne zaman (bitiyor|bitecek|sona eriyor|sona erecek)|son gunu ne|hangi tarih(te|e kadar)")


def tarih_ay_bul(f):
    from datetime import date
    m = TARIH_AY.search(f)
    if m:
        ay = AY_NO[m.group(1)]
        yil = int(m.group(2)) if m.group(2) else date.today().year
        return (yil, ay)
    m = TARIH_GORELI.search(f)
    if m:
        t = date.today()
        if m.group(1) == "bu":
            return (t.year, t.month)
        return (t.year + (1 if t.month == 12 else 0), 1 if t.month == 12 else t.month + 1)
    return None
ESIK_KATILIM = re.compile(r"hangi kampanya|kampanyalara (gir|katil)|girebilecegim|katilabilecegim|yararlanabilir")
KAZANC_SORUSU = re.compile(r"kazan|iade|indirim|odul|puan|ne alirim|ne verir|ne kazandirir")
ESIK_MIN = re.compile(r"en az kac tl|minimum kac tl|en dusuk kac tl")
ESIK_SORU = re.compile(r"esik (nedir|ne kadar|kac)|minimum harcama|asgari harcama|en az (ne kadar )?harcama")
ESIK_STOP = {"nedir", "kadar", "kampanya", "kampanyasinda", "kampanyanin", "minimum",
             "harcama", "esik", "esigi", "guncel", "katilim", "katilimin", "bankasi",
             "hangi", "olan", "icin", "sahip",
             "zaman", "tarihte", "tarihe", "bitiyor", "bitecek", "sona", "eriyor",
             "erecek", "gunu", "ayinda", "hangileri",
             "ocak", "subat", "mart", "nisan", "mayis", "haziran", "temmuz",
             "agustos", "eylul", "ekim", "kasim", "aralik"}


def esik_konulari(f: str, banka_kelimeleri: set) -> list:
    """Sorudan icerik kelimelerini cikarir (ör. 'akaryakit', 'giyim')."""
    out = []
    for k in re.findall(r"[a-z]{4,}", f):
        if k not in ESIK_STOP and k not in banka_kelimeleri and k not in out:
            out.append(k)
    return out[:3]


def yon_bul(f: str):
    if re.search(YON_YUKSEK, f):
        return "yuksek"
    if re.search(YON_DUSUK, f):
        return "dusuk"
    return None

# yon: siralama/karsilastirma sinyali -> SQL yolu
SIRALAMA = (r"en (uzun|kisa|yuksek|dusuk|iyi|fazla|az|avantajli|ucuz)|hangi banka|en cok|siralama|"
            r"kiyasla|karsilastir|karsilastirma|daha (cok|fazla|az|yuksek|dusuk|uzun|kisa|avantajli|iyi)|hangisinde daha")
OZNITELIK_BIRIM = r"(?:taksit|ay\b|yil|gun|tl\b|lira|puan|kat\b|kez|indirim|hediye|iade|oran)"
SAYMA    = (r"\bkac\b(?!\s*" + OZNITELIK_BIRIM + r")|sayisi ne|sayisi|toplam\s+\w*\s*kac|"
            r"listele|hepsini|tumunu|neler var|sirala|daha (cok|fazla|az)|hangisinde daha")
METRIK_SORUSU = (r"kac\s*" + OZNITELIK_BIRIM +
                 r"|ne kadar (indirim|iade|kazan|hediye|puan|para)")
ACIKLAMA = r"nedir|ne demek|nasil (islar|calisir|yapilir|kullanilir)|neden|acikla|anlat|fark(i| nedir)|kosul|sart|avantaj|gerekli belge"


def bankalari_bul(q: str):
    f = fold(q)
    bulunan = []
    for k, ads in BANKA_TAKMA.items():
        for a in ads:
            pat = r"\b" + re.escape(a) + r"\b" if len(a) <= 4 else re.escape(a)
            if re.search(pat, f):
                bulunan.append(k)
                break
    return bulunan


def urunleri_bul(q: str):
    f = fold(q)
    bulunan = []
    for k, ads in URUN_TAKMA.items():
        for a in ads:
            pat = r"\b" + re.escape(a) + r"\b" if len(a) <= 4 else re.escape(a)
            if re.search(pat, f):
                bulunan.append(k)
                break
    return bulunan


def metrik_bul(q: str):
    f = fold(q)
    return [k for k, p in METRIK.items() if re.search(p, f)]


def aktiflik_bul(q: str):
    f = fold(q)
    if re.search(r"aktif|devam eden|suren|gecerli|su an|guncel|hala", f):
        return "aktif"
    if re.search(r"biten|sona eren|suresi dolmus|gecmis|eski", f):
        return "suresi_dolmus"
    return None


# SQL tablosunda marka/magaza adi yok — bu bilgi kampanya metninde.
# Soruda taninmayan bir ozel isim varsa SQL yolu bos doner, RAG'e gitmeli.
BILINEN = set()
for _d in (BANKA_TAKMA, URUN_TAKMA):
    for _v in _d.values():
        BILINEN.update(w for a in _v for w in a.split())
BILINEN.update("""katilim banka bankasi bankalari hesap hesabi kampanya kampanyasi
kampanyalari finansman kart kredi taksit vade oran kar pay payi indirim iade
hangi hangisi kac ne kadar var mi nedir nasil neler en cok az uzun kisa yuksek
dusuk aktif gecerli su an hala bu bir ile ve veya icin ozel""".split())
BILINEN.update("""bana bize benim bizim lutfen rica ederim istiyorum isterim""".split())

def ozel_isim_var(q: str) -> bool:
    """Sozlukte karsiligi olmayan bir ozel isim (marka/magaza) var mi?"""
    for w in re.findall(r"\b[A-ZÇĞİÖŞÜ][\wçğıöşü’']{2,}", q):
        f = re.split(r"[’']", fold(w))[0]
        if not any(f.startswith(b) or b.startswith(f) for b in BILINEN if len(b) >= 3):
            return True
    return False


def soruyu_coz(q: str) -> dict:
    """Sorudan yapilandirilmis slotlari cikarir."""
    f = fold(q)
    curr_banks = bankalari_bul(q)
    curr_prods = urunleri_bul(q)
    curr_metrics = metrik_bul(q)
    is_kiyas = bool(re.search(r"karsilastir|kiyasla|farki ne|farklar|hangisi (daha|iyi|mantikli|uygun)|hangisini|yoksa|m[ıiuü] daha|daha (cok|fazla|az|iyi|yuksek|dusuk)", f))
    is_kampanya = bool(re.search(r"kampanya|firsat|indirim|promosyon|odul|puan", f))

    slot = {
        "soru": q,
        "bankalar": curr_banks,
        "urunler": curr_prods,
        "metrikler": curr_metrics,
        "aktiflik": aktiflik_bul(q),
        "siralama": bool(re.search(SIRALAMA, f)),
        "yon": yon_bul(f),
        "tutar_tl": (lambda m: float(m.group(1).replace(".", "").replace(",", "."))
                     if m else None)(TUTAR_TL.search(f)),
        "tutar_aralik": (lambda m: tuple(sorted(
            float(g.replace(".", "").replace(",", ".")) for g in m.groups()))
            if m else None)(TUTAR_ARALIK.search(f)),
        "esik_katilim": bool(ESIK_KATILIM.search(f) or ESIK_VARMI.search(f))
                        and not KAZANC_SORUSU.search(f),
        "esik_min": bool(ESIK_MIN.search(f)),
        "esik_soru": bool(ESIK_SORU.search(f)) and not KAZANC_SORUSU.search(f),
        "esik_konular": esik_konulari(f, BILINEN),
        "tarih_ay": tarih_ay_bul(f),
        "tarih_ne_zaman": bool(TARIH_NE_ZAMAN.search(f)),
        "kiyas": is_kiyas,
        "sayma": bool(re.search(SAYMA, f)) and not re.search(METRIK_SORUSU, f),
        "_ham_metrik": bool(re.search(METRIK_SORUSU, f)),
        "metrik_sorusu": bool(re.search(METRIK_SORUSU, f)),
        "ozel_isim": ozel_isim_var(q),
        "aciklama": bool(re.search(ACIKLAMA, f)),
        "kampanya": is_kampanya,
        "arama_metni": q,
    }

    return slot
