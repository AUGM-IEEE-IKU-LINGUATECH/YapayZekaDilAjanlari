#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""LinguaTech icin Windows, Linux ve macOS uyumlu kurulum araci.

Bu dosya proje kokunde calistirilir. Kurulum:
  * proje icinde yalitilmis bir .venv olusturur,
  * uyumlu ve tekrarlanabilir Python paketlerini kurar,
  * sorgu gommesi ve reranker modellerini onceden indirir,
  * hazir Chroma indeksini gercekten okuyarak dogrular,
  * bozuk/uyumsuz indeksi silmeden yedekleyip yeniden kurar,
  * SQL ve RAG yollarinda uctan uca saglik testi yapar.

Ollama isletim sistemi uygulamasidir; otomatik kurulmaz. Ollama kurulu ve
servisi calisiyorsa secilen model bu arac tarafindan indirilir.
"""
from __future__ import annotations

import argparse
import importlib.metadata
import json
import os
import platform
import shlex
import shutil
import sqlite3
import subprocess
import sys
import time
import urllib.request
from pathlib import Path


KOK = Path(__file__).resolve().parent
VENV = KOK / ".venv"
VERI = Path(os.getenv("KATILIM_VERI", str(KOK / "veri"))).expanduser().resolve()
CHROMA = VERI / "chroma"
KOLEKSIYON = "katilim_bankaciligi"
EMBED_MODEL = os.getenv("EMBED_MODEL", "BAAI/bge-m3")
RERANK_MODEL = os.getenv("RERANK_MODEL", "BAAI/bge-reranker-v2-m3")
VARSAYILAN_LLM = os.getenv("LLM_MODEL", "qwen2.5:7b-instruct")
GEREKEN_CHROMA = "0.6.3"

for _akis in (sys.stdout, sys.stderr):
    try:
        _akis.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


class KurulumHatasi(RuntimeError):
    pass


def baslik(metin: str) -> None:
    print(f"\n{'=' * 64}\n{metin}\n{'=' * 64}")


def bilgi(metin: str) -> None:
    print(f"  [BILGI] {metin}")


def tamam(metin: str) -> None:
    print(f"  [OK]    {metin}")


def uyari(metin: str) -> None:
    print(f"  [UYARI] {metin}")


def hata(metin: str) -> None:
    print(f"  [HATA]  {metin}")


def komut_metni(argv: list[str]) -> str:
    return subprocess.list2cmdline(argv) if os.name == "nt" else shlex.join(argv)


def calistir(
    argv: list[str],
    *,
    kritik: bool = True,
    ortam: dict[str, str] | None = None,
    zaman_asimi: int | None = None,
    yakala: bool = False,
) -> subprocess.CompletedProcess[str]:
    bilgi(f"$ {komut_metni(argv)}")
    try:
        sonuc = subprocess.run(
            argv,
            cwd=KOK,
            env=ortam,
            text=True,
            encoding="utf-8",
            errors="replace",
            capture_output=yakala,
            timeout=zaman_asimi,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        if kritik:
            raise KurulumHatasi(f"Komut zaman asimina ugradi: {komut_metni(argv)}") from exc
        return subprocess.CompletedProcess(argv, 124, "", "zaman asimi")
    if yakala:
        if sonuc.stdout.strip():
            print(sonuc.stdout.rstrip())
        if sonuc.returncode and sonuc.stderr.strip():
            print(sonuc.stderr.rstrip())
    if sonuc.returncode and kritik:
        raise KurulumHatasi(
            f"Komut basarisiz oldu (kod {sonuc.returncode}): {komut_metni(argv)}"
        )
    return sonuc


def argumanlar() -> argparse.Namespace:
    ap = argparse.ArgumentParser(
        description="LinguaTech'i temiz bir bilgisayarda tekrarlanabilir bicimde kurar."
    )
    ap.add_argument("--kontrol", action="store_true", help="indirme/degisiklik yapmadan durum denetimi")
    ap.add_argument("--tam", action="store_true", help="kontrolde gercek RAG aramasi da yap")
    ap.add_argument("--cpu", action="store_true", help="indeks olustururken GPU/MPS kullanma")
    ap.add_argument("--hizli", action="store_true", help="kurulum sonunda agir RAG testini atla")
    ap.add_argument("--offline", action="store_true", help="yalniz onbellekteki modelleri kullan")
    ap.add_argument("--indeksi-yenile", action="store_true", help="calisan indeksi de yedekleyip yeniden kur")
    ap.add_argument("--model", default=VARSAYILAN_LLM, help="Ollama model adi")
    ap.add_argument("--venv-ici", action="store_true", help=argparse.SUPPRESS)
    return ap.parse_args()


def python_uygun_mu() -> bool:
    v = sys.version_info
    return (3, 10) <= (v.major, v.minor) < (3, 13)


def venv_python() -> Path:
    return VENV / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def venv_hazirla(a: argparse.Namespace) -> None:
    hedef = venv_python()
    try:
        venv_icinde = Path(sys.prefix).resolve() == VENV.resolve()
    except Exception:
        venv_icinde = False
    if venv_icinde:
        return

    if hedef.exists():
        bilgi(f"Mevcut sanal ortam kullaniliyor: {hedef}")
    elif a.kontrol:
        raise KurulumHatasi(
            ".venv bulunamadi. Once 'python kur.py' (Linux/macOS: python3 kur.py) calistirin."
        )
    else:
        baslik("1/8 - YALITILMIS PYTHON ORTAMI")
        bilgi(f"Sanal ortam olusturuluyor: {VENV}")
        sonuc = calistir([sys.executable, "-m", "venv", str(VENV)], kritik=False, yakala=True)
        if sonuc.returncode:
            ek = ""
            if platform.system() == "Linux":
                ek = " Linux'ta once python3-venv paketini kurmaniz gerekebilir."
            raise KurulumHatasi(f".venv olusturulamadi.{ek}")

    yeni_argv = [str(hedef), str(Path(__file__).resolve()), *sys.argv[1:]]
    if "--venv-ici" not in yeni_argv:
        yeni_argv.append("--venv-ici")
    sonuc = subprocess.run(yeni_argv, cwd=KOK, check=False)
    raise SystemExit(sonuc.returncode)


def sistem_kontrolu() -> None:
    baslik("SISTEM KONTROLU")
    surum = platform.python_version()
    if python_uygun_mu():
        tamam(f"Python {surum} (desteklenen aralik: 3.10-3.12)")
    else:
        raise KurulumHatasi(
            f"Python {surum} desteklenmiyor. 64 bit Python 3.10, 3.11 veya 3.12 kurun."
        )
    if sys.maxsize <= 2**32:
        raise KurulumHatasi("32 bit Python desteklenmiyor; 64 bit Python kurun.")
    tamam(f"{platform.system()} {platform.release()} / {platform.machine()} / 64 bit")
    bos_gb = shutil.disk_usage(KOK).free / 1_000_000_000
    if bos_gb < 12:
        raise KurulumHatasi(f"Yalniz {bos_gb:.1f} GB bos alan var; en az 12 GB gerekli.")
    if bos_gb < 20:
        uyari(f"Bos alan {bos_gb:.1f} GB; 20 GB veya fazlasi onerilir.")
    else:
        tamam(f"Bos disk alani: {bos_gb:.1f} GB")


def bagimliliklari_kur() -> None:
    baslik("2/8 - PYTHON BAGIMLILIKLARI")
    gereksinim = KOK / "gereksinimler.txt"
    if not gereksinim.exists():
        raise KurulumHatasi(f"Eksik dosya: {gereksinim}")
    calistir([sys.executable, "-m", "pip", "install", "--upgrade", "pip", "setuptools", "wheel"])
    calistir([sys.executable, "-m", "pip", "install", "-r", str(gereksinim)])
    surum = importlib.metadata.version("chromadb")
    if surum != GEREKEN_CHROMA:
        raise KurulumHatasi(f"chromadb {surum} kuruldu; gereken surum {GEREKEN_CHROMA}.")
    tamam(f"Python paketleri kuruldu; chromadb {surum}")


def paket_kontrolu() -> bool:
    gereken = {
        "chromadb": "chromadb",
        "sentence-transformers": "sentence-transformers",
        "torch": "torch",
        "fastapi": "fastapi",
        "uvicorn": "uvicorn",
        "requests": "requests",
        "pandas": "pandas",
        "huggingface-hub": "huggingface-hub",
    }
    ok = True
    for etiket, dagitim in gereken.items():
        try:
            surum = importlib.metadata.version(dagitim)
            if dagitim == "chromadb" and surum != GEREKEN_CHROMA:
                hata(f"{etiket} {surum}; gereken {GEREKEN_CHROMA}")
                ok = False
            else:
                tamam(f"{etiket} {surum}")
        except importlib.metadata.PackageNotFoundError:
            hata(f"{etiket} kurulu degil")
            ok = False
    return ok


def model_onbellegi(model: str) -> bool:
    try:
        from huggingface_hub import snapshot_download

        snapshot_download(repo_id=model, local_files_only=True)
        return True
    except Exception:
        return False


def modelleri_hazirla(offline: bool) -> None:
    baslik("3/8 - YEREL RAG MODELLERI")
    from huggingface_hub import snapshot_download

    for model in (EMBED_MODEL, RERANK_MODEL):
        if model_onbellegi(model):
            tamam(f"Model onbellekte: {model}")
            continue
        if offline:
            raise KurulumHatasi(f"Offline modda model bulunamadi: {model}")
        bilgi(f"Model indiriliyor: {model}")
        try:
            snapshot_download(repo_id=model, local_files_only=False)
        except Exception as exc:
            raise KurulumHatasi(f"Model indirilemedi: {model}: {exc}") from exc
        if not model_onbellegi(model):
            raise KurulumHatasi(f"Model indirildi ancak yerel onbellekten acilamadi: {model}")
        tamam(f"Model hazir: {model}")


def veri_kontrolu() -> tuple[int, int]:
    db = VERI / "katilim.db"
    chunks = VERI / "rag_chunks.jsonl"
    arayuz = KOK / "katilim_rag" / "arayuz.html"
    for p in (db, chunks, arayuz):
        if not p.exists() or (p.is_file() and p.stat().st_size == 0):
            raise KurulumHatasi(f"Kritik dosya eksik veya bos: {p}")
        tamam(str(p.relative_to(KOK)) if p.is_relative_to(KOK) else str(p))
    try:
        with sqlite3.connect(db) as c:
            urun = c.execute("SELECT COUNT(*) FROM urunler").fetchone()[0]
            banka = c.execute("SELECT COUNT(DISTINCT banka_kodu) FROM urunler").fetchone()[0]
    except Exception as exc:
        raise KurulumHatasi(f"SQLite veritabani okunamadi: {exc}") from exc
    chunk = sum(1 for satir in chunks.open(encoding="utf-8") if satir.strip())
    tamam(f"SQLite: {urun} kayit / {banka} banka")
    tamam(f"RAG parcasi: {chunk}")
    return urun, chunk


def cihaz_sec(force_cpu: bool) -> str:
    if force_cpu:
        return "cpu"
    try:
        import torch

        if torch.cuda.is_available():
            return "cuda"
        mps = getattr(torch.backends, "mps", None)
        if mps is not None and mps.is_available():
            return "mps"
    except Exception:
        pass
    return "cpu"


def chroma_probe() -> tuple[bool, int, str]:
    if not CHROMA.exists() or not any(CHROMA.iterdir()):
        return False, 0, "indeks klasoru yok veya bos"
    kod = (
        "import chromadb;"
        f"c=chromadb.PersistentClient(path={json.dumps(str(CHROMA))},"
        "settings=chromadb.Settings(anonymized_telemetry=False));"
        f"k=c.get_collection({json.dumps(KOLEKSIYON)});"
        "n=k.count();assert n>0,'koleksiyon bos';k.get(limit=1);print(n)"
    )
    try:
        sonuc = subprocess.run(
            [sys.executable, "-c", kod],
            cwd=KOK,
            text=True,
            encoding="utf-8",
            errors="replace",
            capture_output=True,
            timeout=180,
            check=False,
        )
        if sonuc.returncode:
            son = (sonuc.stderr or sonuc.stdout or "bilinmeyen hata").strip().splitlines()
            return False, 0, son[-1] if son else "bilinmeyen hata"
        adet = int(sonuc.stdout.strip().splitlines()[-1])
        return True, adet, "okunuyor"
    except Exception as exc:
        return False, 0, f"{type(exc).__name__}: {exc}"


def chroma_yedekle() -> Path | None:
    if not CHROMA.exists():
        return None
    damga = time.strftime("%Y%m%d_%H%M%S")
    hedef = CHROMA.with_name(f"chroma_yedek_{damga}")
    sayac = 1
    while hedef.exists():
        hedef = CHROMA.with_name(f"chroma_yedek_{damga}_{sayac}")
        sayac += 1
    shutil.move(str(CHROMA), str(hedef))
    uyari(f"Eski indeks silinmedi; yedeklendi: {hedef.name}")
    return hedef


def chroma_hazirla(chunk_sayisi: int, cihaz: str, yenile: bool) -> None:
    baslik("6/8 - CHROMA VEKTOR INDEKSI")
    ok, adet, neden = chroma_probe()
    if ok and adet == chunk_sayisi and not yenile:
        tamam(f"Hazir indeks diskten okunuyor: {adet} kayit")
        return
    if ok and adet != chunk_sayisi:
        uyari(f"Indeks kaydi ({adet}) ile chunk sayisi ({chunk_sayisi}) farkli.")
    elif not ok:
        uyari(f"Hazir indeks kullanilamiyor: {neden}")
    chroma_yedekle()
    bilgi(f"Indeks yeniden olusturuluyor; cihaz={cihaz}. CPU'da 15-30 dakika surebilir.")
    ortam = os.environ.copy()
    ortam.update(
        {
            "CIHAZ": cihaz,
            "HF_HUB_OFFLINE": "1",
            "TRANSFORMERS_OFFLINE": "1",
            "HF_DATASETS_OFFLINE": "1",
        }
    )
    calistir([sys.executable, "-m", "katilim_rag.index"], ortam=ortam)
    ok, adet, neden = chroma_probe()
    if not ok or adet != chunk_sayisi:
        raise KurulumHatasi(
            f"Yeni Chroma indeksi dogrulanamadi: {neden}; kayit={adet}, beklenen={chunk_sayisi}"
        )
    tamam(f"Yeni indeks diskten okunuyor: {adet} kayit")


def ollama_modelleri() -> tuple[bool, list[str], str]:
    url = os.getenv("OLLAMA_URL", "http://localhost:11434").rstrip("/")
    try:
        with urllib.request.urlopen(f"{url}/api/tags", timeout=5) as r:
            veri = json.load(r)
        return True, [m.get("name", "") for m in veri.get("models", [])], ""
    except Exception as exc:
        return False, [], str(exc)


def model_var(modeller: list[str], hedef: str) -> bool:
    hedef = hedef.removesuffix(":latest")
    return any(m.removesuffix(":latest") == hedef for m in modeller)


def ollama_hazirla(model: str, offline: bool) -> bool:
    baslik("5/8 - OLLAMA VE DIL MODELI")
    cli = shutil.which("ollama")
    if not cli:
        hata("Ollama kurulu degil. https://ollama.com/download adresinden kurup bu komutu tekrar calistirin.")
        return False
    calisiyor, modeller, neden = ollama_modelleri()
    if not calisiyor:
        hata(f"Ollama servisine ulasilamadi: {neden}")
        bilgi("Ollama uygulamasini acin veya terminalde 'ollama serve' calistirin.")
        return False
    tamam("Ollama servisi calisiyor")
    if model_var(modeller, model):
        tamam(f"Dil modeli hazir: {model}")
        return True
    if offline:
        hata(f"Offline modda Ollama modeli bulunamadi: {model}")
        return False
    bilgi(f"Ollama modeli indiriliyor: {model}")
    sonuc = calistir([cli, "pull", model], kritik=False)
    calisiyor, modeller, _ = ollama_modelleri()
    if sonuc.returncode or not calisiyor or not model_var(modeller, model):
        hata(f"Ollama modeli indirilemedi: {model}")
        return False
    tamam(f"Dil modeli hazir: {model}")
    return True


def duman_testleri(rag: bool) -> None:
    baslik("7/8 - UCTAN UCA TESTLER")
    ortak = os.environ.copy()
    ortak.update(
        {
            "HF_HUB_OFFLINE": "1",
            "TRANSFORMERS_OFFLINE": "1",
            "HF_DATASETS_OFFLINE": "1",
            "SORGU_CIHAZ": "cpu",
            "RERANK_CIHAZ": "cpu",
            "CIHAZ": "cpu",
            "PYTHONDONTWRITEBYTECODE": "1",
        }
    )
    sql_kod = (
        "from katilim_rag import boru;"
        "r=boru.cevapla('En uzun vadeli konut finansmani hangi bankada?',llm_kullan=False);"
        "assert r.get('yol')=='sql' and r.get('cevap'),r;"
        "print('SQL yolu calisiyor')"
    )
    calistir([sys.executable, "-c", sql_kod], ortam=ortak, yakala=True, zaman_asimi=120)
    tamam("SQL yolu")
    if not rag:
        uyari("Agir RAG testi atlandi. Sonradan: python kur.py --kontrol --tam")
        return
    rag_kod = (
        "from katilim_rag.getir import ara;"
        "r=ara('Katilma hesabi nasil isler?',k=2);"
        "assert r.get('sonuclar'),r;"
        "print('RAG yolu calisiyor; yontem='+r.get('yontem','?')+'; sonuc='+str(len(r['sonuclar'])))"
    )
    calistir([sys.executable, "-c", rag_kod], ortam=ortak, yakala=True, zaman_asimi=900)
    tamam("Gomme modeli + Chroma sorgusu + reranker")


def kontrol(a: argparse.Namespace) -> int:
    sistem_kontrolu()
    baslik("PAKETLER")
    iyi = paket_kontrolu()
    baslik("MODELLER")
    for model in (EMBED_MODEL, RERANK_MODEL):
        if model_onbellegi(model):
            tamam(f"Yerel: {model}")
        else:
            hata(f"Onbellekte yok: {model}")
            iyi = False
    baslik("VERI")
    try:
        _, chunk = veri_kontrolu()
    except KurulumHatasi as exc:
        hata(str(exc))
        return 1
    baslik("CHROMA")
    ok, adet, neden = chroma_probe()
    if ok and adet == chunk:
        tamam(f"{adet} kayit diskten okunuyor")
    else:
        hata(f"Indeks sorunu: {neden}; kayit={adet}, beklenen={chunk}")
        iyi = False
    baslik("OLLAMA")
    o_ok, modeller, neden = ollama_modelleri()
    if o_ok and model_var(modeller, a.model):
        tamam(f"Ollama ve {a.model}")
    else:
        hata(f"Ollama/model hazir degil: {neden or a.model}")
        iyi = False
    if iyi:
        try:
            duman_testleri(rag=a.tam)
        except KurulumHatasi as exc:
            hata(str(exc))
            iyi = False
    baslik("KONTROL SONUCU")
    print("  SISTEM HAZIR" if iyi else "  EKSIK VEYA HATA VAR")
    return 0 if iyi else 1


def calistirma_komutu(model: str) -> str:
    py = venv_python()
    temel = f'"{py}" -m uvicorn katilim_rag.api:app --port 8000'
    if model == "qwen2.5:7b-instruct":
        return temel
    if os.name == "nt":
        return f'$env:LLM_MODEL="{model}"; {temel}'
    return f'LLM_MODEL={shlex.quote(model)} {temel}'


def kur(a: argparse.Namespace) -> int:
    sistem_kontrolu()
    bagimliliklari_kur()
    modelleri_hazirla(a.offline)
    baslik("4/8 - VERI DOSYALARI")
    _, chunk = veri_kontrolu()
    ollama_ok = ollama_hazirla(a.model, a.offline)
    cihaz = cihaz_sec(a.cpu)
    tamam(f"Indeksleme cihazi: {cihaz}")
    chroma_hazirla(chunk, cihaz, a.indeksi_yenile)
    duman_testleri(rag=not a.hizli)
    baslik("8/8 - SONUC")
    if not ollama_ok:
        uyari("Python, veri ve RAG katmani hazir; Ollama tamamlaninca kur.py'yi tekrar calistirin.")
        return 1
    tamam("Tum kurulum ve saglik testleri tamamlandi.")
    print("\nCalistirma komutu:")
    print(f"  {calistirma_komutu(a.model)}")
    print("\nTarayici: http://localhost:8000")
    return 0


def main() -> int:
    a = argumanlar()
    if not python_uygun_mu():
        hata(
            f"Python {platform.python_version()} desteklenmiyor. "
            "64 bit Python 3.10, 3.11 veya 3.12 kurun."
        )
        return 1
    try:
        venv_hazirla(a)
        return kontrol(a) if a.kontrol else kur(a)
    except KurulumHatasi as exc:
        baslik("KURULUM DURDU")
        hata(str(exc))
        bilgi("Sorunu giderdikten sonra ayni komutu tekrar calistirabilirsiniz.")
        return 1
    except KeyboardInterrupt:
        print("\nKurulum kullanici tarafindan durduruldu. Ayni komutla devam edebilirsiniz.")
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
