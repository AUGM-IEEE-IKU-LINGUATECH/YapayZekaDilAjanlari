# -*- coding: utf-8 -*-
"""Retrieval: metadata filtresi -> vektor arama -> rerank -> cesitlilik -> top-k.

Modeller tembel yuklenir (ilk cagrida), boylece SQL yolu icin GPU bosa harcanmaz.
"""
import json, math, re
from collections import Counter
from functools import lru_cache
from .config import (CHROMA_YOLU, KOLEKSIYON, EMBED_MODEL, RERANK_MODEL, SORGU_CIHAZ,
                     RERANK_CIHAZ, RERANK_MAXLEN,
                     TOP_K_ARAMA, TOP_K_CEVAP, DOC_BASINA_MAX, RERANK_AKTIF,
                     MIN_SKOR, MIN_VEKTOR_SKOR, GORELI_BANT, LISTE_SAYFASI_HARIC,
                     RERANK_TABAN, RERANK_BANT)
from .analiz import soruyu_coz, fold
from .config import CHUNKS_JSONL


@lru_cache(maxsize=1)
def _gomme():
    from sentence_transformers import SentenceTransformer
    return SentenceTransformer(EMBED_MODEL, device=SORGU_CIHAZ)


@lru_cache(maxsize=1)
def _reranker():
    from sentence_transformers import CrossEncoder
    try:
        return CrossEncoder(RERANK_MODEL, device=RERANK_CIHAZ, max_length=RERANK_MAXLEN)
    except Exception as e:                       # VRAM yetmedi / cihaz yok
        print(f"[uyari] reranker {RERANK_CIHAZ} yuklenemedi ({e}); CPU'ya dusuluyor.")
        return CrossEncoder(RERANK_MODEL, device="cpu", max_length=RERANK_MAXLEN)


@lru_cache(maxsize=1)
def _koleksiyon():
    import chromadb
    client = chromadb.PersistentClient(path=str(CHROMA_YOLU),
                                      settings=chromadb.Settings(anonymized_telemetry=False))
    return client.get_collection(KOLEKSIYON)




# --------------------------------------------------------------- kelime tabanli yedek
# Anlamsal arama nadir ozel isimlerde (Bellona, Istikbal) isabetsiz kalabiliyor.
# Vektor bos dondugunde devreye girer. Turkce katlama: "Istikbal" ~ "İstikbal".
DURAK = set("""ve veya ile için gibi daha çok az var yok mi mı mu mü ne nedir nasil nasıl
hangi hangisi kac kaç bir bu şu o da de ki den dan tan ten olan olarak
kampanya kampanyasi kampanyası banka bankasi bankası katilim katılım""".split())


@lru_cache(maxsize=1)
def _sozluk():
    kayitlar, dizin = [], {}
    with CHUNKS_JSONL.open(encoding="utf-8") as f:
        for i, satir in enumerate(f):
            c = json.loads(satir)
            kayitlar.append(c)
            for k in set(re.findall(r"\w{3,}", fold(c["content"]))) - DURAK:
                dizin.setdefault(k, []).append(i)
    return kayitlar, dizin


def kelime_ara(soru: str, k: int) -> list[dict]:
    """IDF agirlikli sozcuksel arama. Nadir terimin BASLIKTA gecmesi ZORUNLU:
    govdede gecen ortak kelime belgeyle ilgiyi gostermez; gevsek birakilinca
    korpusta olmayan konulara da sonuc donuyor ve model uydurmaya zorlaniyordu."""
    kayitlar, dizin = _sozluk()
    n = len(kayitlar)
    terimler = [t for t in set(re.findall(r"\w{3,}", fold(soru))) - DURAK if t in dizin]
    if not terimler:
        return []
    esik_df = max(25, int(n * 0.02))
    nadir = {t for t in terimler if len(dizin[t]) <= esik_df}
    skor = Counter()
    for t in terimler:
        w = math.log(n / (1 + len(dizin[t])))
        if w <= 0:
            continue
        for i in dizin[t]:
            skor[i] += w * w
    basligta = []
    for i in list(skor):
        bas = fold(kayitlar[i]["metadata"].get("baslik", ""))
        if any(t in bas for t in nadir):
            skor[i] *= 4
            basligta.append(i)
    if not basligta:
        return []
    skor = Counter({i: skor[i] for i in basligta})
    en = max(skor.values())
    out = []
    for i, sk in skor.most_common(k * 2):
        c = kayitlar[i]
        out.append({"chunk_id": c["chunk_id"], "icerik": c["content"],
                    "metadata": c["metadata"], "mesafe": None,
                    "vektor_skor": round(sk / en, 3)})
    return out


