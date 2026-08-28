# -*- coding: utf-8 -*-
"""Yapilandirilmis sorgu katmani.

LLM'e serbest SQL yazdirmiyoruz — sablon + parametre kullaniyoruz.
Sebep: (1) SQL injection yok, (2) ayni soru hep ayni sorguyu uretir,
(3) test edilebilir. Bedeli: kaliplarin disina cikan soru RAG'e duser.
"""
import re, sqlite3
from typing import Any
from .config import kisa_ad, DB_YOLU, BANKALAR
from .analiz import soruyu_coz, fold

METRIK_ETIKET = {
    "vade_ay_max": ("vade", "ay"), "kar_payi_orani": ("kâr payı oranı", "%"),
    "tutar_max": ("tutar", "TL"), "taksit_max": ("taksit sayısı", ""),
}
URUN_ETIKET = {
    "konut": "konut finansmanı", "arac": "araç finansmanı", "ihtiyac": "ihtiyaç finansmanı",
    "isyeri": "işyeri finansmanı", "kobi_ticari": "KOBİ/ticari finansman",
    "katilma_hesabi": "katılma hesabı", "kredi_karti": "kredi kartı", "sigorta": "sigorta",
    "yatirim_fonu": "yatırım fonu", "surdurulebilir": "sürdürülebilir finansman",
}


def _con():
    c = sqlite3.connect(DB_YOLU)
    c.row_factory = sqlite3.Row
    return c


def _kosullar(slot) -> tuple[str, list]:
    k, p = ["1=1"], []
    if slot["bankalar"]:
        k.append(f"banka_kodu IN ({','.join('?' * len(slot['bankalar']))})")
        p += slot["bankalar"]
    if slot["urunler"]:
        k.append(f"urun_tipi IN ({','.join('?' * len(slot['urunler']))})")
        p += slot["urunler"]
    if slot["aktiflik"]:
        k.append("gecerlilik = ?")
        p.append(slot["aktiflik"])
    if slot["kampanya"]:
        k.append("belge_turu = 'kampanya'")
    k.append("belge_turu != 'liste_sayfasi'")
    return " AND ".join(k), p


def siralama_sorgusu(slot) -> dict[str, Any] | None:
    """'En uzun vadeli konut finansmanı hangi bankada' tipi sorular."""
    metrik = slot["metrikler"][0] if slot["metrikler"] else "vade_ay_max"
    if metrik not in METRIK_ETIKET:
        return None
    # --- siralama yonu ---
    # Kullanicinin acik yon kelimesi ("en yuksek" / "en dusuk") her seyi ezer.
    # Yon belirtilmemisse metrik varsayilani: kar payinda dusuk iyidir (finansman),
    # ISTISNA: katilma hesabi / yatirimda yuksek getiri iyidir.
    # Metrik sorudan TESPIT EDILEMEDIYSE (vade'ye dusulduyse) yon kelimesine
    # bakilmaz — tahmin edilmis metrigin yonunu cevirmek cevabi daha da bozar.
    yon = slot.get("yon") if slot["metrikler"] else None
    if metrik == "kar_payi_orani":
        artan = True                             # varsayilan: dusuk oran iyidir
        if yon == "yuksek":
            artan = False
        elif yon is None and set(slot["urunler"]) & {"katilma_hesabi", "yatirim_fonu"}:
            artan = False                        # getiri urunlerinde yuksek iyidir
    else:
        artan = (yon == "dusuk")                 # vade/tutar/taksit varsayilani: buyuk
    kosul, par = _kosullar(slot)
    sql = (f"SELECT banka_adi, urun_tipi, baslik, {metrik} AS deger, "
           f"kar_payi_orani, tutar_max, vade_ay_max, taksit_max, tahsis_ucreti, masraf_bilgisi, "
           f"kampanya_turu, odul_miktari, indirim_orani, alisveris_puani, kampanya_suresi, kampanya_kosullari, "
           f"hedef_kitle, yeni_musteri, mevcut_musteri, maas_musterisi, kobi_esnaf, kaynak_url "
           f"FROM urunler WHERE {kosul} AND {metrik} IS NOT NULL "
           f"ORDER BY deger {'ASC' if artan else 'DESC'} LIMIT 50")
    with _con() as c:
        satir = [dict(r) for r in c.execute(sql, par)]
    ad, birim = METRIK_ETIKET[metrik]
    return {"tip": "siralama", "metrik": metrik, "metrik_adi": ad, "birim": birim,
            "artan": artan, "sql": sql, "parametre": par, "satirlar": satir}


