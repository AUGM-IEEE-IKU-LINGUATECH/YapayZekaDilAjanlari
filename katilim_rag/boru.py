# -*- coding: utf-8 -*-
"""Uctan uca cevap uretimi: yonlendirme -> (SQL | RAG) -> LLM -> kaynakli cevap."""
import re
import time
from urllib.parse import urlsplit
from . import sql_arac, getir, llm, finansman
from .analiz import fold, soruyu_coz
from .config import TOP_K_CEVAP, BANKALAR

# Soru olmayan girdiler: selamlama, tesekkur, veda. Belge aramasi yapmak
# hem gereksiz hem de alakasiz icerik dokerek kotu cevap uretir.
SOHBET = re.compile(
    r"^\s*(tesekkur|tsk|sagol|sag ol|eline saglik|harika|super|guzel|tamam|anladim|"
    r"merhaba|selam|gunaydin|iyi gunler|iyi aksamlar|hosca kal|gorusuruz|"
    r"cok yardimci|yardimci oldun|eyvallah|helal)")

SOHBET_CEVAP = {
    "tesekkur": "Rica ederim. Katılım bankacılığıyla ilgili başka bir sorunuz olursa yardımcı olabilirim.",
    "selam": "Merhaba. Katılım bankalarının ürün, hesap ve kampanyaları hakkında soru sorabilirsiniz.",
}


def _sohbet_mi(soru: str) -> str | None:
    """Sadece icerik sinyali TASIMAYAN kisa nezaket ifadeleri kisa devre yapar.

    "Tesekkurler ama Ziraat'in konut finansmani kac ay?" -> sohbet DEGIL:
    tesekkurle basliyor ama icinde gercek bir soru var.
    """
    f = fold(soru)
    if len(soru) > 60 or not SOHBET.match(f):
        return None
    slot = soruyu_coz(soru)
    if any([slot["bankalar"], slot["urunler"], slot["metrikler"],
            slot["kampanya"], slot["aciklama"], slot["siralama"], slot["sayma"]]):
        return None
    if re.match(r"^\s*(merhaba|selam|gunaydin|iyi gunler|iyi aksamlar)", f):
        return SOHBET_CEVAP["selam"]
    return SOHBET_CEVAP["tesekkur"]


def _belirsiz_oran_sorusu(soru: str) -> bool:
    """Ürün/tutar/vade olmadan yapılan 'en düşük oran' genellemesini engeller."""
    slot = soruyu_coz(soru)
    return (slot.get("siralama") and "kar_payi_orani" in slot.get("metrikler", [])
            and not slot.get("urunler"))


def _belirsiz_oran_cevabi(soru: str) -> str:
    duzeltme = ""
    f = fold(soru)
    if "faiz" in f or "kredi" in f:
        duzeltme = ("Katılım bankacılığında faizli kredi yerine kâr paylı finansman "
                    "ifadesi kullanılır. ")
    return (duzeltme + "Sağlıklı bir karşılaştırma yapabilmem için finansman türünü "
            "(konut, taşıt veya ihtiyaç), tutarı ve vadeyi belirtmelisiniz.")


# Cevap "bu bilgi bende yok" diyorsa kaynak listelemek yaniltici olur:
# kullanici linkleri gorup bilgi varmis saniyor.
RED = re.compile(
    # "Bilgi/kaynak yok" ile "ozellik yok" ayrimi kritik:
    # "taksit imkani BULUNMAMAKTADIR" gecerli bir cevaptir, reddetme degildir.
    r"(elimdeki|eldeki|mevcut|verilen)\s+(kaynak|bilgi|veri)\w*[^!?\n]{0,130}?"
    r"(bulunmamakta|bulunmuyor|bulunmad\w*|bulamadim|yer almiyor|yer almamakta\w*|rastlanmad\w*|mevcut degil|gecmiyor|\byok\b)"
    r"|kaynaklar\w*[^!?\n]{0,130}?(bulunmamakta|bulunmuyor|bulunmad\w*|yer almiyor|yer almamakta\w*|rastlanmad\w*|gecmiyor|belirtilmemis|belirtilmemistir|\byok\b)"
    r"|(bu )?(bilgi|veri)[^!?\n]{0,30}?(bulunmamakta|bulunmuyor|mevcut degil|yer almiyor)"
    r"|hakkinda[^!?\n]{0,60}?bilgi (yok|bulunmamakta|bulunmuyor)"
    r"|kaynaklar\w*[^!?\n]{0,60}?(belirtilmemis|belirtilmemistir|icermez|icermiyor)"
    r"|bilgi sahibi degilim|kaydedilmiyor|kaydedilmemis|kayd[iı] (yok|bulunmuyor)"
    r"|\bait degil\b|bilgi veremem|bulamadim|emin degilim")


