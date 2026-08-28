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
    "tutar_max": r"tutar|limit|ne kadar|azami|en fazla para",
    "taksit_max": r"taksit",
}
# yon: siralama/karsilastirma sinyali -> SQL yolu
SIRALAMA = (r"en (uzun|kisa|yuksek|dusuk|iyi|fazla|az|avantajli|ucuz)|hangi banka|en cok|siralama|"
            r"kiyasla|karsilastir|karsilastirma|daha (cok|fazla|az|yuksek|dusuk|uzun|kisa|avantajli|iyi)|hangisinde daha")
OZNITELIK_BIRIM = r"(?:taksit|ay\b|yil|gun|tl\b|lira|puan|kat\b|kez|indirim|hediye|iade|oran)"
SAYMA    = (r"\bkac\b(?!\s*" + OZNITELIK_BIRIM + r")|sayisi ne|sayisi|toplam\s+\w*\s*kac|"
            r"listele|hepsini|tumunu|neler var|sirala|goster|daha (cok|fazla|az)|hangisinde daha")
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

def ozel_isim_var(q: str) -> bool:
    """Sozlukte karsiligi olmayan bir ozel isim (marka/magaza) var mi?"""
    for w in re.findall(r"\b[A-ZÇĞİÖŞÜ][\wçğıöşü’']{2,}", q):
        f = re.split(r"[’']", fold(w))[0]
        if not any(f.startswith(b) or b.startswith(f) for b in BILINEN if len(b) >= 3):
            return True
    return False


BAGLAM_IPUCU = r"\b(peki|peki ya|bunu|bunun|bununla|onun|onunkini|bunda|hangisi|karsilastir|kiyasla|digeri|diger|orada|oradaki|farki ne|farklar|avantaji ne|sartlari ne|kosullari ne|kimler|nasil alinir|nasil|mantikli|uygun|hangisini)\b"


def soruyu_coz(q: str, gecmis: list[dict] | None = None) -> dict:
    """Sorudan yapilandirilmis slotlari cikarir; varsa sadece gercek takip sorularinda baglami birlestirir."""
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
        "kiyas": is_kiyas,
        "sayma": bool(re.search(SAYMA, f)) and not re.search(METRIK_SORUSU, f),
        "_ham_metrik": bool(re.search(METRIK_SORUSU, f)),
        "metrik_sorusu": bool(re.search(METRIK_SORUSU, f)),
        "ozel_isim": ozel_isim_var(q),
        "aciklama": bool(re.search(ACIKLAMA, f)),
        "kampanya": is_kampanya,
        "arama_metni": q,
    }

    if gecmis:
        # Yalnizca en son kullanici sorusunu baz al (gecmisi corba yapma)
        onceki_sorular = [
            m.get("icerik") or m.get("content") or ""
            for m in gecmis
            if m.get("rol") in ("kul", "user") or m.get("role") == "user"
        ]
        if onceki_sorular:
            son_soru = onceki_sorular[-1]
            son_banks = bankalari_bul(son_soru)
            son_prods = urunleri_bul(son_soru)
            son_metrics = metrik_bul(son_soru)

            has_baglam_cue = bool(re.search(BAGLAM_IPUCU, f))

            # 1. Banka Cozumleme
            if curr_banks:
                # Kullanici acikca banka adi verdiyse:
                # Eger "bunu X ile karsilastir" gibi zamirli karsilastirma varsa onceki bankayi ekle
                if is_kiyas and (has_baglam_cue or bool(re.search(r"\b(bunu|bununla|onunla)\b", f))):
                    for b in son_banks:
                        if b not in slot["bankalar"]:
                            slot["bankalar"].append(b)
                    slot["kiyas"] = True
                # Aksi halde soru yeni bir banka hakkindadir, sadece mevcut bankayi kullan (gecmis bankayi sil)!
            else:
                # Kullanici soru cumlesinde hic banka belirtmediyse:
                if has_baglam_cue or son_banks:
                    slot["bankalar"] = list(son_banks)
                    if is_kiyas:
                        slot["kiyas"] = True

            # 2. Urun Cozumleme
            if not curr_prods and not is_kampanya:
                # Kullanici genel kampanya sormuyorsa ve urun belirtmediyse onceki urunu devral
                if has_baglam_cue or (not curr_banks and son_prods):
                    slot["urunler"] = list(son_prods)

            # 3. Metrik Cozumleme
            if not curr_metrics and has_baglam_cue and son_metrics:
                slot["metrikler"] = list(son_metrics)

            # 4. Arama Metni Zenginlestirme (yalnizca baglamli sorularda)
            if has_baglam_cue or not curr_banks:
                ekstra = [b.replace("_", " ") for b in slot["bankalar"]] + [u.replace("_", " ") for u in slot["urunler"]]
                if ekstra:
                    slot["arama_metni"] = f"{' '.join(dict.fromkeys(ekstra))} {q}".strip()

    return slot