def sayma_sorgusu(slot) -> dict[str, Any]:
    """Sayım, banka kampanya dağılımı veya miktar kıyaslama sorguları."""
    kosul, par = _kosullar(slot)
    with _con() as c:
        toplam = c.execute(f"SELECT COUNT(*) n FROM urunler WHERE {kosul}", par).fetchone()["n"]
        kirilim = [dict(r) for r in c.execute(
            f"SELECT banka_adi, banka_kodu, COUNT(*) n FROM urunler WHERE {kosul} "
            f"GROUP BY banka_kodu ORDER BY n DESC", par)]

        # Banka başına dengeli örnek çekelim (tek bir banka tüm listeyi kaplamasın)
        ornekler = []
        hedef_bankalar = slot["bankalar"] or [r["banka_kodu"] for r in kirilim[:6]]
        k_ek, p_ek = [], []
        if slot["aktiflik"]:
            k_ek.append("gecerlilik = ?")
            p_ek.append(slot["aktiflik"])
        if slot["kampanya"]:
            k_ek.append("belge_turu = 'kampanya'")
        k_ek.append("belge_turu != 'liste_sayfasi'")
        ek_kosul = " AND ".join(k_ek)
        for bk in hedef_bankalar:
            ornekler += [dict(r) for r in c.execute(
                f"SELECT banka_adi, baslik, urun_tipi, kar_payi_orani, tutar_max, vade_ay_max, taksit_max, "
                f"odul_miktari, indirim_orani, alisveris_puani, kampanya_suresi, kampanya_bitis, hedef_kitle, kaynak_url "
                f"FROM urunler WHERE banka_kodu = ? AND {ek_kosul} "
                f"ORDER BY kampanya_bitis DESC LIMIT 4", [bk] + p_ek)]

    return {"tip": "sayma", "toplam": toplam, "kirilim": kirilim, "ornekler": ornekler,
            "sql": f"SELECT COUNT(*) FROM urunler WHERE {kosul}", "parametre": par}


def karsilastirma_sorgusu(slot) -> dict[str, Any]:
    """'Kuveyt Türk ile Albaraka'nın konut finansmanını karşılaştır'."""
    kosul, par = _kosullar(slot)
    with _con() as c:
        satir = [dict(r) for r in c.execute(
            f"SELECT banka_adi, urun_tipi, MAX(vade_ay_max) vade, MIN(kar_payi_orani) oran, "
            f"MAX(tutar_max) tutar, GROUP_CONCAT(DISTINCT tahsis_ucreti) tahsis, "
            f"GROUP_CONCAT(DISTINCT masraf_bilgisi) masraf, "
            f"GROUP_CONCAT(DISTINCT kampanya_kosullari) kampanya_kosullari, "
            f"GROUP_CONCAT(DISTINCT hedef_kitle) hedef_kitle, COUNT(*) kayit "
            f"FROM urunler WHERE {kosul} "
            f"GROUP BY banka_kodu, urun_tipi ORDER BY banka_adi", par)]
    return {"tip": "karsilastirma", "satirlar": satir, "parametre": par}


AKTIF_SET = ("aktif", "surekli", "sürekli")
# Yonlendirme/arsiv basliklari kampanya degildir; esik cevaplarina sizmasin.
KOTU_BASLIK = re.compile(r"lutfen tiklayin|tum kampanyalar|guncel kampanyalarimiz|arsiv|kampanyalar listesi")


def esik_tekil_sorgusu(slot):
    """'Ziraat akaryakit kampanyasinda esik nedir' -> konu eslesmesi.

    Konu filtresi SQL LIKE ile DEGIL Python fold() ile yapilir: SQLite LIKE
    yalniz ASCII'de buyuk/kucuk duyarsizdir, 'Akaryakıt' icindeki 'ı' Turkce
    tuzagina duser. Aday kume kucuk oldugundan Python taramasi ucuzdur."""
    kosullar, par = ["esik_tutar IS NOT NULL", "belge_turu != 'liste_sayfasi'"], []
    if slot["bankalar"]:
        kosullar.append(f"banka_kodu IN ({','.join('?' * len(slot['bankalar']))})")
        par += slot["bankalar"]
    sql = ("SELECT banka_adi, baslik, kampanya_kosullari, esik_tutar, gecerlilik "
           f"FROM urunler WHERE {' AND '.join(kosullar)} ORDER BY esik_tutar ASC")
    with sqlite3.connect(DB_YOLU) as c:
        c.row_factory = sqlite3.Row
        adaylar = [dict(r) for r in c.execute(sql, par)]
    adaylar = [r for r in adaylar if not KOTU_BASLIK.search(fold(r["baslik"]))]
    konular = slot.get("esik_konular") or []
    if konular:
        # Once baslikta ara: kosullar alanina bazen site menusu sizdigi icin
        # (her konuyu tutar), baslik eslesmesi varsa yalniz onlar alinir.
        b_es = [r for r in adaylar if any(k in fold(r["baslik"]) for k in konular)]
        if b_es:
            adaylar = b_es
        else:
            adaylar = [r for r in adaylar
                       if any(k in fold(r["kampanya_kosullari"] or "") for k in konular)]
    if not adaylar:
        return None
    return {"tip": "esik_tekil", "satirlar": adaylar[:5]}