def reddetti_mi(cevap: str) -> bool:
    return bool(RED.search(fold(cevap or "")))


# Saf yokluk bildirimi tespiti (normalize icin). "taksit imkani bulunmamaktadir"
# gibi OZELLIK-yoklugu cevaplarini ezmemek icin iki koruma birden:
# (1) cevap kisa ve en fazla iki cumle, (2) icinde kaynak/bilgi/veri/kayit
# kelimelerinden biri gecmeli (korpus-yoklugu isareti).
YOKLUK = re.compile(r"bulunmuyor|bulunmamakta|bulunmad\w*|yer almamakta\w*|yer alm[iı]yor|yer almad[iı]\w*|rastlanmad\w*|bulamad\w*|\byok(tur)?\b")
KORPUS_ISARET = re.compile(r"kaynak|bilgi|veri|kay[iı]t")


POZITIF_ICERIK = re.compile(r"%\s*\d|\d[\d.,]*\s*tl\b|\d+\s*taksit|:\s")


def _saf_korpus_reddi_mi(cevap: str) -> bool:
    if not cevap or len(cevap) > 300:
        return False
    f = fold(cevap)
    if POZITIF_ICERIK.search(f):        # somut bilgi tasiyan cevap ezilmez
        return False
    cumleler = [c for c in re.split(r"[.!?]", cevap) if c.strip()]
    return len(cumleler) <= 2 and bool(YOKLUK.search(f)) and bool(KORPUS_ISARET.search(f))


# Qwen, baglam zayifken ana diline kayabiliyor; prompt kurali azaltir, garanti etmez.
YABANCI_HARF = re.compile(r"[\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff\uac00-\ud7af"
                          r"\u0400-\u04ff\u0600-\u06ff]")

# Prompt kurali cogu zaman yeterli ama model bazen kullanicinin terimini tekrarliyor.
# Sartname 5.5 gereginin garantisi cikti tarafinda: metin duzeyinde duzeltme.
TERIM = [
    (re.compile(r"\bkâr oran(ı|ları|ıdır)\b", re.I), lambda m: "kâr payı oran" + m.group(1)),
    (re.compile(r"\bkar oran(ı|ları|ıdır)\b", re.I), lambda m: "kâr payı oran" + m.group(1)),
    (re.compile(r"\bfaiz oran(ı|ları)\b", re.I),      lambda m: "kâr payı oran" + m.group(1)),
    (re.compile(r"\bkredi çek(mek|me|erek)\b", re.I), lambda m: "finansman kullan" + 
        {"mek":"mak","me":"ma","erek":"arak"}[m.group(1)]),
]

def terimleri_duzelt(cevap: str) -> str:
    for kalip, degistir in TERIM:
        cevap = kalip.sub(degistir, cevap)
    return cevap


def dil_temizle(cevap: str) -> str:
    return (cevap.replace("。", ".").replace("，", ",").replace("；", ";")
                 .replace("：", ":").replace("！", "!").replace("？", "?"))

def dil_bozuk_mu(cevap: str) -> bool:
    """Cevap baska dile kaymis mi? (noktalama degil, HARF sayilir)"""
    return bool(cevap) and len(YABANCI_HARF.findall(cevap)) >= 3


# "KUVEYT TURK KATILMA HESABI" gibi fiilsiz/soru isaretsiz girdilerde model,
# kullanicinin boyle bir hesabi OLDUGUNU varsayip kisisellestirilmis cevap
# uydurabiliyor ("%34.08 kar payi ile hesabiniz bulunmaktadir"). Ciplak sorgu
# tespit edilir ve modele genel bilgilendirme talimati eklenir.
SORU_EKI = re.compile(r"nedir|ne demek|nasil|kac|var m[iu]|\bm[iu]\b|\bmidir\b|hangi|"
                      r"ver\b|goster|listele|acikla|karsilastir|oner|soyle|\?", re.I)

