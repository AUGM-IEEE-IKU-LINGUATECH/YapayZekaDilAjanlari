# -*- coding: utf-8 -*-
"""
Sifirdan kurulum ve dogrulama.

    python kur.py            # tum adimlar
    python kur.py --kontrol  # sadece durum raporu, hicbir sey indirmez
    python kur.py --cpu      # GPU yok, CPU kurulumu

Toplam indirme ~12 GB. Adimlar tek tek calisir; yarida kesilirse
ayni komutu tekrar calistir, tamamlananlari atlar.
"""
import argparse, json, os, platform, shutil, subprocess, sys, urllib.request
from pathlib import Path

KOK = Path(__file__).resolve().parent
for _a in (sys.stdout, sys.stderr):
    try:
        _a.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

Y, K, M, S = "\033[93m", "\033[91m", "\033[92m", "\033[0m"
if platform.system() == "Windows" and not os.getenv("WT_SESSION"):
    Y = K = M = S = ""


def baslik(n, t):
    print(f"\n{'='*58}\n[{n}] {t}\n{'='*58}")


def kos(cmd, kritik=True):
    print(f"  $ {cmd}")
    r = subprocess.run(cmd, shell=True)
    if r.returncode and kritik:
        print(f"{K}  HATA: komut basarisiz (kod {r.returncode}){S}")
        return False
    return r.returncode == 0


def var_mi(prog):
    return shutil.which(prog) is not None


# --------------------------------------------------------------- kontroller
def python_kontrol():
    v = sys.version_info
    ok = v >= (3, 10)
    print(f"  Python {v.major}.{v.minor}.{v.micro} {'OK' if ok else 'YETERSIZ (3.10+ gerekli)'}")
    return ok


def disk_kontrol(gerekli_gb=20):
    bos = shutil.disk_usage(KOK).free / 1e9
    ok = bos >= gerekli_gb
    print(f"  Bos disk: {bos:.1f} GB {'OK' if ok else f'YETERSIZ ({gerekli_gb} GB gerekli)'}")
    return ok


def gpu_kontrol():
    if not var_mi("nvidia-smi"):
        print(f"  {Y}nvidia-smi yok — GPU tespit edilemedi, CPU modunda kurulacak{S}")
        return False, 0
    try:
        c = subprocess.run("nvidia-smi --query-gpu=name,memory.total --format=csv,noheader",
                           shell=True, capture_output=True, text=True, timeout=15)
        satir = c.stdout.strip().splitlines()[0]
        ad, bellek = [x.strip() for x in satir.split(",")]
        vram = int("".join(ch for ch in bellek if ch.isdigit())) / 1024
        print(f"  GPU: {ad} ({vram:.0f} GB VRAM)")
        if vram < 6:
            print(f"  {Y}VRAM dusuk — daha kucuk model onerilir (qwen2.5:3b-instruct){S}")
        return True, vram
    except Exception as e:
        print(f"  {Y}GPU okunamadi: {e}{S}")
        return False, 0


def torch_kontrol():
    try:
        import torch
        cuda = torch.cuda.is_available()
        print(f"  torch {torch.__version__} | CUDA: {'EVET' if cuda else 'HAYIR (CPU modu)'}")
        return True, cuda
    except ImportError:
        print("  torch kurulu degil")
        return False, False


def ollama_kontrol(model):
    if not var_mi("ollama"):
        print(f"  {K}ollama kurulu degil{S}")
        return False, False
    try:
        with urllib.request.urlopen("http://localhost:11434/api/tags", timeout=4) as r:
            modeller = [m["name"] for m in json.load(r).get("models", [])]
        kok = model.split(":")[0]
        varmi = any(kok in m for m in modeller)
        print(f"  ollama calisiyor | modeller: {', '.join(modeller) or '(yok)'}")
        return True, varmi
    except Exception:
        print(f"  {Y}ollama kurulu ama servis calismiyor — 'ollama serve' ile baslat{S}")
        return True, False


def veri_kontrol():
    d = KOK / "veri"
    db, ch = d / "katilim.db", d / "rag_chunks.jsonl"
    chroma = d / "chroma"
    print(f"  katilim.db        : {'VAR' if db.exists() else 'YOK'}")
    print(f"  rag_chunks.jsonl  : {'VAR' if ch.exists() else 'YOK'}")
    kurulu = chroma.exists() and any(chroma.iterdir()) if chroma.exists() else False
    print(f"  chroma index      : {'KURULU' if kurulu else 'KURULMAMIS'}")
    return db.exists() and ch.exists(), kurulu