def esik_min_sorgusu(slot):
    """'En az kac TL ile yararlanirim' -> aktif setteki MIN esik + ornekler."""
    with sqlite3.connect(DB_YOLU) as c:
        c.row_factory = sqlite3.Row
        r = c.execute("SELECT MIN(esik_tutar) m FROM urunler WHERE esik_tutar IS NOT NULL "
                      f"AND gecerlilik IN {AKTIF_SET!r}").fetchone()
        if not r or r["m"] is None:
            return None
        ornekler = [dict(x) for x in c.execute(
            "SELECT banka_adi, baslik, esik_tutar FROM urunler WHERE esik_tutar = ? "
            f"AND gecerlilik IN {AKTIF_SET!r} LIMIT 2", (r["m"],))]
    return {"tip": "esik_min", "min": r["m"], "satirlar": ornekler}


def esik_liste_sorgusu(slot):
    """'12.000 TL ile hangi kampanyalara girerim' -> esik<=H aktif kampanyalar."""
    aralik = slot.get("tutar_aralik")
    if aralik:
        kosullar, par = ["esik_tutar IS NOT NULL", "esik_tutar BETWEEN ? AND ?",
                         "belge_turu != 'liste_sayfasi'",
                         f"gecerlilik IN {AKTIF_SET!r}"], list(aralik)
        h = aralik
    else:
        h = slot["tutar_tl"]
        kosullar, par = ["esik_tutar IS NOT NULL", "esik_tutar <= ?",
                         "belge_turu != 'liste_sayfasi'",
                         f"gecerlilik IN {AKTIF_SET!r}"], [h]
    if slot["bankalar"]:
        kosullar.append(f"banka_kodu IN ({','.join('?' * len(slot['bankalar']))})")
        par += slot["bankalar"]
    sql = ("SELECT banka_adi, baslik, esik_tutar FROM urunler "
           f"WHERE {' AND '.join(kosullar)} ORDER BY esik_tutar DESC LIMIT 8")
    with sqlite3.connect(DB_YOLU) as c:
        c.row_factory = sqlite3.Row
        satirlar = [dict(r) for r in c.execute(sql, par)
                    if not KOTU_BASLIK.search(fold(r["baslik"]))]
        genel_min = c.execute("SELECT MIN(esik_tutar) FROM urunler WHERE esik_tutar "
                              f"IS NOT NULL AND gecerlilik IN {AKTIF_SET!r}").fetchone()[0]
    if satirlar:
        return {"tip": "esik_liste", "tutar": h, "aralik": bool(aralik), "satirlar": satirlar}
    return {"tip": "esik_bos", "tutar": h, "aralik": bool(aralik),
            "genel_min": genel_min, "satirlar": []}


AY_ADI = {1:"Ocak",2:"Şubat",3:"Mart",4:"Nisan",5:"Mayıs",6:"Haziran",7:"Temmuz",
          8:"Ağustos",9:"Eylül",10:"Ekim",11:"Kasım",12:"Aralık"}


def _iso_tr(iso):
    y, m, d = iso.split("-")
    return f"{d}.{m}.{y}"


def tarih_ay_sorgusu(slot):
    yil, ay = slot["tarih_ay"]
    lo, hi = f"{yil:04d}-{ay:02d}-01", f"{yil:04d}-{ay:02d}-31"
    kosullar, par = ["bitis_tarihi BETWEEN ? AND ?", "belge_turu != 'liste_sayfasi'"], [lo, hi]
    if slot["bankalar"]:
        kosullar.append(f"banka_kodu IN ({','.join('?' * len(slot['bankalar']))})")
        par += slot["bankalar"]
    sql = ("SELECT banka_adi, baslik, bitis_tarihi FROM urunler "
           f"WHERE {' AND '.join(kosullar)} ORDER BY bitis_tarihi ASC LIMIT 8")
    with sqlite3.connect(DB_YOLU) as c:
        c.row_factory = sqlite3.Row
        satirlar = [dict(r) for r in c.execute(sql, par)
                    if not KOTU_BASLIK.search(fold(r["baslik"]))]
    tip = "tarih_liste" if satirlar else "tarih_bos"
    return {"tip": tip, "yil": yil, "ay": ay, "satirlar": satirlar}