def ciplak_sorgu_mu(q: str) -> bool:
    f = fold(q).strip()
    return len(f.split()) <= 5 and not SORU_EKI.search(f)


CIPLAK_NOT = ("\n(Not: Kullanıcı yalnızca anahtar kelimeler yazdı. Bu konu hakkında genel, "
              "tanıtıcı bilgi ver. Kullanıcının mevcut bir hesabı veya ürünü olduğunu "
              "VARSAYMA; 'hesabınız', 'sahip olduğunuz' gibi ifadeler kullanma.)")


KAYNAK_GENEL_KOKLER = {
    "katilim", "banka", "hesap", "kampanya", "firsat", "urun", "finansman",
    "kart", "kredi", "taksit", "vade", "oran", "indirim", "odul", "puan",
    "alisveris", "magaza", "sektor", "aktif", "guncel", "gecerli", "suresi",
    "dolmus", "biten", "baslayan", "tarih", "donem", "kosul", "sart", "detay",
    "nedir", "nasil", "hangi", "neler", "kadar", "verir", "yapar", "gecer",
    "konut", "arac", "tasit", "ihtiyac", "ticari", "kobi", "sigorta", "egitim",
    "ocak", "subat", "mart", "nisan", "mayis", "haziran", "temmuz", "agustos",
    "eylul", "ekim", "kasim", "aralik",
}


def _terim_token_eslesir(terim: str, tokenlar: set[str]) -> bool:
    """Uzun özel adlarda Türkçe ekleri tolere eder; 'hâlâ' -> 'halalbooking' olmaz."""
    return terim in tokenlar or (len(terim) >= 5 and any(
        token.startswith(terim) or terim.startswith(token) for token in tokenlar
    ))


def _odakli_kaynaklari_sec(kaynaklar: list[dict], soru: str) -> list[dict]:
    """Belirli marka/kampanya sorusunda yalniz dogrudan eslesen kaynaklari gosterir.

    RAG baglami degismez; bu yalnizca kullaniciya sunulan kaynak listesini
    daha durust ve okunur hale getirir. Genel sorularda coklu kaynak korunur.
    """
    if len(kaynaklar) <= 1:
        return kaynaklar

    banka_kelimeleri = set()
    for kod, ad in BANKALAR.items():
        banka_kelimeleri.update(re.findall(r"[a-z0-9]+", fold(kod.replace("_", " "))))
        banka_kelimeleri.update(re.findall(r"[a-z0-9]+", fold(ad)))

    def genel_mi(kelime: str) -> bool:
        return (len(kelime) < 4 or kelime.isdigit() or kelime in banka_kelimeleri
                or any(kelime.startswith(kok) for kok in KAYNAK_GENEL_KOKLER))

    soru_kelimeleri = {
        k for k in re.findall(r"[a-z0-9]+", fold(soru)) if not genel_mi(k)
    }
    if not soru_kelimeleri:
        return kaynaklar

    arama_tokenlari = [
        set(re.findall(r"[a-z0-9]+", fold(f"{k.get('baslik', '')} {k.get('url', '')}")))
        for k in kaynaklar
    ]
    # Yalnizca kaynaklarin bir bolumunu ayirt eden terimler odak terimidir.
    # Boylece "kampanya", "taksit" gibi ortak kelimeler listeyi daraltmaz.
    odak = {
        kelime for kelime in soru_kelimeleri
        if 0 < sum(_terim_token_eslesir(kelime, tokenlar) for tokenlar in arama_tokenlari) < len(kaynaklar)
    }
    if not odak or not any(_terim_token_eslesir(k, arama_tokenlari[0]) for k in odak):
        return kaynaklar

    secilen = [
        kaynak for kaynak, tokenlar in zip(kaynaklar, arama_tokenlari)
        if any(_terim_token_eslesir(k, tokenlar) for k in odak)
    ]
    return secilen or kaynaklar