def durum_raporu(model):
    baslik("K", "DURUM RAPORU")
    py = python_kontrol()
    disk = disk_kontrol()
    gpu, vram = gpu_kontrol()
    t_var, t_cuda = torch_kontrol()
    o_var, o_model = ollama_kontrol(model)
    v_var, idx = veri_kontrol()
    print("\n  ozet:")
    for ad, ok in [("Python 3.10+", py), ("Disk alani", disk), ("torch", t_var),
                   ("torch CUDA", t_cuda), ("ollama", o_var), (f"model {model}", o_model),
                   ("veri dosyalari", v_var), ("chroma index", idx)]:
        print(f"    {'[+]' if ok else '[ ]'} {ad}")
    return all([py, t_var, o_var, o_model, v_var, idx])


# --------------------------------------------------------------- kurulum
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--kontrol", action="store_true", help="sadece durum, indirme yok")
    ap.add_argument("--cpu", action="store_true", help="GPU yok, CPU kurulumu")
    ap.add_argument("--model", default=os.getenv("LLM_MODEL", "qwen2.5:7b-instruct"))
    a = ap.parse_args()

    if a.kontrol:
        tamam = durum_raporu(a.model)
        print(f"\n{M if tamam else Y}{'Sistem hazir.' if tamam else 'Eksikler var — python kur.py ile tamamla.'}{S}")
        return

    baslik(0, "ON KONTROL")
    if not python_kontrol():
        sys.exit("Python 3.10+ gerekli.")
    disk_kontrol()
    gpu, vram = gpu_kontrol()
    cuda_ister = gpu and not a.cpu

    baslik(1, "PYTHON PAKETLERI (~500 MB)")
    kos(f'"{sys.executable}" -m pip install --upgrade pip')
    if cuda_ister:
        print("  CUDA'li torch kuruluyor (~2.5 GB)…")
        kos(f'"{sys.executable}" -m pip install torch --index-url https://download.pytorch.org/whl/cu124')
    kos(f'"{sys.executable}" -m pip install -r "{KOK / "gereksinimler.txt"}"')

    baslik(2, "TORCH DOGRULAMA")
    t_var, t_cuda = torch_kontrol()
    if cuda_ister and not t_cuda:
        print(f"  {Y}GPU var ama torch CUDA gormuyor. Su komutu dene:{S}")
        print(f'  {sys.executable} -m pip install torch --index-url '
              f'https://download.pytorch.org/whl/cu124 --force-reinstall')

    baslik(3, "OLLAMA")
    if not var_mi("ollama"):
        print(f"  {K}Ollama kurulu degil.{S}")
        print("  Indir: https://ollama.com/download")
        print(f"  Kurduktan sonra: ollama pull {a.model}")
        print("  Sonra bu scripti tekrar calistir.")
    else:
        o_var, o_model = ollama_kontrol(a.model)
        if not o_model:
            model = a.model
            if gpu and vram and vram < 8:
                model = "qwen2.5:3b-instruct"
                print(f"  {Y}VRAM {vram:.0f} GB — {model} kuruluyor{S}")
            print(f"  {model} indiriliyor (~4-5 GB)…")
            kos(f"ollama pull {model}", kritik=False)

    baslik(4, "VERI VE INDEX")
    v_var, idx = veri_kontrol()
    if not v_var:
        sys.exit(f"{K}veri/katilim.db ve veri/rag_chunks.jsonl eksik. "
                 f"katilim_rag_sistem.zip icindeki veri/ klasorunu buraya kopyala.{S}")
    if idx:
        print("  index zaten kurulu, atlaniyor (yeniden kurmak icin: "
              "python -m katilim_rag.index --bastan)")
    else:
        try:
            n_ch = sum(1 for _ in (KOK / "veri" / "rag_chunks.jsonl").open(encoding="utf-8"))
        except Exception:
            n_ch = "~2900"
        print(f"  gomme modeli inecek (~2.2 GB) ve {n_ch} chunk gomulecek…")
        cihaz = "cuda" if t_cuda else "cpu"
        if cihaz == "cpu":
            print(f"  {Y}CPU modunda — 15-30 dk surebilir{S}")
        os.environ["CIHAZ"] = cihaz
        kos(f'"{sys.executable}" -m katilim_rag.index --bastan', kritik=False)

    baslik(5, "SONUC")
    tamam = durum_raporu(a.model)
    print(f"\n{M if tamam else Y}{'Kurulum tamam.' if tamam else 'Bazi adimlar eksik kaldi — yukaridaki ozete bak.'}{S}")
    print("\nCalistirma:")
    print("  uvicorn katilim_rag.api:app --port 8000     -> http://localhost:8000")
    print("  python -m katilim_rag.cli                    -> terminal")
    print("  cd test && python degerlendir.py --yerlesik  -> degerlendirme")


if __name__ == "__main__":
    main()