def tarih_tekil_sorgusu(slot):
    """'X kampanyasi ne zaman bitiyor' -> konu/banka esleşmeli en guncel donem."""
    kosullar, par = ["bitis_tarihi IS NOT NULL", "belge_turu != 'liste_sayfasi'"], []
    if slot["bankalar"]:
        kosullar.append(f"banka_kodu IN ({','.join('?' * len(slot['bankalar']))})")
        par += slot["bankalar"]
    sql = ("SELECT banka_adi, baslik, kampanya_kosullari, bitis_tarihi, gecerlilik "
           f"FROM urunler WHERE {' AND '.join(kosullar)} ORDER BY bitis_tarihi DESC")
    with sqlite3.connect(DB_YOLU) as c:
        c.row_factory = sqlite3.Row
        adaylar = [dict(r) for r in c.execute(sql, par)
                   if not KOTU_BASLIK.search(fold(r["baslik"]))]
    konular = slot.get("esik_konular") or []
    if konular:
        b_es = [r for r in adaylar if any(k in fold(r["baslik"]) for k in konular)]
        adaylar = b_es or [r for r in adaylar
                           if any(k in fold(r["kampanya_kosullari"] or "") for k in konular)]
    if not adaylar:
        return None
    return {"tip": "tarih_tekil", "satirlar": adaylar[:3]}


def calistir(soru: str) -> dict[str, Any] | None:
    """Soruyu uygun sablona yonlendirir. Eslesme yoksa None -> RAG yoluna duser."""
    slot = soruyu_coz(soru)
    f = fold(soru)

    # SQL tablosu marka/magaza bazli kampanya detayi tutmuyor; bu sorular RAG'e ait.
    _esik_niyet = (slot.get("esik_katilim") or slot.get("esik_soru") or slot.get("esik_min")
                   or slot.get("tarih_ay") or slot.get("tarih_ne_zaman"))
    if slot.get("ozel_isim") and not (slot.get("kiyas") or len(slot["bankalar"]) >= 2
                                      or _esik_niyet):
        return None

    #  Harcama esigi sorulari (aralik_mantigi / guncellik) — deterministik.
    #    Katilim sorulari ("hangi kampanyalara girerim") aktif sete bakar;
    #    bilgi sorulari ("esik nedir") suresi dolmusu da kapsar, durumunu soyler.
    if slot.get("esik_soru") and (slot["bankalar"] or slot.get("esik_konular")):
        b = esik_tekil_sorgusu(slot)
        if b:
            return b | {"slot": slot}
        # eslesme yoksa RAG'e birak (mevcut davranis korunur)
    if slot.get("esik_min"):
        b = esik_min_sorgusu(slot)
        if b:
            return b | {"slot": slot}
    if slot.get("esik_katilim") and (slot.get("tutar_tl") or slot.get("tutar_aralik")):
        return esik_liste_sorgusu(slot) | {"slot": slot}
    if slot.get("tarih_ne_zaman") and (slot["bankalar"] or slot.get("esik_konular")):
        b = tarih_tekil_sorgusu(slot)
        if b:
            return b | {"slot": slot}
    if slot.get("tarih_ay"):
        return tarih_ay_sorgusu(slot) | {"slot": slot}

    # Kampanya ayrıntıları (ödül tutarı, hedef kitle, harcama koşulu vb.)
    # yapılandırılmış finansman sütunlarından güvenilir biçimde çıkarılamaz.
    # Sayım soruları aşağıdaki SQL yolunda kalır; diğer kampanya soruları ilgili
    # belge metninin bulunacağı RAG yoluna bırakılır.
    if slot["kampanya"] and not slot["sayma"]:
        if not re.search(r"en (cok|fazla|az)|daha (cok|fazla|az)|hangisinde daha|sayisi", f):
            return None

    # 1. Bankalar arası miktar / sayım karşılaştırması ve sıralaması ("Ziraat'te mi daha çok kampanya var?", "En çok kampanya hangi bankada?")
    if (slot["sayma"] or bool(re.search(r"en (cok|fazla|az)|daha (cok|fazla|az)|hangisinde daha|sayisi", f))) and not slot["urunler"] and not slot["metrikler"]:
        b = sayma_sorgusu(slot)
        if b["toplam"] > 0:
            return b | {"slot": slot}

    # 2. Banka ve belirli ürün sorulduğunda (Örn: "Kuveyt Türk ile Albaraka konut finansmanı")
    if (slot["bankalar"] and slot["urunler"]) or (slot.get("kiyas") and slot["urunler"]):
        k = karsilastirma_sorgusu(slot)
        if k["satirlar"]:
            return k | {"slot": slot}

    # 3. 2+ banka karşılaştırması (ürün belirtilmemişse genel sayım veya karşılaştırma tablosu)
    if len(slot["bankalar"]) >= 2 or slot.get("kiyas"):
        if slot["kampanya"] or slot["sayma"]:
            b = sayma_sorgusu(slot)
            if b["toplam"] > 0:
                return b | {"slot": slot}
        k = karsilastirma_sorgusu(slot)
        if k["satirlar"]:
            return k | {"slot": slot}

    # 4. Sıralama soruları ("En uzun vadeli konut finansmanı hangi bankada?")
    if slot["siralama"] and (slot["metrikler"] or slot["urunler"] or slot["kampanya"]):
        s = siralama_sorgusu(slot)
        if s and s["satirlar"]:
            return s | {"slot": slot}
        if slot["kampanya"]:
            b = sayma_sorgusu(slot)
            if b["toplam"] > 0:
                return b | {"slot": slot}

    # 5. Genel sayma soruları ("Ziraat'te kaç kampanya var?", "Toplam kaç kayıt var?")
    if slot["sayma"]:
        b = sayma_sorgusu(slot)
        if b["toplam"] > 0:
            return b | {"slot": slot}

    return None