def _url_anahtari(url: str) -> str:
    """HTTP/HTTPS ve www farkı dışında aynı olan kaynakları tekilleştirir."""
    if not url:
        return ""
    try:
        p = urlsplit(url)
        alan = (p.hostname or "").lower()
        if alan.startswith("www."):
            alan = alan[4:]
        return f"{alan}{p.path.rstrip('/').lower()}?{p.query.lower()}"
    except Exception:
        return fold(url).replace("http://", "").replace("https://", "").replace("www.", "")


def _doc_id(sonuc: dict) -> str:
    m = sonuc.get("metadata") or {}
    return m.get("doc_id") or (sonuc.get("chunk_id") or "").rsplit("__c", 1)[0]


def _tekrar_belgeleri_temizle(sonuclar: list[dict]) -> list[dict]:
    """Aynı sayfanın farklı protokolle alınmış kopyalarından güvenilir olanı tutar."""
    gruplar: dict[str, dict[str, list[tuple[int, dict]]]] = {}
    for sira, sonuc in enumerate(sonuclar):
        m = sonuc.get("metadata") or {}
        url_anahtari = _url_anahtari(m.get("kaynak_url", "")) or f"doc:{_doc_id(sonuc)}"
        gruplar.setdefault(url_anahtari, {}).setdefault(_doc_id(sonuc), []).append((sira, sonuc))

    secilen: list[tuple[int, dict]] = []
    bilinen = {"aktif", "suresi_dolmus", "surekli"}
    for belgeler in gruplar.values():
        def belge_puani(parca: list[tuple[int, dict]]):
            durum = (parca[0][1].get("metadata") or {}).get("gecerlilik_durumu")
            en_skor = max(x[1].get("rerank_skor", x[1].get("vektor_skor", 0)) for x in parca)
            return (durum in bilinen, en_skor, len(parca), -parca[0][0])
        secilen.extend(max(belgeler.values(), key=belge_puani))
    return [sonuc for _, sonuc in sorted(secilen, key=lambda x: x[0])]


def _odakli_sonuclari_sec(sonuclar: list[dict], soru: str) -> list[dict]:
    """LLM bağlamını belirgin ürün/kampanya başlığına odaklar."""
    if len(sonuclar) <= 1:
        return sonuclar
    soru_fold = fold(soru)

    # Başlığın tamamı soruda geçiyorsa en güvenilir sinyal budur:
    # "Sağlam Kart" sorusu, "Sağlam Business Kart" belgesini almamalı.
    tam = []
    for sonuc in sonuclar:
        baslik = fold((sonuc.get("metadata") or {}).get("baslik", "")).strip()
        if len(baslik.split()) >= 2 and re.search(rf"\b{re.escape(baslik)}\b", soru_fold):
            tam.append(sonuc)
    if tam:
        return tam

    # Banka belirtilmeyen keşif sorularında (ör. "esnafa kampanya sunan banka")
    # ilk sonucun kelimelerine göre diğer adayları elemek doğru bankayı görünmez
    # yapabilir. Sözcük bazlı daraltmayı yalnızca banka açıkça seçilmişse uygula.
    if not soruyu_coz(soru).get("bankalar"):
        return sonuclar

    banka_kelimeleri = set()
    for kod, ad in BANKALAR.items():
        banka_kelimeleri.update(re.findall(r"[a-z0-9]+", fold(kod.replace("_", " "))))
        banka_kelimeleri.update(re.findall(r"[a-z0-9]+", fold(ad)))

    def genel_mi(kelime: str) -> bool:
        return (len(kelime) < 4 or kelime.isdigit() or kelime in banka_kelimeleri
                or any(kelime.startswith(kok) for kok in KAYNAK_GENEL_KOKLER))

    soru_kelimeleri = {
        k for k in re.findall(r"[a-z0-9]+", soru_fold) if not genel_mi(k)
    }
    tokenlar = [
        set(re.findall(r"[a-z0-9]+", fold(
            f"{(s.get('metadata') or {}).get('baslik', '')} "
            f"{(s.get('metadata') or {}).get('kaynak_url', '')}"
        ))) for s in sonuclar
    ]
    odak = {
        k for k in soru_kelimeleri
        if 0 < sum(_terim_token_eslesir(k, t) for t in tokenlar) < len(tokenlar)
    }
    if not odak or not any(_terim_token_eslesir(k, tokenlar[0]) for k in odak):
        return sonuclar
    secilen = [
        s for s, t in zip(sonuclar, tokenlar)
        if any(_terim_token_eslesir(k, t) for k in odak)
    ]
    return secilen or sonuclar