def filtre_kur(slot: dict) -> dict | None:
    """Slotlardan Chroma where filtresi. Cok darsa None doner (arama genis kalir)."""
    kosul = []
    if slot["bankalar"]:
        kosul.append({"banka_kodu": {"$in": slot["bankalar"]}})
    if slot["aktiflik"] == "aktif":
        # kampanya disi belgeler "surekli" — onlari da birak
        kosul.append({"gecerlilik_durumu": {"$in": ["aktif", "surekli"]}})
    elif slot["aktiflik"] == "suresi_dolmus":
        kosul.append({"gecerlilik_durumu": "suresi_dolmus"})
    if LISTE_SAYFASI_HARIC:
        kosul.append({"rag_oncelik": {"$ne": "dusuk"}})
    if not kosul:
        return None
    return kosul[0] if len(kosul) == 1 else {"$and": kosul}


def _doc_id(a: dict) -> str:
    """Metadata'da doc_id yoksa chunk_id'den turet ('<doc_id>__cNN' formati).

    Eski index'lerde metadata.doc_id bos kalmis olabilir; bu durumda cesitlilik
    filtresi tum chunk'lari tek belge sanip top-k'yi 1-2 sonuca dusurur.
    """
    d = (a.get("metadata") or {}).get("doc_id") or ""
    if d:
        return d
    cid = a.get("chunk_id") or ""
    return cid.rsplit("__c", 1)[0] if "__c" in cid else cid


def cesitlilik_uygula(adaylar: list[dict], doc_basina: int, k: int) -> list[dict]:
    """Ayni belgeden gelen chunk sayisini sinirla — tek sayfa top-k'yi doldurmasin."""
    sayac, secilen = {}, []
    for a in adaylar:
        d = _doc_id(a)
        if sayac.get(d, 0) >= doc_basina:
            continue
        sayac[d] = sayac.get(d, 0) + 1
        secilen.append(a)
        if len(secilen) >= k:
            break
    return secilen


def ara(soru: str, k: int = TOP_K_CEVAP, k_arama: int = TOP_K_ARAMA,
        rerank: bool = RERANK_AKTIF, doc_basina: int = DOC_BASINA_MAX,
        filtre_kullan: bool = True, gecmis: list[dict] | None = None) -> dict:
    slot = soruyu_coz(soru, gecmis=gecmis)
    kol = _koleksiyon()
    where = filtre_kur(slot) if filtre_kullan else None

    arama_metni = slot.get("arama_metni") or soru
    v = _gomme().encode([arama_metni], normalize_embeddings=True)[0].tolist()
    ham = kol.query(query_embeddings=[v], n_results=k_arama, where=where,
                    include=["documents", "metadatas", "distances"])

    adaylar = [{"chunk_id": i, "icerik": d, "metadata": m, "mesafe": ms,
                "vektor_skor": 1 - ms}
               for i, d, m, ms in zip(ham["ids"][0], ham["documents"][0],
                                      ham["metadatas"][0], ham["distances"][0])]

    # filtre hicbir sey dondurmediyse filtresiz tekrar dene
    if not adaylar and where is not None:
        return ara(soru, k, k_arama, rerank, doc_basina, filtre_kullan=False, gecmis=gecmis)

    # Alaka kontrolu: once "hic alakali sonuc var mi" (en iyi eslesmeye bak),
    # sonra "en iyiden cok geride kalanlari ele".
    if adaylar and MIN_VEKTOR_SKOR > 0:
        en_iyi = max(a["vektor_skor"] for a in adaylar)
        if en_iyi < MIN_VEKTOR_SKOR:
            adaylar = []                       # korpusta ilgili icerik yok
        elif GORELI_BANT > 0:
            adaylar = [a for a in adaylar if a["vektor_skor"] >= en_iyi - GORELI_BANT]

    if rerank and adaylar:
        skor = _reranker().predict([(soru, a["icerik"]) for a in adaylar])
        for a, s in zip(adaylar, skor):
            a["rerank_skor"] = float(s)
        adaylar.sort(key=lambda a: a["rerank_skor"], reverse=True)
        adaylar = [a for a in adaylar if a["rerank_skor"] >= MIN_SKOR]
        # Rerank alaka kontrolu — vektor esiginin ayni mantigi, daha guvenilir skorla:
        # once "hic alakali sonuc var mi", sonra "en iyiden cok geride kalani ele".
        if adaylar and RERANK_TABAN > 0:
            en_iyi = adaylar[0]["rerank_skor"]
            if en_iyi < RERANK_TABAN:
                adaylar = []                       # korpusta karsiligi yok
            elif RERANK_BANT > 0:
                adaylar = [a for a in adaylar if a["rerank_skor"] >= en_iyi - RERANK_BANT]

    yontem = "vektor"
    if not adaylar:
        adaylar = kelime_ara(arama_metni, k)
        yontem = "kelime" if adaylar else "bos"

    secilen = cesitlilik_uygula(adaylar, doc_basina, k)
    return {"slot": slot, "filtre": where, "aday_sayisi": len(adaylar),
            "yontem": yontem, "sonuclar": secilen}


