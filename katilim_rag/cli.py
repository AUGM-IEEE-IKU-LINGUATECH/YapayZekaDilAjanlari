# -*- coding: utf-8 -*-
"""Terminal arayuzu.

    python -m katilim_rag.cli                      # etkilesimli
    python -m katilim_rag.cli -s "soru"            # tek soru
    python -m katilim_rag.cli -s "soru" --detay    # kaynak/chunk detayi
    python -m katilim_rag.cli -s "soru" --zorla rag
"""
import argparse, json
from . import boru, llm


def yaz(c, detay=False):
    print(f"\n[{c['yol'].upper()}] {c['sure_sn']}sn")
    print("-" * 62)
    print(c["cevap"])
    if c.get("kaynaklar"):
        print("-" * 62 + "\nKaynaklar:")
        for k in c["kaynaklar"][:5]:
            print(f"  • {k.get('baslik','')[:62]}\n    {k.get('url','')}")
    if detay and c.get("chunklar"):
        print("-" * 62 + f"\nAday: {c.get('aday_sayisi')} | Filtre: {c.get('filtre')}")
        for ch in c["chunklar"]:
            print(f"  [{ch['skor']:.3f}] {ch['chunk_id']}  {ch['icerik'][:110]}…")
    print()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("-s", "--soru")
    ap.add_argument("--detay", action="store_true")
    ap.add_argument("--zorla", choices=["sql", "rag"])
    ap.add_argument("-k", type=int, default=6)
    ap.add_argument("--llmsiz", action="store_true", help="LLM'i atla, ham baglami goster")
    a = ap.parse_args()

    ok, mesaj = llm.uygun_mu()
    if not ok and not a.llmsiz:
        print(f"UYARI: {mesaj}\n(--llmsiz ile LLM olmadan retrieval'i test edebilirsin)\n")

    if a.soru:
        yaz(boru.cevapla(a.soru, k=a.k, llm_kullan=not a.llmsiz, zorla=a.zorla), a.detay)
        return

    print("Katılım Bankacılığı Asistanı — çıkmak için 'q'\n")
    while True:
        try:
            q = input("> ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if q.lower() in {"q", "quit", "cikis", "çıkış"}:
            break
        if q:
            yaz(boru.cevapla(q, k=a.k, llm_kullan=not a.llmsiz, zorla=a.zorla), a.detay)


if __name__ == "__main__":
    main()
