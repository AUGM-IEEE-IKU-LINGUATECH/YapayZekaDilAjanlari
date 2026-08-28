# -*- coding: utf-8 -*-
"""Elle doğrulanmış finansman tabloları için ortak, çevrimdışı veri katmanı.

Arayüz ve asistan aynı JSON dosyasını kullanır. Kesin oran tabloları vektör
aramasına bırakılmaz; banka ve ürün eşleştiğinde doğrudan bu kaynaktan okunur.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from .analiz import bankalari_bul, fold, soruyu_coz, urunleri_bul
from .config import DB_YOLU, kisa_ad


VERI_YOLU = DB_YOLU.parent / "finansman_oranlari.json"

OZEL_URUNLER = {
    "bes_teminatli": ("bes teminatli", "bes teminat", "birikim teminatli"),
    "dijital_pratik": ("pratik finansman kart", "dijital pratik", "pratik finansman"),
    "konut": ("kentsel donusum", "cevreci konut", "yeni konut finansmani"),
    "arac": ("togg finansmani", "togg"),
    "alisveris": (
        "alisveris finansmani", "alisveris finansman",
        "alisveris kredileri", "alisveris kredisi",
        "veresiye alisveris kredisi", "taksitli alisveris kredisi",
        "veresiye kredi",
    ),
    "arsa_isyeri": (
        "arsa finansmani", "is yeri finansmani", "isyeri finansmani",
        "arsa ve is yeri", "arsa isyeri",
    ),
    "banka_gayrimenkulleri": (
        "banka gayrimenkulleri", "banka gayrimenkulu",
        "banka portfoyundeki gayrimenkul", "satilik gayrimenkul finansmani",
    ),
    "ticari_finansman_ucretleri": (
        "ticari finansman ucretleri", "finansman tahsis ucreti",
        "finansman kullandirim ucreti", "yapilandirma ucreti",
        "temdit ucreti", "taahhude uymama ucreti",
        "ara odeme ucreti", "kismi odeme ucreti",
        "erken kapama ucreti", "finansman riski ucreti",
    ),
    "ihtiyac": (
        "hac umre finansmani", "hac ve umre finansmani", "umre finansmani",
        "egitim finansmani", "saglam kart egitim", "hac finansmani",
        "saglik finansmani", "ev ofis gerecleri", "ofis gerecleri",
    ),
}
GENEL_URUNLER = {"konut", "arac", "ihtiyac"}
FINANSMAN_URUNLERI = GENEL_URUNLER | set(OZEL_URUNLER)
URUN_ADLARI = {
    "konut": "konut finansmanı",
    "arac": "taşıt finansmanı",
    "ihtiyac": "ihtiyaç finansmanı",
    "alisveris": "alışveriş finansmanı",
    "arsa_isyeri": "arsa ve iş yeri finansmanı",
    "bes_teminatli": "BES teminatlı finansman",
    "dijital_pratik": "dijital pratik finansman",
    "banka_gayrimenkulleri": "banka gayrimenkulleri finansmanı",
    "ticari_finansman_ucretleri": "ticari finansman ücretleri",
}
URUN_GERI_DONUS = {"arsa_isyeri": "konut"}
FINANSMAN_NIYETI = re.compile(
    r"finansman|kar pay|oran|vade|tutar|limit|ucret|tahsis|kullandirim|"
    r"erken kapama|ara odeme|yapilandirma|temdit|taahhut|ilk ev|ikinci ev|"
    r"2\. ev|enerji sinifi"
)
KIYAS_NIYETI = re.compile(
    r"karsilastir|karsilastirma|kiyasla|kiyas|hangisi|farki|farklari|"
    r"avantajli|daha iyi|tercih"
)
GRAFIK_NIYETI = re.compile(r"grafik|grafig|çiz|ciz|görselle|gorselle")
VADE_AY = re.compile(r"(?<![\d.,])(\d{1,3})\s*ay(?:lik)?\b")


def veriyi_oku() -> dict[str, Any]:
    if not VERI_YOLU.exists():
        return {"surum": 1, "guncelleme_tarihi": None, "bankalar": {}}
    return json.loads(VERI_YOLU.read_text(encoding="utf-8"))


def detay(banka_kodu: str, urun_kodu: str) -> dict[str, Any] | None:
    veri = veriyi_oku()
    banka = veri.get("bankalar", {}).get(banka_kodu)
    urun = (banka or {}).get("urunler", {}).get(urun_kodu)
    if not banka or not urun:
        return None
    return {
        "banka_kodu": banka_kodu,
        "banka_adi": banka.get("banka_adi", banka_kodu),
        "urun_tipi": urun_kodu,
        "guncelleme_tarihi": veri.get("guncelleme_tarihi"),
        **urun,
    }


def _urunleri_bul(soru: str) -> list[str]:
    f = fold(soru)
    bulunan = [u for u in urunleri_bul(soru) if u in GENEL_URUNLER]
    for kod, adlar in OZEL_URUNLER.items():
        if any(ad in f for ad in adlar):
            bulunan.append(kod)
    return list(dict.fromkeys(bulunan))


def sorgula(soru: str) -> dict[str, Any] | None:
    """Banka + ürün içeren finansman sorusunu kanonik tablolara yönlendirir."""
    f = fold(soru)
    slot = soruyu_coz(soru)
    bankalar = bankalari_bul(soru)
    urunler = _urunleri_bul(soru)
    if not bankalar:
        if urunler and GRAFIK_NIYETI.search(f):
            return _grafik_sorgusu(urunler, slot)
        return None

    veri = veriyi_oku()
    mevcut_bankalar = veri.get("bankalar", {})
    if not urunler and FINANSMAN_NIYETI.search(f):
        for banka_kodu in bankalar:
            for urun_kodu in mevcut_bankalar.get(banka_kodu, {}).get("urunler", {}):
                urunler.append(urun_kodu)
        urunler = list(dict.fromkeys(urunler))
    if not urunler:
        return None

    eslesen = []
    for banka_kodu in bankalar:
        for urun_kodu in urunler:
            kayit = detay(banka_kodu, urun_kodu)
            if not kayit and urun_kodu in URUN_GERI_DONUS:
                kayit = detay(banka_kodu, URUN_GERI_DONUS[urun_kodu])
            if kayit:
                kayit = dict(kayit)
                kayit["sorgu_urun_tipi"] = urun_kodu
                eslesen.append(kayit)
    return {
        "tip": "finansman_detay",
        "guncelleme_tarihi": veri.get("guncelleme_tarihi"),
        "bankalar": bankalar,
        "urunler": urunler,
        "satirlar": eslesen,
        "tutar_tl": slot.get("tutar_tl"),
        "vade_ay": (lambda m: int(m.group(1)) if m else None)(VADE_AY.search(f)),
    }


def kaynaklari_olustur(bulgu: dict[str, Any]) -> list[dict[str, str]]:
    kaynaklar, gorulen = [], set()
    for urun in bulgu.get("satirlar", []):
        adaylar = []
        if urun.get("kaynak_url"):
            adaylar.append({"ad": urun.get("kaynak_adi") or urun.get("ad"),
                            "url": urun["kaynak_url"]})
        adaylar.extend(urun.get("ek_kaynaklar") or [])
        for kaynak in adaylar:
            url = kaynak.get("url", "")
            if not url or url in gorulen:
                continue
            gorulen.add(url)
            kaynaklar.append({
                "banka": urun.get("banka_adi", ""),
                "baslik": kaynak.get("ad") or urun.get("ad", "Finansman"),
                "url": url,
            })
    return kaynaklar


def bulguyu_metne_cevir(bulgu: dict[str, Any]) -> str:
    bloklar = ["[DOĞRULANMIŞ GÜNCEL FİNANSMAN VERİSİ — ESKİ KAYITLARA GÖRE ÖNCELİKLİ]"]
    for urun in bulgu.get("satirlar", []):
        satirlar = [
            f"Banka: {urun['banka_adi']}",
            f"Ürün: {urun['ad']}",
            f"Güncelleme: {urun.get('guncelleme_tarihi') or '-'}",
            " | ".join(urun.get("sutunlar", [])),
        ]
        for satir in urun.get("satirlar", []):
            satirlar.append("• " + " | ".join(str(x) for x in satir.get("degerler", [])))
        for not_metni in urun.get("notlar", []):
            satirlar.append("Not: " + not_metni)
        if urun.get("kaynak_url"):
            satirlar.append("İlgili resmî ürün sayfası: " + urun["kaynak_url"])
        bloklar.append("\n".join(satirlar))
    return "\n\n".join(bloklar)


def sablonla_yaz(bulgu: dict[str, Any]) -> str:
    """Sayısal değerleri model yorumuna bırakmadan Markdown tablo olarak yazar."""
    if not bulgu.get("satirlar"):
        veri = veriyi_oku().get("bankalar", {})
        bankalar = [veri.get(k, {}).get("banka_adi", k) for k in bulgu.get("bankalar", [])]
        urunler = [URUN_ADLARI.get(k, k) for k in bulgu.get("urunler", [])]
        return (
            f"Doğrulanmış güncel tabloda {', '.join(bankalar)} için "
            f"{', '.join(urunler)} verisi bulunmuyor."
        )

    bolumler = []
    for urun in bulgu.get("satirlar", []):
        sutunlar = [str(x) for x in urun.get("sutunlar", [])]
        satirlar = urun.get("satirlar", [])
        p = [f"**{urun['banka_adi']} — {urun['ad']}**"]
        if sutunlar and satirlar:
            p.append("| " + " | ".join(sutunlar) + " |")
            p.append("| " + " | ".join("---" for _ in sutunlar) + " |")
            for satir in satirlar:
                p.append("| " + " | ".join(str(x) for x in satir.get("degerler", [])) + " |")
        bolumler.append("\n".join(p))

    tarih = bulgu.get("guncelleme_tarihi")
    giris = f"Doğrulanmış finansman verileri (güncelleme: {tarih}):" if tarih else "Doğrulanmış finansman verileri:"
    return giris + "\n\n" + "\n\n".join(bolumler)


def karsilastirma_mi(soru: str, bulgu: dict[str, Any]) -> bool:
    """Çok bankalı finansman bulgusunun yorumlanması gerekip gerekmediğini belirler."""
    bankalar = list(dict.fromkeys(bulgu.get("bankalar") or []))
    return len(bankalar) >= 2 or bool(KIYAS_NIYETI.search(fold(soru)) and len(bulgu.get("satirlar", [])) >= 2)


def _eksik_banka_adlari(bulgu: dict[str, Any]) -> list[str]:
    """Soruda istenip seçilen ürün için doğrulanmış kaydı bulunmayan bankaları döndürür."""
    istenen = list(dict.fromkeys(bulgu.get("bankalar") or []))
    bulunan = {urun.get("banka_kodu") for urun in bulgu.get("satirlar", [])}
    banka_verisi = veriyi_oku().get("bankalar", {})
    return [
        banka_verisi.get(kod, {}).get("banka_adi", kod)
        for kod in istenen if kod not in bulunan
    ]


def _sayi_mi(deger: Any) -> bool:
    return isinstance(deger, (int, float)) and not isinstance(deger, bool)


def _aralikta_mi(deger: float | int, alt: Any, ust: Any) -> bool:
    if _sayi_mi(alt) and deger < alt:
        return False
    if _sayi_mi(ust) and deger > ust:
        return False
    return True


def _karsilastirma_satirlarini_sec(
        urun: dict[str, Any], tutar_tl: float | None = None,
        vade_ay: int | None = None) -> list[dict[str, Any]]:
    """Birleşik ürün, tutar ve vade koşullarına uyan doğrulanmış satırları seçer."""
    satirlar = list(urun.get("satirlar") or [])
    ilk_sutun = fold(str((urun.get("sutunlar") or [""])[0]))
    sorgu_urunu = urun.get("sorgu_urun_tipi") or urun.get("urun_tipi")
    if "finansman turu" in ilk_sutun and sorgu_urunu in {"konut", "arsa_isyeri"}:
        def arsa_isyeri_mi(satir: dict[str, Any]) -> bool:
            etiket = fold(str((satir.get("degerler") or [""])[0]))
            return "arsa" in etiket or "is yeri" in etiket or "isyeri" in etiket

        urun_satirlari = [
            satir for satir in satirlar
            if arsa_isyeri_mi(satir) == (sorgu_urunu == "arsa_isyeri")
        ]
        if urun_satirlari:
            satirlar = urun_satirlari

    if tutar_tl is not None:
        tutar_sinirli = [
            satir for satir in satirlar
            if _sayi_mi(satir.get("tutar_min")) or _sayi_mi(satir.get("tutar_max"))
        ]
        tutar_ve_oranli = [
            satir for satir in tutar_sinirli
            if any("kar_payi" in k and _sayi_mi(v) for k, v in satir.items())
        ]
        eslesen_tutarli = [
            satir for satir in tutar_sinirli
            if _aralikta_mi(tutar_tl, satir.get("tutar_min"), satir.get("tutar_max"))
        ]
        if tutar_ve_oranli:
            satirlar = [satir for satir in eslesen_tutarli if satir in tutar_ve_oranli]
        elif tutar_sinirli:
            # Bazı tablolarda oranlar vadeye, finansman sınırı ise tutara göre
            # ayrı satırlardadır (ör. Türkiye Finans taşıt tablosu).
            satirlar = [satir for satir in satirlar if satir not in tutar_sinirli]
            satirlar.extend(eslesen_tutarli)

    if vade_ay is not None:
        vadeli = [
            satir for satir in satirlar
            if not (_sayi_mi(satir.get("vade_min")) or _sayi_mi(satir.get("vade_max")))
            or _aralikta_mi(vade_ay, satir.get("vade_min"), satir.get("vade_max"))
        ]
        satirlar = vadeli

    return satirlar


def _karsilastirma_urun_adi(urun: dict[str, Any]) -> str:
    sorgu_urunu = urun.get("sorgu_urun_tipi") or urun.get("urun_tipi")
    return URUN_ADLARI.get(
        sorgu_urunu, str(urun.get("ad") or sorgu_urunu or "Finansman")
    ).title()


def karsilastirma_ozeti(bulgu: dict[str, Any]) -> list[dict[str, Any]]:
    """Farklı tablo şemalarını modelden önce ortak ve doğrulanmış metriklere indirger."""
    sonuc = []
    for urun in bulgu.get("satirlar", []):
        oranlar, vadeler, tutarlar, finansman_oranlari = [], [], [], []
        acik_tutar = None
        secilen_satirlar = _karsilastirma_satirlarini_sec(
            urun, bulgu.get("tutar_tl"), bulgu.get("vade_ay")
        )
        for satir in secilen_satirlar:
            for anahtar, deger in satir.items():
                if not _sayi_mi(deger):
                    continue
                if "kar_payi" in anahtar:
                    oranlar.append(float(deger))
                elif anahtar == "vade_max":
                    vadeler.append(int(deger))
                elif anahtar in {"tutar_max", "maks_finansman_tutari", "kredi_tutari"}:
                    tutarlar.append(float(deger))
                elif anahtar in {"finansman_orani", "finansman_orani_min", "finansman_orani_max"}:
                    finansman_oranlari.append(float(deger))
            for gosterilen in satir.get("degerler", []):
                metin = str(gosterilen)
                if "TL" in metin and "üzeri" in metin:
                    acik_tutar = metin

        notlar = list(urun.get("notlar") or [])
        finansman_siniri = next(
            (n for n in notlar
             if ("ekspertiz" in fold(n) or "finansman oran" in fold(n)) and "%" in n),
            None,
        )
        sonuc.append({
            "banka_kodu": urun.get("banka_kodu"),
            "banka_adi": urun.get("banka_adi"),
            "urun_tipi": urun.get("urun_tipi"),
            "urun_adi": _karsilastirma_urun_adi(urun),
            "oran_min": min(oranlar) if oranlar else None,
            "oran_max": max(oranlar) if oranlar else None,
            "azami_vade": max(vadeler) if vadeler else None,
            "azami_tutar": max(tutarlar) if tutarlar else None,
            "acik_tutar": acik_tutar,
            "finansman_orani_min": min(finansman_oranlari) if finansman_oranlari else None,
            "finansman_orani_max": max(finansman_oranlari) if finansman_oranlari else None,
            "notlar": notlar,
            "finansman_siniri": finansman_siniri,
            "satirlar": [list(s.get("degerler") or []) for s in secilen_satirlar],
            "uygun_satir_yok": not bool(secilen_satirlar),
        })
    return sonuc


def _grafik_sorgusu(urunler: list[str], slot: dict[str, Any]) -> dict[str, Any] | None:
    """Banka belirtilmeyen grafik sorusunu kanonik finansman verisinden üretir."""
    if len(urunler) != 1:
        return None
    urun_kodu = urunler[0]
    veri = veriyi_oku()
    eslesen = []
    for banka_kodu in veri.get("bankalar", {}):
        kayit = detay(banka_kodu, urun_kodu)
        if kayit:
            kayit = dict(kayit)
            kayit["sorgu_urun_tipi"] = urun_kodu
            eslesen.append(kayit)
    if not eslesen:
        return None

    bulgu = {
        "tip": "finansman_grafik",
        "guncelleme_tarihi": veri.get("guncelleme_tarihi"),
        "bankalar": [x["banka_kodu"] for x in eslesen],
        "urunler": [urun_kodu],
        "satirlar": eslesen,
        "tutar_tl": None,
        "vade_ay": None,
        "slot": slot,
    }
    ozetler = karsilastirma_ozeti(bulgu)
    metrikler = slot.get("metrikler") or []
    if "kar_payi_orani" in metrikler:
        alan, birim, metrik_adi = "oran_min", "%", "en düşük kâr payı oranı"
    elif "tutar_max" in metrikler:
        alan, birim, metrik_adi = "azami_tutar", "TL", "azami tutar"
    else:
        alan, birim, metrik_adi = "azami_vade", "ay", "azami vade"
    noktalar = [(kisa_ad(o["banka_adi"]), o.get(alan)) for o in ozetler if o.get(alan) is not None]
    if not noktalar:
        return None
    bulgu["grafik"] = {
        "baslik": f"{URUN_ADLARI.get(urun_kodu, urun_kodu).title()} — {metrik_adi}",
        "etiketler": [x[0] for x in noktalar],
        "degerler": [x[1] for x in noktalar],
        "birim": birim,
        "metrik_adi": metrik_adi,
    }
    return bulgu


def grafik_sablonu(bulgu: dict[str, Any]) -> str:
    """Grafikle birlikte gösterilecek kısa ve doğrulanmış metin tablosu."""
    grafik = bulgu.get("grafik") or {}
    etiketler = grafik.get("etiketler") or []
    degerler = grafik.get("degerler") or []
    birim = grafik.get("birim", "")
    metrik = grafik.get("metrik_adi", "değer")
    if not etiketler:
        return "Grafik için doğrulanmış veri bulunamadı."

    def bicim(deger):
        if birim == "%":
            return _oran_yaz(float(deger))
        if birim == "TL":
            return _tl_yaz(float(deger))
        return f"{deger} {birim}".strip()

    satirlar = [f"**{grafik.get('baslik', 'Banka karşılaştırması')}**", "",
                f"| Banka | {metrik.title()} |", "| --- | --- |"]
    satirlar.extend(f"| {etiket} | {bicim(deger)} |" for etiket, deger in zip(etiketler, degerler))
    if len(set(degerler)) == 1:
        satirlar.extend(["", f"Tüm bankalar {bicim(degerler[0])} ile aynı {metrik} değerini sunuyor."])
    return "\n".join(satirlar)


def _oran_yaz(deger: float | None) -> str:
    if deger is None:
        return "—"
    return "%" + f"{deger:.2f}".replace(".", ",")


def _tl_yaz(deger: float | None) -> str:
    if deger is None:
        return "—"
    return f"{int(deger):,}".replace(",", ".") + " TL"


def _ozet_orani_yaz(ozet: dict[str, Any]) -> str:
    if ozet["oran_min"] == ozet["oran_max"]:
        return _oran_yaz(ozet["oran_min"])
    return f"{_oran_yaz(ozet['oran_min'])} – {_oran_yaz(ozet['oran_max'])}"


def _senaryo_karsilastirma_sablonu(
        bulgu: dict[str, Any], ozetler: list[dict[str, Any]]) -> str:
    tutar_tl, vade_ay = bulgu.get("tutar_tl"), bulgu.get("vade_ay")
    arac_degeri = bool(tutar_tl is not None and bulgu.get("urunler") == ["arac"])
    kosullar = []
    if tutar_tl is not None:
        kosullar.append(_tl_yaz(tutar_tl) + (" araç fatura/kasko değeri" if arac_degeri else ""))
    if vade_ay is not None:
        kosullar.append(f"{vade_ay} ay")
    urunler = [URUN_ADLARI.get(k, k) for k in bulgu.get("urunler", [])]
    baslik = f"**{' / '.join(kosullar)} için {', '.join(urunler)} karşılaştırması**"

    satirlar = [baslik]
    uygunlar = []
    for ozet in ozetler:
        if ozet["uygun_satir_yok"] or ozet["oran_min"] is None:
            satirlar.append(
                f"- **{ozet['banka_adi']}:** Bu tutar ve vade koşullarına uyan "
                "doğrulanmış bir kâr payı oranı bulunmuyor."
            )
            continue
        uygunlar.append(ozet)
        ek = ""
        if arac_degeri and ozet.get("finansman_orani_max") is not None:
            oran = ozet["finansman_orani_max"]
            yaklasik = tutar_tl * oran / 100
            ek = f"; azami finansman oranı %{oran:g} (yaklaşık {_tl_yaz(yaklasik)})"
        satirlar.append(f"- **{ozet['banka_adi']}:** {_ozet_orani_yaz(ozet)}{ek}")

    if len(uygunlar) == 2:
        a, b = uygunlar
        if a["oran_min"] == b["oran_min"] and a["oran_max"] == b["oran_max"]:
            sonuc = (
                f"**Sonuç:** İki bankanın da kâr payı oranı {_ozet_orani_yaz(a)}; "
                "yalnızca oran açısından eşit görünüyorlar."
            )
        else:
            a_ustun = (a["oran_min"] <= b["oran_min"] and a["oran_max"] <= b["oran_max"])
            b_ustun = (b["oran_min"] <= a["oran_min"] and b["oran_max"] <= a["oran_max"])
            if a_ustun != b_ustun:
                iyi, diger = (a, b) if a_ustun else (b, a)
                if iyi["oran_min"] == diger["oran_min"]:
                    gerekce = (
                        f"En düşük oran iki bankada da {_oran_yaz(iyi['oran_min'])} olsa da "
                        f"{iyi['banka_adi']} için üst sınır {_oran_yaz(iyi['oran_max'])}, "
                        f"{diger['banka_adi']} için {_oran_yaz(diger['oran_max'])}"
                    )
                else:
                    gerekce = (
                        f"{iyi['banka_adi']} için {_ozet_orani_yaz(iyi)} olan oran aralığı, "
                        f"{diger['banka_adi']} için {_ozet_orani_yaz(diger)} olan aralıktan daha düşük"
                    )
                sonuc = (
                    f"**Sonuç:** {gerekce}. Bu nedenle yalnızca kâr payı oranı açısından "
                    f"{iyi['banka_adi']} daha avantajlı görünüyor."
                )
            else:
                en_dusuk = min(o["oran_min"] for o in uygunlar)
                adlar = [o["banka_adi"] for o in uygunlar if o["oran_min"] == en_dusuk]
                sonuc = (
                    f"**Sonuç:** Oran aralıkları kesişiyor. En düşük oran {_oran_yaz(en_dusuk)} "
                    f"ile {', '.join(adlar)} tarafında görülse de kesin oran teklif koşullarına "
                    "göre değişeceğinden tek bir banka doğrudan üstün sayılamaz."
                )
    elif len(uygunlar) == 1:
        sonuc = (
            "**Sonuç:** Yalnızca bir bankada bu koşullara uyan doğrulanmış oran bulunduğu "
            "için iki banka arasında doğrudan karşılaştırma yapılamıyor."
        )
    else:
        sonuc = (
            "**Sonuç:** Seçilen bankalarda bu tutar ve vadeye uyan doğrulanmış oran "
            "bulunmadığından karşılaştırma yapılamıyor."
        )

    satirlar.extend(["", sonuc])
    if arac_degeri:
        satirlar.append(
            "Not: Taşıt tablolarındaki tutar, kullanılacak net finansmanı değil aracın "
            "fatura/kasko değerini ifade eder. Net finansman tutarı için araç değeri ve "
            "uygulanacak finansman oranı birlikte değerlendirilmelidir."
        )
    satirlar.append("Bu değerlendirme yalnızca aylık kâr payı oranına dayanır; toplam maliyet ve diğer koşullar ayrıca incelenmelidir.")
    return "\n".join(satirlar)


def karsilastirma_sablonu(bulgu: dict[str, Any]) -> str:
    """Model yanıt veremezse ortak metriklerden güvenli bir karşılaştırma üretir."""
    ozetler = karsilastirma_ozeti(bulgu)
    eksik_bankalar = _eksik_banka_adlari(bulgu)
    if not ozetler:
        return (
            "Seçilen ürün için " + ", ".join(eksik_bankalar)
            + " hakkında doğrulanmış güncel veri bulunmadığından karşılaştırma yapılamıyor."
        )
    if bulgu.get("tutar_tl") is not None or bulgu.get("vade_ay") is not None:
        return _senaryo_karsilastirma_sablonu(bulgu, ozetler)
    oranli = [o for o in ozetler if o["oran_min"] is not None]
    vadeli = [o for o in ozetler if o["azami_vade"] is not None]
    giris = []
    if len(ozetler) >= 2 and oranli:
        en_dusuk = min(o["oran_min"] for o in oranli)
        adlar = [o["banka_adi"] for o in oranli if o["oran_min"] == en_dusuk]
        giris.append(
            f"Tablolardaki en düşük başlangıç kâr payı {_oran_yaz(en_dusuk)} ile "
            + ", ".join(adlar) + " tarafından sunuluyor."
        )
    if len(ozetler) >= 2 and vadeli:
        en_uzun = max(o["azami_vade"] for o in vadeli)
        adlar = [o["banka_adi"] for o in vadeli if o["azami_vade"] == en_uzun]
        giris.append(f"En uzun azami vade {en_uzun} ay ile " + ", ".join(adlar) + " tarafından sunuluyor.")

    tablo = [
        "| Banka | Ürün | Tablodaki kâr payı aralığı | Azami vade | Finansman sınırı / koşulu |",
        "| --- | --- | --- | --- | --- |",
    ]
    for o in ozetler:
        oran = _ozet_orani_yaz(o)
        if o.get("finansman_siniri"):
            tutar = o["finansman_siniri"]
        elif o.get("finansman_orani_max") is not None:
            alt = o.get("finansman_orani_min")
            ust = o.get("finansman_orani_max")
            tutar = f"Ekspertiz/fatura değerinin %{alt:g}–%{ust:g}'ı" if alt != ust else f"Ekspertiz/fatura değerinin %{ust:g}'ı"
        else:
            tutar = _tl_yaz(o["azami_tutar"]) if o.get("azami_tutar") is not None else "Tabloda kesin üst sınır yok"
        tablo.append(
            f"| {o['banka_adi']} | {o['urun_adi']} | {oran} | "
            f"{o['azami_vade'] or '—'} ay | {tutar} |"
        )
    if eksik_bankalar:
        giris.append(
            "Seçilen ürün için " + ", ".join(eksik_bankalar)
            + " hakkında doğrulanmış veri bulunmadığından eksiksiz bir karşılaştırma yapılamıyor."
        )
    if eksik_bankalar:
        yorum = (
            "**Kısa yorum:** Seçilen ürün için tüm bankalarda doğrulanmış veri bulunmadığı "
            "için doğrudan bir avantaj karşılaştırması yapılamaz."
        )
    else:
        yorum = (
            "**Kısa yorum:** Başlangıç oranı tek başına toplam finansman maliyetini belirlemez. "
            "Oranlar tutar ve vade dilimine göre değişebildiği için aynı finansman tutarı ile "
            "aynı vade üzerinden teklif alınmadan bir bankayı koşulsuz olarak daha avantajlı "
            "saymak doğru olmaz."
        )
    return "\n\n".join([" ".join(giris), "\n".join(tablo), yorum])


def slot_baglami(slot: dict[str, Any]) -> str:
    """Zorlanmış RAG yolunda da eski SQLite değerlerinin yeni veriyi ezmesini önler."""
    bankalar = slot.get("bankalar") or []
    urunler = [u for u in (slot.get("urunler") or []) if u in FINANSMAN_URUNLERI]
    if not bankalar or not urunler:
        return ""
    veri = veriyi_oku()
    eslesen = []
    for banka_kodu in bankalar:
        for urun_kodu in urunler:
            kayit = detay(banka_kodu, urun_kodu)
            if not kayit and urun_kodu in URUN_GERI_DONUS:
                kayit = detay(banka_kodu, URUN_GERI_DONUS[urun_kodu])
            if kayit:
                eslesen.append(kayit)
    if not eslesen:
        return ""
    return bulguyu_metne_cevir({
        "guncelleme_tarihi": veri.get("guncelleme_tarihi"),
        "satirlar": eslesen,
    })
