# -*- coding: utf-8 -*-
"""Tum ayarlar tek yerde. Ortam degiskeni ile ezilebilir."""
import os
from pathlib import Path

KOK = Path(__file__).resolve().parent.parent
VERI = Path(os.getenv("KATILIM_VERI", KOK / "veri"))

# --- veri dosyalari
CHUNKS_JSONL = VERI / "rag_chunks.jsonl"
DB_YOLU      = VERI / "katilim.db"
CHROMA_YOLU  = VERI / "chroma"
KOLEKSIYON   = "katilim_bankaciligi"

# --- modeller
EMBED_MODEL    = os.getenv("EMBED_MODEL", "BAAI/bge-m3")
RERANK_MODEL   = os.getenv("RERANK_MODEL", "BAAI/bge-reranker-v2-m3")
OLLAMA_URL     = os.getenv("OLLAMA_URL", "http://localhost:11434")
LLM_MODEL      = os.getenv("LLM_MODEL", "qwen2.5:7b-instruct")
# Model bellekten atilmasin: her istekle gonderilir, servis ayarina bagimli degil.
KEEP_ALIVE     = os.getenv("OLLAMA_KEEP_ALIVE", "30m")
CIHAZ          = os.getenv("CIHAZ", "cuda")          # cuda | cpu (indexleme)
# Sorgu aninda gomme modeli nerede calissin? 8 GB VRAM'de LLM ile cakisiyor;
# tek sorgu gommesi CPU'da da hizli (~0.1 sn), VRAM'i LLM'e birakmak daha iyi.
# NOT: CIHAZ'a baglamiyoruz artik — indexleme cuda'da kalsin (toplu is, hizli
# olsun), ama sorgu varsayilan olarak cpu'da calissin (RTX 4060 8GB + 7B LLM
# ayni anda GPU'da sigmiyor).
SORGU_CIHAZ    = os.getenv("SORGU_CIHAZ", "cpu")

# --- retrieval parametreleri (test sisteminde bunlari tarayacagiz)
# Reranker CPU'da her adayi tek tek puanliyor (GPU LLM'e ayrildi): 30 aday ~20sn,
# 12 aday ~6sn. Vektor siralamasi ilk 12'de dogru chunk'i buyuk olcude yakaliyor.
TOP_K_ARAMA    = int(os.getenv("TOP_K_ARAMA", 12))   # vektor aramasindan cekilen
TOP_K_CEVAP    = int(os.getenv("TOP_K_CEVAP", 8))    # LLM'e verilen
DOC_BASINA_MAX = int(os.getenv("DOC_BASINA_MAX", 2)) # ayni belgeden en fazla kac chunk
RERANK_AKTIF   = os.getenv("RERANK_AKTIF", "1") == "1"
# Reranker gomme modelinden AYRI cihazda calisir. Gomme CPU'da (tek cumle, ucuz),
# reranker GPU'da (12 aday x uzun metin, CPU'da ~60 sn suruyordu). VRAM yetmezse
# yukleme sirasinda otomatik CPU'ya duser.
RERANK_CIHAZ   = os.getenv("RERANK_CIHAZ", CIHAZ)
# 1024 token cogu chunk icin gereksiz: chunk ortalamasi ~900 karakter (~300 token).
RERANK_MAXLEN  = int(os.getenv("RERANK_MAXLEN", 512))
MIN_SKOR       = float(os.getenv("MIN_SKOR", "0.0")) # rerank skoru mutlak esigi
# Rerank skoru, vektor benzerliginden cok daha iyi bir alaka gostergesi.
# Gozlem: dogru cevaplanan soruda en iyi skor ~1.00; korpusta karsiligi olmayan
# soruda ~0.22-0.30. Vektor esigi bunlari geciriyor, sonuc olarak reddetme
# cevaplarinin altinda alakasiz kaynaklar listeleniyordu.
RERANK_TABAN   = float(os.getenv("RERANK_TABAN", "0.30"))  # en iyi bunun altindaysa sonuc yok
RERANK_BANT    = float(os.getenv("RERANK_BANT", "0.45"))   # en iyiden bu kadar geride kalani ele
# Alaka kontrolu MUTLAK degil GORELI yapilir.
#   TABAN : en iyi eslesme bunun altindaysa korpusta ilgili icerik yok say.
#   BANT  : en iyi eslesmeden bu kadar geride kalan chunk'lar elenir.
# Mutlak esik (tek bir sayinin altini ele) meshru sorulari da eliyordu:
# soru tarzina gore skorlar 0.55-0.80 arasinda geziniyor.
MIN_VEKTOR_SKOR = float(os.getenv("MIN_VEKTOR_SKOR", "0.55"))   # taban
GORELI_BANT     = float(os.getenv("GORELI_BANT", "0.15"))
LISTE_SAYFASI_HARIC = True                            # rag_oncelik=dusuk olanlari eleme

# --- uretim
MAX_TOKEN      = int(os.getenv("MAX_TOKEN", 4096))
# 0.0 = deterministik: ayni soruya hep ayni cevap. Olcumler tekrarlanabilir,
# demo ongorulebilir olur. Yaraticilik gerektiren bir gorev degil.
SICAKLIK       = float(os.getenv("SICAKLIK", "0.0"))
# 15 chunk + sistem promptu Ollama'nin varsayilan baglam penceresini (genelde
# 2048-4096) tasabilir; asarsa Ollama sessizce eski baglami kirpar. 8B model +
# 8192 ctx, 8GB VRAM'de (SORGU_CIHAZ=cpu ile GPU bosaldigi icin) makul sinirda.
NUM_CTX        = int(os.getenv("NUM_CTX", 8192))

BANKALAR = {
    "kuveyt_turk": "Kuveyt Türk", "ziraat_katilim": "Ziraat Katılım",
    "albaraka": "Albaraka Türk", "turkiye_finans": "Türkiye Finans",
    "vakif_katilim": "Vakıf Katılım", "emlak_katilim": "Türkiye Emlak Katılım",
    "hayat_finans": "Hayat Finans", "tom_katilim": "T.O.M. Katılım",
    "dunya_katilim": "Dünya Katılım", "adil_katilim": "Adil Katılım",
}