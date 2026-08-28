# -*- coding: utf-8 -*-
"""Retrieval teshisi: 30 adayin doc_id'lerini ve cesitlilik filtresinin ne yaptigini gosterir.

    py teshis.py
    py teshis.py -s "başka bir soru"
"""
import argparse, collections, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
for _a in (sys.stdout, sys.stderr):
    try:
        _a.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

ap = argparse.ArgumentParser()
ap.add_argument("-s", "--soru", default="Katılma hesabı nasıl işliyor")
a = ap.parse_args()

from katilim_rag import getir, config

print("=" * 62)
print("AYARLAR")
print("=" * 62)
for k in ["TOP_K_ARAMA", "TOP_K_CEVAP", "DOC_BASINA_MAX", "RERANK_AKTIF",
          "MIN_SKOR", "LISTE_SAYFASI_HARIC", "SORGU_CIHAZ", "CIHAZ"]:
    print(f"  {k:22s} = {getattr(config, k, '(YOK)')}")

print("\n  yama yuklendi mi :", hasattr(getir, "_doc_id"))

print("\n" + "=" * 62)
print("HAM ARAMA (cesitlilik filtresi UYGULANMADAN)")
print("=" * 62)

slot = getir.soruyu_coz(a.soru)
kol = getir._koleksiyon()
where = getir.filtre_kur(slot)
print(f"  filtre: {where}")

v = getir._gomme().encode([a.soru], normalize_embeddings=True)[0].tolist()
ham = kol.query(query_embeddings=[v], n_results=config.TOP_K_ARAMA, where=where,
                include=["documents", "metadatas", "distances"])

adaylar = [{"chunk_id": i, "icerik": d, "metadata": m, "mesafe": ms, "vektor_skor": 1 - ms}
           for i, d, m, ms in zip(ham["ids"][0], ham["documents"][0],
                                  ham["metadatas"][0], ham["distances"][0])]
print(f"  donen aday sayisi: {len(adaylar)}")

print("\n  ilk 12 aday:")
for x in adaylar[:12]:
    md = x["metadata"]
    print(f"    [{x['vektor_skor']:.3f}] chunk={x['chunk_id']}")
    print(f"            metadata.doc_id = {md.get('doc_id')!r}"
          f" | turetilen = {getir._doc_id(x)!r}" if hasattr(getir, "_doc_id")
          else f"            metadata.doc_id = {md.get('doc_id')!r}")

sayim = collections.Counter(
    (getir._doc_id(x) if hasattr(getir, "_doc_id") else x["metadata"].get("doc_id", ""))
    for x in adaylar)
print(f"\n  30 aday kac farkli belgeden geliyor: {len(sayim)}")
for d, n in sayim.most_common(8):
    print(f"    {n:2d} chunk  <- {d!r}")

print("\n" + "=" * 62)
print("CESITLILIK FILTRESI SONRASI")
print("=" * 62)
sec = getir.cesitlilik_uygula(adaylar, config.DOC_BASINA_MAX, config.TOP_K_CEVAP)
print(f"  secilen: {len(sec)} (hedef {config.TOP_K_CEVAP})")
for x in sec:
    print(f"    {x['chunk_id']}")

print("\n" + "=" * 62)
print("TAM ara() CIKTISI")
print("=" * 62)
r = getir.ara(a.soru)
print(f"  aday_sayisi = {r['aday_sayisi']} | sonuc = {len(r['sonuclar'])}")
for x in r["sonuclar"]:
    print(f"    {x['chunk_id']}  skor={x.get('rerank_skor', x.get('vektor_skor')):.3f}")