def bulguyu_metne_cevir(b: dict) -> str:
    """SQL sonucunu LLM'in okuyabilecegi Teknofest Senaryo 2 standardindaki formata cevirir."""
    if b["tip"] == "siralama" and b.get("satirlar"):
        # Esit degerli cok satir oldugunda model "hangisi?" diye secim yapmaya
        # calisip listede olmayan banka adi uretebiliyor. Cevabi hazir veriyoruz.
        _en = b["satirlar"][0].get("deger")
        _bankalar, _g = [], set()
        for _r in b["satirlar"]:
            if _r.get("deger") == _en and _r.get("banka_adi") not in _g:
                _g.add(_r["banka_adi"]); _bankalar.append(_r["banka_adi"])
        _liste = ", ".join(_bankalar)
        _ad = b.get("metrik_adi", "değer")
        _yon_soz = (("En kısa" if "vade" in _ad else "En düşük") if b.get("artan")
                    else ("En uzun" if "vade" in _ad else "En yüksek"))
        _ozet = (f"[ÖZET — CEVABIN BUNA DAYANMALI] {_yon_soz} "
                 f"{_ad}: {_en}{b.get('birim','')}\n"
                 f"Bu değere sahip bankalar ({len(_bankalar)} adet): {_liste}\n"
                 f"ZORUNLU: Cevabında bu bankaların HEPSİNİ say. Tek bir banka seçme. "
                 f"Listede olmayan banka adı yazma.\n\n")
        _kapanis = (f"\n\n[HATIRLATMA] Yukarıdaki {len(_bankalar)} bankanın hepsi "
                    f"{_en}{b.get('birim','')} sunuyor: {_liste}. "
                    f"Cevabında hepsini listele.")
    else:
        _ozet = _kapanis = ""

    if b["tip"] == "siralama":
        ad, birim = b["metrik_adi"], b["birim"]
        satir = []
        for r in b["satirlar"]:
            satir.append(
                f"• Banka Bilgisi: {r['banka_adi']}\n"
                f"  Ürün / Başlık: {r['baslik']}\n"
                f"  Finansman Bilgileri: {ad}: {r['deger']}{birim} | Kâr Payı: %{r.get('kar_payi_orani') or '-'} | Vade: {r.get('vade_ay_max') or '-'} ay | Max Tutar: {r.get('tutar_max') or '-'} TL | Tahsis Ücreti: {r.get('tahsis_ucreti') or '-'} | Masraf: {r.get('masraf_bilgisi') or '-'}\n"
                f"  Hedef Kitle Bilgileri: {r.get('hedef_kitle') or 'Genel Bireysel Müşteriler'}\n"
                f"  Kaynak: {r.get('kaynak_url') or '-'}"
            )
        yon = "en düşükten" if b["artan"] else "en yüksekten"
        return _ozet + f"[SQL sonucu — {ad} {yon} sıralı]\n\n" + "\n\n".join(satir) + _kapanis

    if b["tip"] == "sayma":
        s = [f"[SQL sonucu — Sayım ve Dağılım] Toplam kayıt: {b['toplam']}"]
        if b.get("kirilim"):
            s.append("Bankalara göre kampanya/kayıt sayıları:")
            for r in b["kirilim"]:
                s.append(f"- {r['banka_adi']}: {r['n']} adet")
        if b.get("ornekler"):
            s.append("\nÖrnek Kampanyalar (Yukarıdaki toplam kayıt sayısından bağımsız, yalnızca temsili örnekler):")
            for r in b["ornekler"]:
                finans = []
                if r.get('kar_payi_orani') is not None: finans.append(f"Kâr Payı Oranı: %{r['kar_payi_orani']}")
                if r.get('vade_ay_max'): finans.append(f"Vade: {r['vade_ay_max']} Ay")
                if r.get('tutar_max'): finans.append(f"Tutar: {r['tutar_max']:,.0f} TL".replace(",", "."))
                if r.get('taksit_max'): finans.append(f"Taksit: {r['taksit_max']}")
                if r.get('tahsis_ucreti'): finans.append(f"Tahsis Ücreti: {r['tahsis_ucreti']}")
                if r.get('masraf_bilgisi'): finans.append(f"Masraf Bilgisi: {r['masraf_bilgisi']}")

                kamp = []
                if r.get('kampanya_turu'): kamp.append(f"Kampanya Türü: {r['kampanya_turu']}")
                if r.get('odul_miktari'): kamp.append(f"Ödül Miktarı: {r['odul_miktari']}")
                if r.get('indirim_orani'): kamp.append(f"İndirim Oranı: {r['indirim_orani']}")
                if r.get('alisveris_puani'): kamp.append(f"Alışveriş Puanı: {r['alisveris_puani']}")
                if r.get('kampanya_suresi'): kamp.append(f"Süre: {r['kampanya_suresi']}")
                if r.get('kampanya_bitis'): kamp.append(f"Bitiş: {r['kampanya_bitis']}")
                if r.get('kampanya_kosullari'): kamp.append(f"Koşullar: {r['kampanya_kosullari']}")

                s.append(
                    f"\n• Banka Bilgisi: {r['banka_adi']}\n"
                    f"  Kampanya / Ürün Adı: {r['baslik']}\n"
                    f"  Finansman Bilgileri: {', '.join(finans) if finans else 'Standart finansman koşulları'}\n"
                    f"  Kampanya Bilgileri: {', '.join(kamp) if kamp else 'Genel Kampanya'}\n"
                    f"  Hedef Kitle Bilgileri: {r.get('hedef_kitle') or 'Yeni ve Mevcut Müşterilere Özel'}\n"
                    f"  Kaynak: {r.get('kaynak_url') or '-'}"
                )
        return "\n".join(s)

    if b["tip"] == "karsilastirma":
        s = ["[SQL sonucu — Karşılaştırma ve Hedef Kitle Tablosu]"]
        for r in b["satirlar"]:
            #dogrulanamayan alanin satiri hic yazilmaz
            parca = [
                f"\n• Banka: {kisa_ad(r['banka_adi'])}",
                f"  Ürün Türü: {URUN_ETIKET.get(r['urun_tipi'], r['urun_tipi'])}",
            ]
            if r['oran'] is not None:
                parca.append(f"  Kâr Payı Oranı: %{r['oran']}")
            if r.get('vade'):
                parca.append(f"  Azami Vade: {r['vade']} Ay")
            if r.get('tutar'):
                _t = r['tutar']
                _ts = f"{int(_t):,}".replace(",", ".") if _t == int(_t) else str(_t)
                parca.append(f"  - Azami Finansman Tutarı: {_ts} TL")
            tahsis_ham = r.get('tahsis')
            if tahsis_ham and ('0.50' in str(tahsis_ham) or '0,50' in str(tahsis_ham)):
                parca.append("  Tahsis Ücreti: %0.50")
            elif tahsis_ham and len(str(tahsis_ham).strip()) <= 25:
                parca.append(f"  Tahsis Ücreti: {str(tahsis_ham).strip()}")
            masraf_ham = r.get('masraf')
            if masraf_ham:
                ilk = next((q.strip() for q in str(masraf_ham).split(',') if len(q.strip()) > 3),
                           str(masraf_ham).strip())
                if len(ilk) <= 60:
                    parca.append(f"  Masraf Bilgisi: {ilk}")
            hk_ham = r.get('hedef_kitle')
            if hk_ham:
                hk_parcalar = [q.strip() for q in hk_ham.split(',') if q.strip()]
                parca.append("  Hedef Kitle: " + ", ".join(dict.fromkeys(hk_parcalar)))
            avantaj = []
            if tahsis_ham and any(w in str(tahsis_ham).lower() for w in ['ucretsiz', 'ücretsiz', 'alınmaz', 'masrafsiz', '0.20', '0,20']):
                avantaj.append(f"Tahsis Avantajı: {tahsis_ham}")
            if r.get('kampanya_kosullari'):
                avantaj.append(f"Koşul/Avantaj: {r['kampanya_kosullari'][:120]}")
            if avantaj:
                parca.append("  " + " | ".join(avantaj))
            s.append("\n".join(parca))
        return "\n".join(s)
    return ""


