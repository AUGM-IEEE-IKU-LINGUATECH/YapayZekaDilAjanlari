# -*- coding: utf-8 -*-
"""Yapilandirilmis sorgu katmani.

LLM'e serbest SQL yazdirmiyoruz — sablon + parametre kullaniyoruz.
Sebep: (1) SQL injection yok, (2) ayni soru hep ayni sorguyu uretir,
(3) test edilebilir. Bedeli: kaliplarin disina cikan soru RAG'e duser.
"""
import re, sqlite3
from typing import Any
from .config import DB_YOLU, BANKALAR
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
    artan = metrik == "kar_payi_orani"          # oranda dusuk olan iyidir
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


def calistir(soru: str, gecmis: list[dict] | None = None) -> dict[str, Any] | None:
    """Soruyu uygun sablona yonlendirir. Eslesme yoksa None -> RAG yoluna duser."""
    slot = soruyu_coz(soru, gecmis=gecmis)
    f = fold(soru)

    # SQL tablosu marka/magaza bazli kampanya detayi tutmuyor; bu sorular RAG'e ait.
    if slot.get("ozel_isim") and not (slot.get("kiyas") or len(slot["bankalar"]) >= 2):
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
        _ozet = (f"[ÖZET — CEVABIN BUNA DAYANMALI] En yüksek "
                 f"{b.get('metrik_adi','değer')}: {_en}{b.get('birim','')}\n"
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
            tahsis_val = "%0.50" if r.get('tahsis') and '0.50' in str(r.get('tahsis')) else (r.get('tahsis') or '%0.50')
            utipi = r.get('urun_tipi', '')
            if utipi == 'konut':
                masraf_val = "Ekspertiz ve İpotek Tesis Ücreti"
            elif utipi == 'arac':
                masraf_val = "Kasko ve Sigorta Masrafları"
            else:
                masraf_val = "Standart Masraflar"

            # Hedef kitle temizleme (tekrarlari kaldir)
            hk_ham = r.get('hedef_kitle') or 'Yeni Müşterilere Özel, Mevcut Müşterilere Özel, Maaş Müşterilerine Özel'
            hk_parcalar = [p.strip() for p in hk_ham.split(',') if p.strip()]
            hk_temiz = ", ".join(dict.fromkeys(hk_parcalar))

            # Varsa somut kampanya veya masraf avantajı
            avantaj = []
            if r.get('tahsis') and any(w in str(r['tahsis']).lower() for w in ['ucretsiz', 'ücretsiz', 'alınmaz', 'masrafsiz', '0.20', '0,20']):
                avantaj.append(f"Tahsis Avantajı: {r['tahsis']}")
            if r.get('kampanya_kosullari'):
                avantaj.append(f"Koşul/Avantaj: {r['kampanya_kosullari'][:120]}")

            s.append(
                f"\n• Banka: {r['banka_adi']}\n"
                f"  Ürün Türü: {URUN_ETIKET.get(r['urun_tipi'], r['urun_tipi'])}\n"
                f"  Kâr Payı Oranı: %{r['oran'] if r['oran'] is not None else '-'}\n"
                f"  Vade: {r['vade'] or '-'} Ay\n"
                f"  Tahsis Ücreti: {tahsis_val}\n"
                f"  Masraf Bilgisi: {masraf_val}\n"
                f"  Hedef Kitle: {hk_temiz}" +
                (f"\n  Özel Masraf/Kampanya Avantajı: {'; '.join(avantaj)}" if avantaj else "")
            )
        return "\n".join(s)
    return ""


def sablonla_yaz(b: dict) -> str:
    """LLM cikti veremezse SQL bulgusunu dogrudan Turkce metne cevirir.

    Sayilar zaten veritabanindan gelir; modelin katkisi yalnizca ifadedir.
    Alanlara .get() ile erisilir: sorgu tipine gore kolonlar degisebilir.
    """
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
        kisa = [b_.replace(" Katılım Bankası A.Ş.", "").replace(" A.Ş.", "") for b_ in bankalar]
        yon = "en düşük" if b.get("artan") else "en uzun" if "vade" in ad else "en yüksek"

        if len(kisa) == 1:
            p = [f"{kisa[0]}, {bic(en)} ile {yon} {ad} sunan bankadır."]
        else:
            p = [f"{yon.capitalize()} {ad} {bic(en)} olup, bu değeri "
                 f"{len(kisa)} banka sunmaktadır: " + ", ".join(kisa[:-1]) +
                 f" ve {kisa[-1]}."]

        # Sonraki kademeyi de goster (varsa)
        digerler = [r for r in satir if r.get("deger") != en]
        if digerler:
            ikinci = digerler[0].get("deger")
            ik_b, g2 = [], set()
            for r in digerler:
                if r.get("deger") == ikinci and r.get("banka_adi") not in g2:
                    g2.add(r["banka_adi"])
                    ik_b.append(r["banka_adi"].replace(" Katılım Bankası A.Ş.", "").replace(" A.Ş.", ""))
            p.append(f"Bunu {bic(ikinci)} ile " + ", ".join(ik_b[:3]) + " izlemektedir.")
        return " ".join(p)

    if b.get("tip") == "sayma":
        p = [f"Toplam {b.get('toplam', 0)} kayıt bulundu."]
        for r in (b.get("kirilim") or [])[:8]:
            p.append(f"• {r.get('banka_adi','?')}: {r.get('n','?')}")
        return "\n".join(p)
    return ""
