# -*- coding: utf-8 -*-
"""Chunk'lari gomup Chroma'ya yazar. Bir kez calistirilir.

    python -m katilim_rag.index            # index kur
    python -m katilim_rag.index --bastan   # sifirdan kur
"""
import argparse, json, sys
from .config import (CHUNKS_JSONL, CHROMA_YOLU, KOLEKSIYON, EMBED_MODEL, CIHAZ)

# doc_id bilerek listede yok: chunk metadata'sinda bulunmadigi icin
# m.get("doc_id") -> None dondurur ve dogru degeri ezerdi.
DUZ_ALANLAR = ["banka_kodu", "banka_adi", "baslik", "belge_turu", "musteri_segmenti",
               "gecerlilik_durumu", "kampanya_bitis", "kaynak_url", "chunk_index",
               "rag_oncelik"]


def metadata_duzle(m: dict, doc_id: str) -> dict:
    """Chroma sadece str/int/float/bool kabul eder — liste ve dict'leri duzlestir."""
    d = {"doc_id": doc_id}
    for k in DUZ_ALANLAR:
        v = m.get(k)
        if isinstance(v, (str, int, float, bool)):
            d[k] = v
        elif v is None:
            d[k] = ""
    d["kategoriler"] = ",".join(m.get("urun_kategorileri", []))
    d["anahtar_kelimeler"] = ",".join(m.get("anahtar_kelimeler", []))
    s = m.get("sayisal_bilgiler", {})
    d["vade_ay_max"] = max(s.get("vade_ay") or [0]) or 0
    d["taksit_max"] = max(s.get("taksit_sayisi") or [0]) or 0
    d["doc_id"] = doc_id          # her zaman en sonda: ezilmesin
    return d


def main(bastan=False, yigin=64):
    import chromadb, gc, time, shutil
    from sentence_transformers import SentenceTransformer

    if not CHUNKS_JSONL.exists():
        sys.exit(f"{CHUNKS_JSONL} yok. rag_chunks.jsonl dosyasini veri/ altina koy.")
    kayitlar = [json.loads(l) for l in CHUNKS_JSONL.open(encoding="utf-8")]
    print(f"{len(kayitlar)} chunk okundu")

    print(f"gomme modeli yukleniyor: {EMBED_MODEL} ({CIHAZ})")
    model = SentenceTransformer(EMBED_MODEL, device=CIHAZ)

    if bastan and CHROMA_YOLU.exists():
        print(f"eski chroma dizini siliniyor: {CHROMA_YOLU}")
        shutil.rmtree(CHROMA_YOLU, ignore_errors=True)

    CHROMA_YOLU.mkdir(parents=True, exist_ok=True)
    ist = chromadb.PersistentClient(path=str(CHROMA_YOLU),
                                   settings=chromadb.Settings(anonymized_telemetry=False))
    kol = ist.get_or_create_collection(KOLEKSIYON, metadata={"hnsw:space": "cosine"})
    if kol.count() and not bastan:
        print(f"koleksiyonda zaten {kol.count()} kayit var. --bastan ile sifirla.")
        return

    texts = [c["embedding_text"] for c in kayitlar]
    print(f"GPU/CPU ile {len(texts)} chunk gomuluyor (batch_size={yigin})...")
    vektorler = model.encode(texts, batch_size=yigin, normalize_embeddings=True, show_progress_bar=True)
    print(f"Gomme tamamlandi (sekil: {vektorler.shape}). Chroma'ya yaziliyor...")

    kol.add(ids=[c["chunk_id"] for c in kayitlar],
            embeddings=vektorler.tolist(),
            documents=[c["content"] for c in kayitlar],
            metadatas=[metadata_duzle(c["metadata"], c["doc_id"]) for c in kayitlar])

    print(f"Koleksiyona eklendi ({len(kayitlar)} kayit), indeks senkronize ediliyor...")
    _sync_q = kol.query(query_embeddings=[vektorler[0].tolist()], n_results=1)
    del kol
    del ist
    gc.collect()
    time.sleep(1)
    print(f"bitti — koleksiyon basariyla diske yazildi ({CHROMA_YOLU})")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--bastan", action="store_true")
    ap.add_argument("--yigin", type=int, default=64)
    a = ap.parse_args()
    main(a.bastan, a.yigin)

