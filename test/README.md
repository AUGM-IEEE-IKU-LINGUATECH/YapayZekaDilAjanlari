# Katılım Bankacılığı RAG Test Kiti

Herhangi bir RAG sistemine takılabilen, **model gerektirmeyen** değerlendirme aracı.
Tek bağımlılığı `requests` (o da sadece HTTP adaptörü için).

## Ne ölçer

44 soru, 15 kategori. 23 sorunun sayısal altın cevabı doğrudan veritabanından doğrulandı — elle yazılmadı. Hepsi deterministik metriklerle puanlanır — LLM hakem yok,
yani sonuç her çalıştırmada aynı çıkar ve internet gerekmez.

| Metrik | Ne bakar |
|---|---|
| `anahtar_kapsam` | Cevapta geçmesi beklenen terimler var mı |
| `yasak_temiz` | Geçmemesi gereken ifade var mı ("faiz oranı" gibi) |
| `banka_isabet` | Doğru bankayı bulmuş mu |
| `deger_dogru` | Beklenen sayı cevapta geçiyor mu (120 ay, 104 kampanya…) |
| `davranis` | Tuzak sorularda doğru davranış (reddetme, tavsiye vermeme) |
| `yol_dogru` | Soruyu doğru katmana yönlendirmiş mi (varsa) |
| `kaynak_var` | Kaynak gösteriyor mu |
| `sayi_dayanakli` | Cevaptaki sayılar kaynaklarda geçiyor mu (halüsinasyon) |

### Soru grupları

| Ön ek | Ne ölçer |
|---|---|
| `T` | Tanım ve terminoloji (katılma hesabı nedir, kâr payı nasıl hesaplanır) |
| `S` | Sıralama, sayma, karşılaştırma — tüm korpusa bakmayı gerektirir |
| `K` | Kampanya arama ve detay |
| `M` | **Marka bazlı taksit** — "Ziraat Katılım'ın Bellona kampanyasında kaç taksit?" (14 soru) |
| `P` | **Harcama-ödül matematiği** — "QR ile 2.000 TL harcarsam ne kazanırım?" (4 soru) |
| `G` | **Geçerlilik tuzağı** — süresi dolmuş kampanya sorulur, model uyarmalı |
| `H` | Halüsinasyon tuzağı — olmayan banka, gelecek projeksiyonu, yatırım tavsiyesi |
| `Z` | Zorlayıcı girdi — Türkçe karaktersiz yazım, anahtar kelime yığını, eşanlamlı |

En değerli kısımlar `G` ve `H`. `G` soruları süresi dolmuş kampanyaları sorar; sistem
"hemen yararlanabilirsiniz" derse geçerlilik filtresi çalışmıyor demektir. `H` soruları
korpusta olmayan bilgiyi sorar; sistem uydurursa yakalanır. İyi görünen sistemlerin çoğu
normal sorularda başarılı olup burada çöker.

`M` ve `P` sorularının altın cevapları kampanya kayıtlarından üretildi, her birinin
`kaynak_url` ve `aciklama` alanında dayanağı yazıyor — istersen tek tek doğrulayabilirsin.

## Kullanım

Üç bağlanma yolu var:

```bash
# 1) HTTP endpoint — en kolay, dil bağımsız
python degerlendir.py --http http://localhost:8000/sor --etiket benim_sistem

# 2) Python fonksiyonu
python degerlendir.py --modul benim_rag:cevapla --etiket v2

# 3) Bu repodaki sistem
python degerlendir.py --yerlesik --etiket temel
python degerlendir.py --yerlesik --llmsiz     # LLM'siz, sadece retrieval
```

## Adaptör sözleşmesi

Sistemin bir soru alıp şunu döndürmeli:

```python
{
  "cevap": "metin",                                  # zorunlu
  "kaynaklar": [{"url": "...", "baslik": "..."}],    # opsiyonel
  "yol": "sql" | "rag"                               # opsiyonel
}
```

Sadece `cevap` dönerse çalışır; eksik alanların metrikleri atlanır.
HTTP adaptörü `answer`/`sources`/`response` gibi İngilizce anahtarları da tanır.

En basit bağlama:

```python
# benim_rag.py
def cevapla(soru: str) -> dict:
    parcalar = benim_retriever.ara(soru)
    return {"cevap": benim_llm.uret(soru, parcalar),
            "kaynaklar": [{"url": p.url} for p in parcalar]}
```

## Başka korpusta çalıştırma

Sorular iki gruba ayrılıyor:

- `veri_bagimsiz: true` (10 soru) — genel katılım bankacılığı bilgisi, her korpusta çalışır
- `veri_bagimsiz: false` (34 soru) — teslim korpusunun (949 benzersiz belge) sayılarına bağlı

Farklı veriyle çalışan bir sistemi test ediyorsan:

```bash
python degerlendir.py --http ... --sadece-genel
```

Tam seti kullanmak istersen `sorular.json` içindeki `beklenen_deger` alanlarını
kendi verine göre güncelle.

## Çıktı

```
sonuclar/sonuc_<etiket>.json   # her sorunun cevabı, puanları, bayrakları
sonuclar/rapor_<etiket>.md     # okunabilir özet + sorunlu cevaplar listesi
```

Farklı ayarları etiketleyip karşılaştırabilirsin:

```bash
TOP_K_CEVAP=4 python degerlendir.py --yerlesik --etiket k4
TOP_K_CEVAP=8 python degerlendir.py --yerlesik --etiket k8
RERANK_AKTIF=0 python degerlendir.py --yerlesik --etiket reranksiz
```

## Puan yorumu

Mutlak bir eşik yok — bu set kendi sistemini kendi geçmişiyle karşılaştırmak için.
Referans olarak: kaynaklara sadık, terminolojiyi doğru kullanan, uydurmayan bir
sahte sistem 0.69; uyduran ve tavsiye veren bir sahte sistem 0.31 aldı.

Genel puandan çok **bayraklara** bak. `uydurma_riski`, `yatirim_tavsiyesi` ve
`dayanaksiz_sayi` bayrakları tek başına ciddi sorun demektir; genel puan yüksek olsa bile.