def veritabani_baglami_olustur(slot: dict) -> str:
    """RAG icin veritabanindaki kesin oran ve urun bilgilerini baglama ekler (Structured Grounding)."""
    if not slot or not (slot.get("bankalar") or slot.get("urunler")):
        return ""

    import sqlite3
    from .config import DB_YOLU
    from .sql_arac import URUN_ETIKET

    kosullar = ["1=1"]
    par = []
    if slot.get("bankalar"):
        kosullar.append(f"banka_kodu IN ({','.join('?' * len(slot['bankalar']))})")
        par += slot["bankalar"]
    if slot.get("urunler"):
        kosullar.append(f"urun_tipi IN ({','.join('?' * len(slot['urunler']))})")
        par += slot["urunler"]
    kosullar.append("belge_turu != 'liste_sayfasi'")

    sql = (f"SELECT banka_adi, urun_tipi, MAX(vade_ay_max) vade, MIN(kar_payi_orani) oran, "
           f"MAX(tutar_max) tutar, GROUP_CONCAT(DISTINCT tahsis_ucreti) tahsis, "
           f"GROUP_CONCAT(DISTINCT hedef_kitle) hedef_kitle "
           f"FROM urunler WHERE {' AND '.join(kosullar)} "
           f"GROUP BY banka_kodu, urun_tipi ORDER BY banka_adi")

    try:
        with sqlite3.connect(DB_YOLU) as c:
            c.row_factory = sqlite3.Row
            satirlar = [dict(r) for r in c.execute(sql, par)]
    except Exception:
        return ""

    if not satirlar:
        return ""

    blok = ["[DOĞRULANMIŞ VERİTABANI VE RESMİ ORAN BİLGİSİ (ESAS ALINACAK KESİN DEĞERLER)]"]
    for r in satirlar:
        oran_str = f"%{r['oran']}" if r['oran'] is not None else "Belirtilmemiş"
        tahsis_str = "%0.50" if r.get('tahsis') and '0.50' in str(r.get('tahsis')) else (r.get('tahsis') or '%0.50')
        hk_ham = r.get('hedef_kitle') or 'Yeni Müşterilere Özel, Mevcut Müşterilere Özel, Maaş Müşterilerine Özel'
        hk_parcalar = [p.strip() for p in hk_ham.split(',') if p.strip()]
        hk_temiz = ", ".join(dict.fromkeys(hk_parcalar))

        utipi_ad = URUN_ETIKET.get(r['urun_tipi'], r['urun_tipi'])
        blok.append(
            f"• {r['banka_adi']} | {utipi_ad}:\n"
            f"  - Kesin Kâr Payı Oranı: {oran_str}\n"
            f"  - Azami Vade: {r['vade'] or '-'} Ay\n"
            f"  - Tahsis Ücreti: {tahsis_str}\n"
            f"  - Hedef Kitle: {hk_temiz}"
        )
    return "\n".join(blok)


def baglami_metne_cevir(sonuclar: list[dict], slot: dict | None = None) -> str:
    """Chunk'lari ve dogrulanmis veritabani oranlarini LLM promptuna girecek bloklara cevirir."""
    db_metni = veritabani_baglami_olustur(slot) if slot else ""
    ETIKET = {"suresi_dolmus": "Sona Ermiş",
              "aktif": "Aktif", "bilinmiyor": "", "surekli": "Sürekli"}
    blok = []
    if db_metni:
        blok.append(db_metni)
    for i, r in enumerate(sonuclar, 1):
        m = r["metadata"]
        durum = ETIKET.get(m.get("gecerlilik_durumu", ""), "")
        bitis = f" | Bitiş Tarihi: {m['kampanya_bitis']}" if m.get("kampanya_bitis") else ""
        blok.append(f"[KAYNAK {i}] {m.get('banka_adi','')} | {m.get('baslik','')}{bitis}\n"
                    f"Durum: {durum}\nURL: {m.get('kaynak_url','')}\n{r['icerik']}")
    return "\n\n".join(blok)
