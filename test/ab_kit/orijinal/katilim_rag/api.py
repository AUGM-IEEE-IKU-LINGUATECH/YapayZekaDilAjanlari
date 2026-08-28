# -*- coding: utf-8 -*-
"""FastAPI servisi: chatbot + dashboard endpointleri + statik arayuz.

    uvicorn katilim_rag.api:app --reload --port 8000
"""
import sqlite3
from pathlib import Path
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from . import boru, llm, sql_arac, getir
from .config import DB_YOLU, TOP_K_CEVAP, LLM_MODEL, EMBED_MODEL

app = FastAPI(title="Katılım Bankacılığı RAG", version="1.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

ARAYUZ = Path(__file__).parent / "arayuz.html"
# Chart.js yerel dosyadan servis edilir: sartname 5.9 on-premise, sifir dis baglanti.
STATIK = Path(__file__).parent / "statik"
if STATIK.exists():
    app.mount("/statik", StaticFiles(directory=str(STATIK)), name="statik")


class Soru(BaseModel):
    soru: str
    k: int = TOP_K_CEVAP
    zorla: str | None = None      # 'sql' | 'rag' | None
    gecmis: list[dict] | None = None


def _sorgu(sql: str, par=()):
    with sqlite3.connect(DB_YOLU) as c:
        c.row_factory = sqlite3.Row
        return [dict(r) for r in c.execute(sql, par)]


@app.get("/", response_class=HTMLResponse)
def anasayfa():
    if ARAYUZ.exists():
        return ARAYUZ.read_text(encoding="utf-8")
    return "<h1>Katılım RAG</h1><p>arayuz.html bulunamadı. /docs adresini kullanın.</p>"


@app.get("/saglik")
def saglik():
    ollama_ok, mesaj = llm.uygun_mu()
    try:
        n_chunk = getir._koleksiyon().count()
    except Exception as e:
        n_chunk, mesaj = 0, f"{mesaj} | Chroma: {e}"
    return {"ollama": ollama_ok, "mesaj": mesaj, "chunk_sayisi": n_chunk,
            "llm_model": LLM_MODEL, "embed_model": EMBED_MODEL,
            "kayit_sayisi": _sorgu("SELECT COUNT(*) n FROM urunler")[0]["n"]}


@app.post("/sor")
def sor(s: Soru):
    if not s.soru.strip():
        raise HTTPException(400, "soru boş olamaz")
    return boru.cevapla(s.soru, k=s.k, zorla=s.zorla, gecmis=s.gecmis)


@app.post("/sor/akis")
def sor_akis(s: Soru):
    """Token token akitir — chat arayuzu icin."""
    bulgu = None if s.zorla == "rag" else sql_arac.calistir(s.soru, gecmis=s.gecmis)
    if bulgu:
        akis = llm.sql_cevap(s.soru, sql_arac.bulguyu_metne_cevir(bulgu), gecmis=s.gecmis, akis=True)
    else:
        a = getir.ara(s.soru, k=s.k, gecmis=s.gecmis)
        if not a["sonuclar"]:
            akis = iter(["Elimdeki kaynaklarda bu soruya dair bilgi bulamadım."])
        else:
            akis = llm.rag_cevap(s.soru, getir.baglami_metne_cevir(a["sonuclar"], slot=a["slot"]), gecmis=s.gecmis, akis=True)
    return StreamingResponse(akis, media_type="text/plain; charset=utf-8")


# ----------------------------------------------------------------- dashboard

@app.get("/panel/kriterler")
def panel_kriterler(urun_tipi: str | None = None):
    """Sartname 5.7: bes karsilastirma kriteri."""
    k = ["belge_turu!='liste_sayfasi'"]; par = []
    if urun_tipi:
        k.append("urun_tipi=?"); par.append(urun_tipi)
    w = " AND ".join(k)
    return {
        "en_dusuk_kar_payi": _sorgu(
            f"SELECT banka_adi,baslik,kar_payi_orani deger,kaynak_url FROM urunler "
            f"WHERE {w} AND CAST(kar_payi_orani AS REAL)>0 ORDER BY deger ASC LIMIT 5", par),
        "en_yuksek_odul": _sorgu(
            f"SELECT banka_adi,baslik,CAST(odul_miktari AS REAL) deger,kaynak_url FROM urunler "
            f"WHERE {w} AND CAST(odul_miktari AS REAL)>0 "
            f"ORDER BY deger DESC LIMIT 5", par),
        "en_uzun_vade": _sorgu(
            f"SELECT banka_adi,baslik,vade_ay_max deger,kaynak_url FROM urunler "
            f"WHERE {w} AND vade_ay_max IS NOT NULL ORDER BY deger DESC LIMIT 5", par),
        "en_dusuk_masraf": _sorgu(
            f"SELECT banka_adi,baslik,COALESCE(NULLIF(tahsis_ucreti,''),masraf_bilgisi) deger,"
            f"kaynak_url FROM urunler WHERE {w} AND "
            f"(tahsis_ucreti LIKE '%cretsiz%' OR masraf_bilgisi LIKE 'Masrafs%') LIMIT 5", par),
        "en_yuksek_indirim": _sorgu(
            f"SELECT banka_adi,baslik,indirim_orani deger,kaynak_url FROM urunler "
            f"WHERE {w} AND indirim_orani IS NOT NULL AND indirim_orani<=100 "
            f"ORDER BY deger DESC LIMIT 5", par),
    }


@app.get("/panel/hedef_kitle")
def panel_hedef_kitle():
    """Sartname 5.3: hedef kitle dagilimi (boolean kolonlardan)."""
    r = _sorgu("""SELECT SUM(yeni_musteri) yeni_musteri, SUM(mevcut_musteri) mevcut_musteri,
        SUM(maas_musterisi) maas_musterisi, SUM(kobi_esnaf) kobi_esnaf FROM urunler""")[0]
    return [{"hedef_kitle": k, "n": v or 0} for k, v in
            sorted(r.items(), key=lambda x: -(x[1] or 0))]


@app.get("/panel/kampanya_turleri")
def panel_kampanya_turleri():
    """Sartname 5.4: kampanya turu dagilimi."""
    return _sorgu("""SELECT kampanya_turu,COUNT(*) n FROM urunler
        WHERE belge_turu='kampanya' AND kampanya_turu!='' GROUP BY 1 ORDER BY n DESC""")

@app.get("/panel/ozet")
def panel_ozet():
    return {
        "toplam_kayit": _sorgu("SELECT COUNT(*) n FROM urunler")[0]["n"],
        "banka_sayisi": _sorgu("SELECT COUNT(DISTINCT banka_kodu) n FROM urunler")[0]["n"],
        "aktif_kampanya": _sorgu("SELECT COUNT(*) n FROM urunler WHERE gecerlilik='aktif'")[0]["n"],
        "suresi_dolmus": _sorgu("SELECT COUNT(*) n FROM urunler WHERE gecerlilik='suresi_dolmus'")[0]["n"],
        "kar_payi_veri": _sorgu("SELECT COUNT(kar_payi_orani) n FROM urunler")[0]["n"],
    }


@app.get("/panel/bankalar")
def panel_bankalar():
    return _sorgu("""SELECT banka_adi, banka_kodu, COUNT(*) kayit,
        SUM(gecerlilik='aktif') aktif_kampanya,
        MAX(vade_ay_max) max_vade, MIN(kar_payi_orani) min_oran
        FROM urunler WHERE belge_turu!='liste_sayfasi'
        GROUP BY banka_kodu ORDER BY kayit DESC""")


@app.get("/panel/karsilastir")
def panel_karsilastir(urun_tipi: str = "konut"):
    return _sorgu("""SELECT banka_adi, MAX(vade_ay_max) vade, MIN(kar_payi_orani) oran,
        MAX(tutar_max) tutar, COUNT(*) kayit FROM urunler
        WHERE urun_tipi=? AND belge_turu!='liste_sayfasi'
        GROUP BY banka_kodu HAVING vade IS NOT NULL OR oran IS NOT NULL
        ORDER BY vade DESC""", (urun_tipi,))


@app.get("/panel/kampanyalar")
def panel_kampanyalar(banka: str | None = None, durum: str = "hepsi", urun_tipi: str | None = None, q: str | None = None, limit: int = 1000):
    k, p = ["belge_turu='kampanya'"], []
    if banka:
        k.append("banka_kodu=?"); p.append(banka)
    if urun_tipi and urun_tipi != "hepsi" and urun_tipi != "":
        k.append("urun_tipi=?"); p.append(urun_tipi)
    if durum == "aktif":
        k.append("gecerlilik IN ('aktif', 'bilinmiyor')")
    elif durum and durum != "hepsi":
        k.append("gecerlilik=?"); p.append(durum)
    if q and q.strip():
        k.append("(baslik LIKE ? OR kampanya_kosullari LIKE ?)")
        p.extend([f"%{q.strip()}%", f"%{q.strip()}%"])
    p.append(limit)
    return _sorgu(f"""SELECT banka_adi, baslik, urun_tipi, gecerlilik, kampanya_bitis, sektor, kaynak_url
        FROM urunler WHERE {' AND '.join(k)}
        ORDER BY CASE WHEN gecerlilik='aktif' THEN 1 WHEN gecerlilik='bilinmiyor' THEN 2 ELSE 3 END, kampanya_bitis DESC LIMIT ?""", p)


@app.get("/panel/urun_tipleri")
def panel_urun_tipleri():
    return _sorgu("""SELECT urun_tipi, COUNT(*) n FROM urunler
        WHERE belge_turu!='liste_sayfasi' GROUP BY urun_tipi ORDER BY n DESC""")