def sablonla_yaz(b: dict) -> str:
    """LLM cikti veremezse SQL bulgusunu dogrudan Turkce metne cevirir.

    Sayilar zaten veritabanindan gelir; modelin katkisi yalnizca ifadedir.
    Alanlara .get() ile erisilir: sorgu tipine gore kolonlar degisebilir.
    """
    def _tl(v):
        return f"{int(v):,}".replace(",", ".") if v == int(v) else str(v)

    _g_not = {"suresi_dolmus": " (kampanyanın süresi sona ermiştir)",
              "yok": " (kampanya süresi belirtilmemiş)", "bilinmiyor": " (kampanya süresi belirtilmemiş)"}

    if b["tip"] == "esik_tekil":
        r0 = b["satirlar"][0]
        p = [f"{kisa_ad(r0['banka_adi'])} — {r0['baslik']} kampanyasında katılım için "
             f"minimum harcama {_tl(r0['esik_tutar'])} TL'dir{_g_not.get(r0['gecerlilik'], '')}."]
        for r in b["satirlar"][1:2]:
            p.append(f"Ayrıca: {r['baslik']} (eşik {_tl(r['esik_tutar'])} TL{_g_not.get(r['gecerlilik'], '')}).")
        return " ".join(p)

    if b["tip"] == "esik_min":
        orn = "; ".join(f"{r['baslik']} ({kisa_ad(r['banka_adi'])})" for r in b["satirlar"])
        return (f"Aktif kampanyalardan yararlanmak için en az {_tl(b['min'])} TL harcama "
                f"yeterlidir. Örnek: {orn}.")

    if b["tip"] == "esik_liste":
        maddeler = "; ".join(f"{r['baslik']} ({kisa_ad(r['banka_adi'])}, eşik {_tl(r['esik_tutar'])} TL)"
                             for r in b["satirlar"][:5])
        if b.get("aralik"):
            lo, hi = b["tutar"]
            return (f"{_tl(lo)}-{_tl(hi)} TL arası katılım eşiğine sahip aktif "
                    f"kampanyalar: {maddeler}.")
        return (f"{_tl(b['tutar'])} TL harcamayla katılabileceğiniz aktif kampanyalardan "
                f"bazıları: {maddeler}.")

    if b["tip"] == "tarih_liste":
        maddeler = "; ".join(f"{r['baslik']} ({kisa_ad(r['banka_adi'])}, son gün {_iso_tr(r['bitis_tarihi'])})"
                             for r in b["satirlar"][:6])
        return f"{AY_ADI[b['ay']]} {b['yil']}'da sona erecek kampanyalar: {maddeler}."

    if b["tip"] == "tarih_bos":
        return (f"{AY_ADI[b['ay']]} {b['yil']} içinde sona erecek bir kampanya "
                f"kayıtlarda bulunmamaktadır.")

    if b["tip"] == "tarih_tekil":
        r0 = b["satirlar"][0]
        d = ("kampanya aktiftir" if r0["gecerlilik"] in AKTIF_SET
             else "kampanyanın süresi sona ermiştir")
        p = [f"{kisa_ad(r0['banka_adi'])} — {r0['baslik']} kampanyasının son günü "
             f"{_iso_tr(r0['bitis_tarihi'])}'dir ({d})."]
        for r in b["satirlar"][1:2]:
            p.append(f"Önceki dönem: son gün {_iso_tr(r['bitis_tarihi'])}.")
        return " ".join(p)

    if b["tip"] == "esik_bos":
        if b.get("aralik"):
            lo, hi = b["tutar"]
            return (f"{_tl(lo)}-{_tl(hi)} TL arası katılım eşiğine sahip aktif bir "
                    f"kampanya kayıtlarda bulunmamaktadır.")
        ek = (f" Aktif kampanyalarda en düşük katılım eşiği {_tl(b['genel_min'])} TL'dir."
              if b.get("genel_min") else "")
        return (f"{_tl(b['tutar'])} TL harcamayla katılabileceğiniz aktif bir kampanya "
                f"kayıtlarda bulunmamaktadır.{ek}")

    def _p(v):
        try:
            return f"{float(v):,.0f}".replace(",", ".")
        except (TypeError, ValueError):
            return str(v)

    if not b:
        return ""

    if b.get("tip") == "karsilastirma":
        satir = b.get("satirlar") or []
        if not satir:
            return "Karşılaştırma için yeterli veri bulunamadı."
        p = ["Karşılaştırma sonucu:"]
        for r in satir:
            par = []
            if r.get("vade"):  par.append(f"{r['vade']} aya varan vade")
            if r.get("oran"):  par.append(f"%{r['oran']} kâr payı oranı")
            if r.get("tutar"): par.append(f"{_p(r['tutar'])} TL'ye kadar tutar")
            if r.get("tahsis"): par.append(f"tahsis: {r['tahsis']}")
            p.append(f"• {r.get('banka_adi','?')}: " + (", ".join(par) if par else "ayrıntı yok"))
        v = [r for r in satir if r.get("vade")]
        o = [r for r in satir if r.get("oran")]
        if v:
            e = max(v, key=lambda r: r["vade"])
            p.append(f"\nVade açısından {e['banka_adi']} öne çıkıyor ({e['vade']} ay).")
        if o:
            e = min(o, key=lambda r: r["oran"])
            p.append(f"Kâr payı oranı açısından {e['banka_adi']} daha avantajlı (%{e['oran']}).")
        return "\n".join(p)

    if b.get("tip") == "siralama":
        satir = b.get("satirlar") or []
        if not satir:
            return "Bu kritere uyan kayıt bulunamadı."
        ad = b.get("metrik_adi", "değer")
        birim = b.get("birim", "")
        # Turkce yazim: yuzde isareti sayidan ONCE ("%2.88"), birim SONRA ("120 ay").
        yuzde = birim.strip() == "%"
        if birim and birim[0].isalpha():
            birim = " " + birim                    # "120ay" -> "120 ay"
        bic = (lambda v: f"%{v}") if yuzde else (lambda v: f"{v}{birim}")
        # Sifir oran veri artefaktidir (bos alan 0 olarak kaydedilmis), gercek
        # bir teklif degil: "en dusuk kar payi %0" yanlis bilgi olur.
        if b.get("artan") and ("oran" in ad or "kâr" in ad or "kar" in ad):
            satir = [r for r in satir if (r.get("deger") or 0) > 0] or satir
        en = satir[0].get("deger")
        # Ayni en iyi degere sahip TUM bankalar (esitlik cok yaygin)
        bankalar, g = [], set()
        for r in satir:
            if r.get("deger") == en and r.get("banka_adi") not in g:
                g.add(r["banka_adi"]); bankalar.append(r["banka_adi"])
        kisa = [kisa_ad(b_) for b_ in bankalar]
        yon = (("en kısa" if "vade" in ad else "en düşük") if b.get("artan")
               else ("en uzun" if "vade" in ad else "en yüksek"))

        if len(kisa) == 1:
            p = [f"{kisa[0]}, {bic(en)} ile {yon} {ad} sunan bankadır."]
        else:
            p = [f"{yon.capitalize()} {ad} {bic(en)} olup, bu değeri "
                 f"{len(kisa)} banka sunmaktadır: " + ", ".join(kisa[:-1]) +
                 f" ve {kisa[-1]}."]

        # Kullanici en iyi degeri sordu: ayni bankanin baska belgelerdeki daha
        # dusuk degerlerini "sonraki kademe" diye eklemek yanilticiydi.
        return " ".join(p)

    if b.get("tip") == "sayma":
        slot = b.get("slot") or {}
        kirilim = b.get("kirilim") or []
        nesne = "kampanya kaydı" if slot.get("kampanya") else "kayıt"
        etkinlik = "aktif " if slot.get("aktiflik") == "aktif" else ""
        if len(kirilim) == 1:
            r = kirilim[0]
            return (f"{kisa_ad(r.get('banka_adi', '?'))} için "
                    f"{r.get('n', 0)} {etkinlik}{nesne} bulunmaktadır.")

        p = [f"Toplam {b.get('toplam', 0)} {etkinlik}{nesne} bulundu."]
        for r in kirilim[:8]:
            p.append(f"• {kisa_ad(r.get('banka_adi','?'))}: {r.get('n','?')}")
        if len(kirilim) >= 2:
            en = max(kirilim, key=lambda r: r.get("n", 0))
            p.append(f"En fazla {nesne} {kisa_ad(en.get('banka_adi', '?'))} bünyesindedir.")
        return "\n".join(p)
    return ""