def kaynaklari_topla(sonuclar, soru: str = "") -> list[dict]:
    konum, kaynak = {}, []
    bilinen = {"aktif", "suresi_dolmus", "surekli"}
    for r in sonuclar:
        m = r["metadata"]
        u = m.get("kaynak_url", "")
        if not u:
            continue
        aday = {"banka": m.get("banka_adi", ""), "baslik": m.get("baslik", ""),
                "url": u, "gecerlilik": m.get("gecerlilik_durumu", ""),
                "skor": round(r.get("rerank_skor", r.get("vektor_skor", 0)), 4)}
        anahtar = _url_anahtari(u)
        if anahtar not in konum:
            konum[anahtar] = len(kaynak)
            kaynak.append(aday)
        else:
            i = konum[anahtar]
            if kaynak[i].get("gecerlilik") not in bilinen and aday["gecerlilik"] in bilinen:
                kaynak[i] = aday
    return _odakli_kaynaklari_sec(kaynak, soru) if soru else kaynak


def _sql_kaynaklari_topla(bulgu: dict) -> list[dict]:
    """SQL sonuçlarında bir banka için en ilgili tek ürün sayfasını seçer."""
    satirlar = list(bulgu.get("satirlar", bulgu.get("ornekler", [])) or [])
    if bulgu.get("tip") == "siralama" and satirlar:
        en = satirlar[0].get("deger")
        satirlar = [r for r in satirlar if r.get("deger") == en]
        urunler = (bulgu.get("slot") or {}).get("urunler") or []
        urun_sozleri = {
            "konut": {"konut", "gayrimenkul"}, "arac": {"arac", "tasit"},
            "ihtiyac": {"ihtiyac"}, "katilma_hesabi": {"katilma", "hesap"},
        }
        aranan = set().union(*(urun_sozleri.get(u, {u}) for u in urunler)) if urunler else set()
        kotu = {"sigorta", "ortaklik", "sermaye", "kampanya"}

        def puan(r: dict) -> tuple[int, int]:
            baslik = set(re.findall(r"[a-z0-9]+", fold(r.get("baslik", ""))))
            return (len(aranan & baslik) * 3 - len(kotu & baslik) * 4, -len(baslik))

        banka_gruplari: dict[str, list[dict]] = {}
        for r in satirlar:
            banka_gruplari.setdefault(r.get("banka_adi", ""), []).append(r)
        satirlar = [max(grup, key=puan) for grup in banka_gruplari.values()]

    kaynaklar, gorulen = [], set()
    for r in satirlar:
        url = r.get("kaynak_url", "")
        anahtar = _url_anahtari(url)
        if not url or anahtar in gorulen:
            continue
        gorulen.add(anahtar)
        kaynaklar.append({"url": url, "banka": r.get("banka_adi", ""),
                          "baslik": r.get("baslik", "")})
        if len(kaynaklar) >= 8:
            break
    return kaynaklar


