# -*- coding: utf-8 -*-
"""
Katilim bankalari kâr payi / katilma hesabi oran tablolarini JS render sonrasi ceker.

Kurulum:
    pip install playwright pandas
    playwright install chromium

Kullanim:
    python scrape_oranlar.py                      # tum hedefler
    python scrape_oranlar.py --oncelik 1          # sadece oncelik 1
    python scrape_oranlar.py --url https://...    # tek sayfa denemesi
    python scrape_oranlar.py --gorunur            # tarayiciyi gorerek calistir (debug)

Cikti:
    ham_sayfalar/<banka>__<slug>.json   # tablolar + metin + ekran goruntusu yolu
    oran_ham.jsonl                      # hepsi tek dosyada
"""
import asyncio, argparse, csv, json, re, sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

HEDEF = Path("hedef_sayfalar.csv")
OUTDIR = Path("ham_sayfalar"); OUTDIR.mkdir(exist_ok=True)
JSONL = Path("oran_ham.jsonl")

# Cerez banneri kapatma — metin bazli, secici bazli degil (siteler arasi degisir)
CEREZ_METIN = ["kabul et", "tümünü kabul", "tumunu kabul", "onayla", "anladım",
               "anladim", "accept", "kapat", "izin ver"]
# Oran tablosu iceren sayfa sinyali: "%" ve ardindan rakam
ORAN_VAR = re.compile(r"%\s*\d|\d\s*%")


async def cerez_kapat(page):
    for t in CEREZ_METIN:
        try:
            btn = page.get_by_role("button", name=re.compile(t, re.I)).first
            if await btn.is_visible(timeout=800):
                await btn.click(timeout=1500)
                await page.wait_for_timeout(400)
                return True
        except Exception:
            continue
    return False


async def akordeonlari_ac(page):
    """Oran tablolari sikca sekme/akordeon icinde gizli olur — hepsini acmayi dene."""
    sec = ("[data-toggle='collapse'], [data-bs-toggle='collapse'], .accordion-header, "
           ".accordion-button, .tab-link, [role='tab'], summary")
    try:
        els = await page.query_selector_all(sec)
        for e in els[:25]:
            try:
                if await e.is_visible():
                    await e.click(timeout=800)
                    await page.wait_for_timeout(250)
            except Exception:
                pass
    except Exception:
        pass


async def tablolari_al(page):
    """Her <table>'i satir dizisine cevir."""
    return await page.evaluate("""() => {
        const cikti = [];
        document.querySelectorAll('table').forEach((tbl, i) => {
            const satirlar = [];
            tbl.querySelectorAll('tr').forEach(tr => {
                const h = [...tr.querySelectorAll('th,td')]
                    .map(td => td.innerText.replace(/\\s+/g,' ').trim());
                if (h.some(x => x)) satirlar.push(h);
            });
            if (satirlar.length > 1) {
                let bh = null, el = tbl;
                for (let k=0; k<6 && el; k++) {
                    el = el.previousElementSibling || el.parentElement;
                    if (el && /^H[1-6]$/.test(el.tagName)) { bh = el.innerText.trim(); break; }
                }
                cikti.push({ index: i, baslik: bh, satirlar });
            }
        });
        return cikti;
    }""")


async def bir_sayfa(page, banka, url, tip):
    kayit = {"banka_kodu": banka, "url": url, "tip": tip,
             "cekim_zamani": datetime.now(timezone.utc).isoformat(),
             "durum": None, "tablolar": [], "metin": "", "oran_bulundu": False}
    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=45000)
        await cerez_kapat(page)
        # lazy-load icerik icin sona kaydir
        await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        await page.wait_for_timeout(1200)
        await page.evaluate("window.scrollTo(0, 0)")
        await akordeonlari_ac(page)
        # oran gorunene kadar bekle (yoksa timeout'u yut, sayfa yine de kaydedilir)
        try:
            await page.wait_for_function(
                "() => /%\\s*\\d|\\d\\s*%/.test(document.body.innerText)", timeout=8000)
        except Exception:
            pass
        await page.wait_for_timeout(600)

        kayit["tablolar"] = await tablolari_al(page)
        kayit["metin"] = re.sub(r"\s{2,}", " ", await page.inner_text("body"))[:60000]
        kayit["oran_bulundu"] = bool(ORAN_VAR.search(kayit["metin"]))
        kayit["durum"] = "ok"

        slug = re.sub(r"[^a-z0-9]+", "-", urlparse(url).path.lower()).strip("-")[:70] or "index"
        png = OUTDIR / f"{banka}__{slug}.png"
        await page.screenshot(path=str(png), full_page=False)
        kayit["ekran_goruntusu"] = str(png)
        (OUTDIR / f"{banka}__{slug}.json").write_text(
            json.dumps(kayit, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as e:
        kayit["durum"] = f"hata: {type(e).__name__}: {e}"[:300]
    return kayit


async def main(args):
    from playwright.async_api import async_playwright

    if args.url:
        hedefler = [{"banka_kodu": "manuel", "url": args.url, "tip": "manuel", "oncelik": "1"}]
    else:
        if not HEDEF.exists():
            sys.exit(f"{HEDEF} bulunamadi — once bu dosyayi yanina koy.")
        hedefler = list(csv.DictReader(HEDEF.open(encoding="utf-8")))
        if args.oncelik:
            hedefler = [h for h in hedefler if h["oncelik"] == str(args.oncelik)]

    yapilan = set()
    if JSONL.exists() and not args.bastan:
        for l in JSONL.open(encoding="utf-8"):
            try:
                r = json.loads(l)
                if r.get("durum") == "ok":
                    yapilan.add(r["url"])
            except Exception:
                pass
    hedefler = [h for h in hedefler if h["url"] not in yapilan]
    print(f"{len(hedefler)} sayfa cekilecek ({len(yapilan)} zaten yapilmis)")

    ok = oran = 0
    async with async_playwright() as p:
        tarayici = await p.chromium.launch(headless=not args.gorunur)
        ctx = await tarayici.new_context(
            locale="tr-TR", timezone_id="Europe/Istanbul",
            viewport={"width": 1440, "height": 1000},
            user_agent=("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                        "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"))
        page = await ctx.new_page()
        with JSONL.open("a", encoding="utf-8") as f:
            for i, h in enumerate(hedefler, 1):
                r = await bir_sayfa(page, h["banka_kodu"], h["url"], h["tip"])
                f.write(json.dumps(r, ensure_ascii=False) + "\n"); f.flush()
                if r["durum"] == "ok":
                    ok += 1
                    oran += r["oran_bulundu"]
                isaret = "OK " if r["durum"] == "ok" else "HATA"
                print(f"[{i}/{len(hedefler)}] {isaret} tablo={len(r['tablolar'])} "
                      f"oran={'V' if r['oran_bulundu'] else '-'} {h['url'][:78]}")
                await asyncio.sleep(args.bekle)   # nazik ol
        await tarayici.close()
    print(f"\nbitti: {ok}/{len(hedefler)} basarili, {oran} sayfada oran verisi var")
    print(f"cikti: {JSONL} ve {OUTDIR}/")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--oncelik", type=int, help="sadece bu oncelik seviyesi")
    ap.add_argument("--url", help="tek URL dene")
    ap.add_argument("--gorunur", action="store_true", help="tarayiciyi goster")
    ap.add_argument("--bekle", type=float, default=1.5, help="sayfalar arasi saniye")
    ap.add_argument("--bastan", action="store_true", help="onceki sonuclari yok say")
    asyncio.run(main(ap.parse_args()))
