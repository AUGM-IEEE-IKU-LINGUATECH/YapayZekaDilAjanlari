# Katılım Bankacılığı Ürün ve Kampanya Analizi

**TEKNOFEST 2026 · Yapay Zeka Dil Ajanları Yarışması · 2. Senaryo**  
Takım: **Lingua-Tech Yapay Zeka** · Etiket: **BilisimVadisi2026**

Katılım bankalarının doğal dilde yayımladığı ürün ve kampanya metinlerinden
finansal bilgileri çıkaran, ürünleri karşılaştırılabilir hâle getiren ve tamamen
kurum içinde (on-premise) çalışan Türkçe NLP sistemidir. Sistem; yapılandırılmış
sorular için SQL, açıklama ve kampanya ayrıntıları için kaynaklı RAG kullanır.

## Doğrulanmış veri özeti

Aşağıdaki değerler teslim edilen `veri/katilim.db` ve
`veri/rag_chunks.jsonl` dosyalarından 28 Ağustos 2026 tarihinde hesaplanmıştır.

| Ölçü | Değer |
|---|---:|
| Veritabanında fiilî verisi bulunan banka | 10 |
| Ürün ve kampanya kaydı | 1.114 |
| SQLite `urunler` tablosu sütunu | 41 |
| Benzersiz kaynak belge | 949 |
| RAG metin parçası (chunk) | 2.893 |
| Kaynak URL içeren kayıt | 1.012 |
| Kâr payı oranı bulunan kayıt | 178 (%16) |
| Kayıtlı son birleşik değerlendirme | 138 soruda 0,875 |
| Harici bulut servisi bağımlılığı | Yok |

İktisat Katılım ad çözümleme sözlüğünde tanımlıdır; teslim veritabanında bu
bankaya ait ürün kaydı bulunmamaktadır.

## Mimari

Kural tabanlı yönlendirici her soruyu uygun cevap katmanına gönderir:

- **SQL katmanı:** Sayma, sıralama ve karşılaştırma sorularını 1.114 kaydın
  tamamı üzerinde şablon tabanlı ve deterministik olarak işler.
- **RAG katmanı:** Açıklama ve kampanya ayrıntısı sorularında metadata filtresi,
  bge-m3 vektör araması, sözcüksel yedek ve bge-reranker-v2-m3 kullanır.
- **Yerel üretim:** Qwen2.5-7B-Instruct, Ollama üzerinden yerel olarak çalışır.
- **Sunum katmanı:** FastAPI, dashboard ve chatbot arayüzünü sağlar.

Dil kayması koruması, kaynak tutarlılığı denetimi, terminoloji güvencesi,
alaka eşiği ve sohbet bağlamı izolasyonu uygulanır.

## Kurulum ve çalıştırma

Python 3.10 veya üzeri ve yaklaşık 12 GB boş alan önerilir. Ollama sistemde
ayrıca kurulmalıdır.

```bash
python kur.py --kontrol
python kur.py
python -m uvicorn katilim_rag.api:app --port 8000
```

Arayüz: `http://localhost:8000`  
Ayrıntılı talimatlar: [KURULUM.md](KURULUM.md)

## Veri seti

- Herkese açık veri seti: [veri/Veri_Set.csv](veri/Veri_Set.csv)
- Teslim veritabanı: [veri/katilim.db](veri/katilim.db)
- RAG parçaları: [veri/rag_chunks.jsonl](veri/rag_chunks.jsonl)
- Hazır vektör dizini: `veri/chroma/`

Teslim edilen `katilim.db`, veri zenginleştirme ve migrasyonların uygulanmış
nihai kopyasıdır. Ayrıntılar dokümantasyonda açıklanmıştır.

## Değerlendirme

```bash
cd test
python degerlendir.py --http http://localhost:8000/sor \
       --sorular sorular_birlesik.json --etiket olcum
```

Birleşik set 44 iç ve 94 bağımsız olmak üzere 138 sorudan oluşur. Ölçüm,
LLM hakem yerine deterministik metrikler kullanır. Kayıtlı son sonuç 0,875'tir.

## Teslim materyalleri

- [Proje dokümantasyonu](DOKUMANTASYON.md)
- [Demo videosu](DEMO.md)
- [Final sunumu — PPTX](LinguaTechSunum.pptx)
- [Final sunumu — PDF](LinguaTechSunum.pdf)

## Lisans

Bu proje [Apache License 2.0](LICENSE) ile lisanslanmıştır.