def cevapla(soru: str, k: int = TOP_K_CEVAP, llm_kullan: bool = True,
            zorla: str | None = None) -> dict:
    """zorla: None (otomatik) | 'sql' | 'rag' — test sisteminde yol karsilastirmak icin."""
    t0 = time.time()
    cikti = {"soru": soru, "yol": None, "cevap": None, "kaynaklar": [],
             "bulgu": None, "sure_sn": None}

    kisa = _sohbet_mi(soru)
    if kisa and zorla is None:
        cikti.update({"yol": "sohbet", "cevap": kisa, "sure_sn": round(time.time() - t0, 2)})
        return cikti

    if zorla is None and _belirsiz_oran_sorusu(soru):
        cikti.update({"yol": "netlestirme", "cevap": _belirsiz_oran_cevabi(soru),
                      "sure_sn": round(time.time() - t0, 2)})
        return cikti

    # Kullanıcı tarafından doğrulanmış güncel oran tabloları eski SQLite/RAG
    # kayıtlarından önce gelir. Sayılar modele yeniden yazdırılmaz; kanonik
    # JSON'dan deterministik tablo üretilir.
    finansman_bulgusu = None if zorla == "rag" else finansman.sorgula(soru)
    if finansman_bulgusu:
        if finansman_bulgusu.get("tip") == "finansman_grafik":
            cevap = finansman.grafik_sablonu(finansman_bulgusu)
            karsilastirma = False
            uretim = "sablon-grafik"
        else:
            karsilastirma = finansman.karsilastirma_mi(soru, finansman_bulgusu)
        if finansman_bulgusu.get("tip") != "finansman_grafik" and karsilastirma:
            cevap = finansman.karsilastirma_sablonu(finansman_bulgusu)
            uretim = "sablon-karsilastirma"
        elif finansman_bulgusu.get("tip") != "finansman_grafik":
            cevap = finansman.sablonla_yaz(finansman_bulgusu)
            uretim = "sablon"
        cikti.update({
            "yol": "finansman",
            "bulgu": finansman_bulgusu,
            "cevap": cevap,
            "kaynaklar": finansman.kaynaklari_olustur(finansman_bulgusu),
            "uretim": uretim,
            "karsilastirma": karsilastirma,
            "sure_sn": round(time.time() - t0, 2),
        })
        return cikti

    # 1. SQL Yolunu Dene (Sayım, Sıralama, Karşılaştırma veya Doğrulanmış Oranlar)
    bulgu = None if zorla == "rag" else sql_arac.calistir(soru)
    if bulgu and zorla != "rag":
        cikti["yol"] = "sql"
        metin = sql_arac.bulguyu_metne_cevir(bulgu)
        cikti["bulgu"] = bulgu
        cikti["kaynaklar"] = _sql_kaynaklari_topla(bulgu)
        soru_llm = soru + (CIPLAK_NOT if ciplak_sorgu_mu(soru) else "")
        # SIRALAMA cevaplari sablonla uretilir, modele yazdirilmaz.
        # Gerekce: cevap zaten bir olgu listesi; modelin katkisi yalnizca ifade,
        # buna karsilik gozlemlenen riskler somut — esit degerli 7 bankadan birini
        # secip tek cevap gibi sunmak, ilgisiz satirlardan (arsa finansmani) yanlis
        # deger okumak, hatta kaynakta olmayan vade araligi uydurmak.
        if bulgu.get("tip") in ("siralama", "sayma", "esik_tekil", "esik_min", "esik_liste", "esik_bos", "tarih_liste", "tarih_bos", "tarih_tekil"):
            cikti["cevap"] = sql_arac.sablonla_yaz(bulgu)
            cikti["uretim"] = "sablon"
        else:
            cikti["cevap"] = llm.sql_cevap(soru_llm, metin) if llm_kullan else metin
        if llm_kullan and cikti.get("cevap"):
            cikti["cevap"] = terimleri_duzelt(dil_temizle(cikti["cevap"]))
        if llm_kullan and dil_bozuk_mu(cikti.get("cevap")):
            # SQL verisi elimizde: modele mahkum degiliz, sablonla yaz.
            cikti["cevap"] = sql_arac.sablonla_yaz(bulgu) or cikti["cevap"]
            cikti["dil_korumasi"] = "sablona_dusuldu"
        cikti["sure_sn"] = round(time.time() - t0, 2)
        return cikti

    # HİBRİT RAG HATTI (Ana Doğal Dil Omurgası)
    cikti["yol"] = "rag"
    a = getir.ara(soru, k=k)
    a["sonuclar"] = _odakli_sonuclari_sec(
        _tekrar_belgeleri_temizle(a["sonuclar"]), soru
    )
    cikti["aday_sayisi"] = a["aday_sayisi"]
    cikti["filtre"] = a["filtre"]
    tum_kaynaklar = kaynaklari_topla(a["sonuclar"])
    cikti["kaynaklar"] = _odakli_kaynaklari_sec(tum_kaynaklar, soru)
    if len(cikti["kaynaklar"]) < len(tum_kaynaklar):
        cikti["kaynak_odaklandi"] = True
    cikti["chunklar"] = [{"chunk_id": r["chunk_id"], "icerik": r["icerik"],
                          "skor": r.get("rerank_skor", r.get("vektor_skor"))}
                         for r in a["sonuclar"]]
    if not a["sonuclar"]:
        cikti["cevap"] = ("Elimdeki kaynaklarda bu soruya dair bilgi bulamadım. "
                          "Sorduğunuz konu veri setimde yer almıyor olabilir.")
        cikti["kaynaklar"] = []
    else:
        baglam = getir.baglami_metne_cevir(a["sonuclar"], slot=a["slot"])
        soru_llm = soru + (CIPLAK_NOT if ciplak_sorgu_mu(soru) else "")
        cikti["cevap"] = llm.rag_cevap(soru_llm, baglam) if llm_kullan else baglam

    # --- dil guvenligi: once noktalama duzelt, gercek kayma varsa kademeli kurtar
    if llm_kullan and cikti.get("cevap"):
        cikti["cevap"] = terimleri_duzelt(dil_temizle(cikti["cevap"]))
    if llm_kullan and dil_bozuk_mu(cikti.get("cevap")):
        try:
            yeni = llm.rag_cevap(soru_llm, baglam)
            if yeni and not dil_bozuk_mu(yeni):
                cikti["cevap"] = dil_temizle(yeni); cikti["dil_korumasi"] = "tekrar_basarili"
        except Exception:
            pass
    if llm_kullan and dil_bozuk_mu(cikti.get("cevap")):
        cikti["cevap"] = ("Bu soruya elimdeki kaynaklardan güvenilir bir cevap üretemedim. "
                          "Sorunuzu biraz daha belirginleştirirseniz yardımcı olabilirim.")
        cikti["kaynaklar"] = []; cikti["dil_korumasi"] = "guvenli_metin"

    # Kural 10'un cikti tarafindaki garantisi: istenen banka, donen kaynaklarin
    # HICBIRINDE yoksa (filtre gevsetilip baska bankalarin metinleri gelmisse)
    # ve model de yokluk bildiriyorsa cevabi standart redde normalize et.
    # Kullaniciya "yok" derken alakasiz bankalarin kaynaklarini listelemek yaniltici.
    istenen = (a["slot"].get("bankalar") or []) if cikti.get("yol") == "rag" else []
    if istenen and a.get("sonuclar") and cikti.get("cevap"):
        gelenler = {r["metadata"].get("banka_kodu") for r in a["sonuclar"]}
        _c = cikti["cevap"]
        _f = fold(_c)
        _kisa = len(_c) <= 300 and len([x for x in re.split(r"[.!?]", _c) if x.strip()]) <= 2
        if (not (set(istenen) & gelenler) and YOKLUK.search(_f)
                and _kisa and not POZITIF_ICERIK.search(_f)):
            ad = BANKALAR.get(istenen[0], "ilgili banka")
            cikti["cevap"] = f"Verilen kaynaklarda {ad} için bu konuda bilgi bulunmamaktadır."
            cikti["kaynaklar"] = []
            cikti["banka_uyusmazligi_reddi"] = True

    # Saf korpus-yoklugu cevabini tek tutarli kurumsal kaliba oturt: sorudaki
    # tutarin yankilanmasini da onler. Bilgi iceren karma cevaplara dokunulmaz
    # (_saf_korpus_reddi_mi korumalari).
    if (cikti.get("yol") == "rag" and not cikti.get("banka_uyusmazligi_reddi")
            and _saf_korpus_reddi_mi(cikti.get("cevap"))):
        cikti["cevap"] = "Verilen kaynaklarda bu konuda bilgi bulunmamaktadır."
        cikti["kaynaklar"] = []
        cikti["standart_red"] = True

    # Model bilgiyi bulamadigini soyluyorsa kaynak gostermeyelim.
    if reddetti_mi(cikti.get("cevap")):
        cikti["kaynaklar"] = []
        cikti["kaynak_temizlendi"] = True

    cikti["sure_sn"] = round(time.time() - t0, 2)
    return cikti
