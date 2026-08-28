# Katılım Bankacılığı RAG Sistemi

Türkiye'deki 10 katılım bankasının ürün, hesap ve kampanya verisi üzerinde çalışan,
tamamen lokal (offline) soru-cevap sistemi. TEKNOFEST TYDA Senaryo 2 için.

## Mimari

Soru iki yoldan biriyle cevaplanır:

- **SQL yolu** — sayma, sıralama, karşılaştırma soruları. Şablon tabanlı, deterministik,
  1114 kaydın tamamına bakar. ("En uzun vadeli konut finansmanı hangi bankada?")
- **RAG yolu** — açıklama, koşul, tanım soruları. 2893 chunk üzerinde vektör araması.
  ("Katılma hesabı nasıl işliyor?")

Yönlendirme kural tabanlıdır (`analiz.py`), LLM'e bırakılmaz — böylece test edilebilir
ve aynı soru hep aynı yola gider.

## Sıfırdan kurulum

```bash
python kur.py --kontrol    # önce neyin eksik olduğuna bak, hiçbir şey indirmez
python kur.py              # eksikleri tamamla
```

Script sırayla: Python sürümü ve disk alanını kontrol eder, GPU'yu tespit eder,
CUDA'lı torch'u kurar, bağımlılıkları yükler, Ollama modelini indirir, Chroma indexini
kurar ve sonunda durum raporu basar. Yarıda kesilirse aynı komutu tekrar çalıştır —
tamamlanan adımları atlar.

GPU yoksa: `python kur.py --cpu`
Farklı model: `python kur.py --model llama3.1:8b`

**Ollama'yı script kuramaz** (sistem kurulumu gerektiriyor). `ollama` komutu yoksa
önce https://ollama.com/download adresinden kur, sonra scripti tekrar çalıştır.

### İndirme boyutları

| Ne | Boyut |
|---|---|
| CUDA'lı torch | ~2.5 GB |
| bge-m3 (gömme) | ~2.2 GB |
| bge-reranker-v2-m3 | ~2.2 GB |
| qwen2.5:7b-instruct | ~4.7 GB |
| diğer paketler | ~500 MB |
| **toplam** | **~12 GB** |

Reranker ilk soru sorulduğunda iner; istemiyorsan `RERANK_AKTIF=0` ile atla (2.2 GB tasarruf,
retrieval kalitesi bir miktar düşer).

## Çalıştırma

```bash
uvicorn katilim_rag.api:app --port 8000     # http://localhost:8000 (panel + asistan)
python -m katilim_rag.cli                    # terminal
python -m katilim_rag.cli -s "soru" --detay  # hangi chunk'lar geldi, skorları ne
python -m katilim_rag.cli -s "soru" --llmsiz # LLM'siz, sadece retrieval testi
```

## Dosyalar

| Dosya | Görev |
|---|---|
| `config.py` | Tüm parametreler (model, top_k, eşikler). Ortam değişkeniyle ezilir. |
| `analiz.py` | Türkçe normalizasyon + slot çıkarımı (banka, ürün, metrik, aktiflik) |
| `sql_arac.py` | Şablon tabanlı SQL sorguları — sıralama, sayma, karşılaştırma |
| `index.py` | Chunk'ları gömüp Chroma'ya yazar (bir kez) |
| `getir.py` | Filtre → vektör arama → rerank → belge çeşitliliği → top-k |
| `llm.py` | Ollama istemcisi + prompt şablonları |
| `boru.py` | Uçtan uca akış |
| `api.py` | FastAPI: `/sor`, `/sor/akis`, `/panel/*`, `/saglik` |
| `arayuz.html` | Panel (grafikler, karşılaştırma, kampanyalar) + sohbet |
| `cli.py` | Terminal arayüzü |

## Ayarlanabilir parametreler

`config.py` içinde ya da ortam değişkeniyle:

```bash
TOP_K_CEVAP=6 RERANK_AKTIF=0 LLM_MODEL=llama3.1:8b python -m katilim_rag.cli
```

- `TOP_K_ARAMA` (12) — vektör aramasından çekilen aday sayısı
- `TOP_K_CEVAP` (8) — LLM'e verilen chunk sayısı
- `DOC_BASINA_MAX` (2) — aynı belgeden en fazla kaç chunk (çeşitlilik)
- `RERANK_AKTIF` (1) — cross-encoder yeniden sıralama
- `MIN_SKOR` (0.0) — rerank skor eşiği

## Ölçüm sonuçları

138 soruluk birleşik değerlendirme setinde (44 iç + 94 bağımsız) **0.875** ortalama.
Sayısal doğruluk (`deger_dogru`) 1.000 — kampanya tutarı, taksit ve vade cevaplarının tamamı doğru.
Soru başına ortalama 5.75 sn (RTX 3070 Ti, Qwen2.5-7B).

Gelişim: 0.748 → 0.905 (iç set) → 0.877 → 0.875 (birleşik set, veri birleştirme sonrası).

Ölçümle bulunup düzeltilen hatalar:
- `doc_id` metadata'da ezildiği için LLM'e 6 yerine 2 chunk gidiyordu
- Marka bazlı kampanya soruları SQL'e yönlenip boş dönüyordu
- Alaka eşiği olmadığı için korpusta olmayan sorulara alakasız kaynak gösteriliyordu
- Model süresi dolmuş kampanyaya "hâlâ geçerli" diyordu (tarih aritmetiği yerine artık
  `DURUM` etiketi bağlama yazılıyor)
- Bağlam zayıfladığında model Çince cevap veriyordu

## Bilinen eksik

**Kâr payı oranı 1.114 kaydın 178'inde vardır (%16).** Bankaların oran tablolarının
önemli bir bölümü JavaScript ile yüklendiği için kapsam sınırlıdır. Ek tarama için
`scrape_oranlar.py` ve `hedef_sayfalar.csv` kullanılabilir. Panel bu kapsamı
kullanıcıya açıkça gösterir.
