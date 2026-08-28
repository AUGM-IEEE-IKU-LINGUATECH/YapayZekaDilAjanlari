# Proje Dokümantasyonu

**TEKNOFEST 2026 — Yapay Zeka Dil Ajanları Yarışması, 2. Senaryo**
Katılım Bankacılığı Ürün ve Kampanya Analizi için NLP Çözümü

**Takım:** Lingua-Tech Yapay Zeka

### Takım üyeleri ve görev dağılımı

| Üye | Rol | Sorumluluklar |
|---|---|---|
| **Yiğit Varol** | Takım Kaptanı | RAG ve LLM katmanı, değerlendirme süreçleri |
| **Yiğitcan Bayık** | Takım Üyesi | Finansal bilgi çıkarımı ve veri normalizasyonu |
| **Kağan Kutanoğlu** | Takım Üyesi | Veri toplama ve metin ön işleme |
| **Cem Çalışkan** | Takım Üyesi | API, dashboard ve sunum materyalleri |

---

## 1. Sistem Mimarisinin Genel Açıklaması ve Veri Akışının Özetlenmesi

Sistem iki fazda çalışır: bir kez yapılan **veri hazırlama** ve her soruda çalışan **cevap üretimi**.

### Veri hazırlama (offline)

```
Ham CSV (1026 satır)
    ↓ metin temizleme, boilerplate tespiti
    ↓ banka normalizasyonu, mükerrer birleştirme
1.114 kayıt
    ├─→ finansal bilgi çıkarımı → SQLite (1.114 satır × 41 sütun)
    └─→ chunk'lama + gömme      → ChromaDB (2.893 vektör)
```

### Cevap üretimi (online)

```
Kullanıcı sorusu
    ↓
Kural tabanlı yönlendirici (analiz.py) + sohbet hafızası
    ├─→ SQL yolu   : sayma, sıralama, karşılaştırma  → SQLite → LLM
    └─→ RAG yolu   : açıklama, kampanya detayı       → ChromaDB → LLM
    ↓
Dil ve kaynak güvenlik kontrolü (boru.py)
    ├─ dil koruması: Latin dışı kayma → tekrar dene → şablon → güvenli metin
    ├─ reddetme tespiti: kaynak listesi tutarlılığı
    └─ yapılandırılmış temellendirme: doğrulanmış DB değerleri bağlama eklenir
    ↓
Türkçe cevap + kaynak URL listesi
```

**Sohbet hafızası.** Takip soruları önceki turların bağlamıyla çözülür: "Kuveyt
Türk'ün konut finansmanı ne?" sorusundan sonra "peki vade kaç ay?" sorusu bankayı
hatırlar. Yeni soruda farklı bir banka geçerse önceki bağlam bilinçli olarak atılır.

**İki katmanlı tasarımın gerekçesi.** Saf RAG mimarisi, 2.893 chunk arasından yalnızca
en benzer 6 tanesini çeker. "En uzun vadeli konut finansmanı hangi bankada?" gibi bir
soru ise tüm veri kümesine bakmayı gerektirir; doğru kayıt ilk 6 içinde değilse model
elindeki en büyük değeri "en uzun" diye sunar ve bunu kaynak göstererek yapar.
Bu nedenle toplama/sıralama gerektiren sorular yapılandırılmış SQL katmanına,
açıklama gerektiren sorular vektör aramasına yönlendirilir.

Ölçüm bu ayrımın değerini doğrulamıştır: yönlendirme hatalıyken genel başarı 0.748,
düzeltildikten sonra 0.905'tir (bkz. bölüm 10).

### Bileşenler

| Katman | Teknoloji | Lisans |
|---|---|---|
| Gömme modeli | BAAI/bge-m3 | MIT |
| Vektör veritabanı | ChromaDB | Apache 2.0 |
| Yapılandırılmış veri | SQLite | Public Domain |
| Dil modeli | Qwen2.5-7B-Instruct (Ollama) | Apache 2.0 |
| Servis | FastAPI + Uvicorn | MIT |
| Arayüz | HTML/CSS/JS + Chart.js (yerel) | MIT |

---

## 2. Kullanılan NLP Yaklaşımının Açıklaması

Çözüm tek bir yönteme değil, dört NLP tekniğinin birleşimine dayanır.

### 2.1 Kural tabanlı bilgi çıkarımı

Finansal değerler (kâr payı oranı, vade, taksit, tutar, ödül) düzenli ifadelerle
çıkarılır. Bu tercih bilinçlidir: finansal veride **doğrulanabilirlik**, esneklikten
önce gelir. Kural tabanlı çıkarımın hangi metinden hangi değeri aldığı izlenebilir
(`kar_payi_kaynak` alanında dayanak cümlesi saklanır), LLM tabanlı çıkarımda bu
izlenebilirlik kaybolur.

Şartname 5.2'de belirtilen dolaylı ifadeler de ayrıca yakalanır:
"avantajlı kâr payı fırsatı", "özel oranlı finansman", "düşük maliyetli finansman",
"masrafsız finansman". Bu ifadeler `dolayli_kar_payi` alanına etiketlenir
(kolon ve etiketleme `migrasyon_2026_08.py` ile üretilir; 21 kayıt işaretlidir).

### 2.2 Metin sınıflandırma

İki ayrı sınıflandırma yapılır:

- **Belge türü**: kampanya / ürün-hizmet / liste sayfası / kurumsal bilgi / sözleşme-form
- **Kampanya türü** (şartname 5.4): 8 kategori — konut, taşıt, ihtiyaç finansmanı,
  kart, alışveriş puanı, yeni müşteri, yatırım ürünü, genel finansman

Sınıflandırma anahtar kelime örüntüleri ve URL yol yapısının birlikte
değerlendirilmesiyle yapılır.

### 2.3 Hibrit arama (anlamsal + sözcüksel)

Chunk'lar `bge-m3` ile 1024 boyutlu vektörlere dönüştürülür. Bu model çok dilli
olduğu ve Türkçe'de güçlü performans gösterdiği için seçilmiştir. Anlamsal arama
sayesinde "ev kredisi" ile "konut finansmanı", "araba" ile "taşıt" eşleşir.

**Sözcüksel yedek:** Anlamsal arama nadir özel isimlerde (marka adları) isabetsiz
kalabildiğinden, vektör araması boş döndüğünde IDF ağırlıklı kelime araması devreye
girer. Nadir terimin belge BAŞLIĞINDA geçmesi zorunludur: gövdede geçen ortak bir
kelime ilgiyi göstermez; bu koşul olmadan korpusta olmayan konulara da sonuç dönüyor
ve model uydurmaya zorlanıyordu. Türkçe katlama sayesinde "Istikbal" yazımı
"İstikbal" kaydını bulur.

**Bağlamsal gömme (contextual retrieval):** Her chunk'ın gömme metninin başına
`[Banka] [belge türü] [segment] [kategori] Başlık` bağlamı eklenir. Uzun bir belgenin
üçüncü chunk'ında banka adı geçmeyebilir; bu ön ek olmadan banka karşılaştırma
sorularında retrieval isabetsiz kalır.

### 2.4 Üretim (generation)

Çekilen kaynaklar bir sistem promptu ile birlikte yerel LLM'e verilir. Prompt,
katılım bankacılığı terminolojisini zorunlu kılar ("faiz" değil "kâr payı",
"kredi" değil "finansman"), kaynak dışı bilgi üretimini yasaklar ve cevabın
Türkçe olmasını şart koşar.

---

## 3. Kullanılan Veri Seti ve Açıklaması

### Kaynak

Veri, BDDK'nın katılım bankaları listesinde yer alan kuruluşların resmî web
sitelerinden Python tabanlı web scraping ile toplanmıştır. Kapsam, veri toplama
dönemindeki 10 faal bankadır; 26 Şubat 2026'da faaliyet izni alan **İktisat
Katılım** ad çözümleme sözlüğünde tanımlıdır ancak ürün/kampanya verisi henüz
toplanmamıştır — bkz. "Bilinen Eksikler".

| Özellik | Değer |
|---|---|
| Ham kayıt | 1.026 satır (crawl) + 467 satır (yapılandırılmış CSV) |
| İşlenmiş kayıt | 1.114 |
| Chunk | 2.893 |
| Banka | 10 |
| Kolon (yapılandırılmış) | 37 |

### Kapsanan kurumlar

Kuveyt Türk, Ziraat Katılım, Albaraka Türk, Türkiye Finans, Vakıf Katılım,
Türkiye Emlak Katılım, Hayat Finans, T.O.M. Katılım, Dünya Katılım, Adil Katılım.

### Belge türü dağılımı

| Tür | Adet |
|---|---|
| Ürün / hizmet | 365 |
| Kampanya | 346 |
| Liste sayfası | 138 |
| Kurumsal bilgi | 21 |
| Sözleşme / form | 6 |

### Kampanya geçerlilik durumu

Aktif 109, süresi dolmuş 173, tarihi belirlenemeyen 64.
Süresi dolmuş kampanyaların işaretlenmesi kritik bir gerekliliktir: sistem bu
kampanyaları cevaplarında "sona ermiş" olarak belirtir, aksi halde kullanıcıya
geçersiz bilgi sunulmuş olur.

---

## 4. Veri Ön İşleme Adımları

Ham veri üzerinde gözlemlenen sorunlar ve uygulanan işlemler:

### 4.1 Banka adı normalizasyonu
Ham veride aynı banka 18 farklı biçimde yazılmıştı (`Kuveyt Türk`,
`KUVEYT TÜRK KATILIM BANKASI A.Ş.`, `Kuveyt Turk`). Ayrıca bazı satırlarda
`banka_adi` alanı ile `kaynak_url` çelişiyordu. Çelişki durumunda **URL alan adı
otorite kabul edilmiştir**, çünkü içeriğin hangi siteden geldiği kesindir.

### 4.2 Boilerplate temizliği
Menü, buton ve gezinme metinleri (`DETAYLI BİLGİ`, `HEMEN BAŞVUR`,
`Bu bağlantı yeni sekmede açılacak`) metin gövdesine karışmıştı. Korpus genelinde
25'ten fazla belgede tekrar eden, nokta ile bitmeyen kısa segmentler otomatik olarak
boilerplate kabul edilip çıkarılmıştır. Nokta ile biten cümleler korunur —
kampanya koşulları bu şekilde kaybolmaz.

### 4.3 Yapısal düzeltmeler
Bazı bankaların metinleri boru işareti (`|`) ile ayrılmış, cümle sınırı içermiyordu.
Bitişik tekrar eden başlıklar (`Yatırım RehberimYatırım Rehberim`) ayrıştırılmıştır.

### 4.4 Mükerrer birleştirme
Aynı sayfa hem `http://` hem `https://`, bazen de `#çapa` ekiyle taranmıştı.
Metinler birkaç yüz karakter farklı olduğundan birebir karşılaştırma bunları
yakalayamıyordu. URL normalizasyonu (şema, `www`, çapa ve sorgu parametresi
atılarak) ile **139 mükerrer belge** birleştirilmiştir. Zengin olan sürüm korunur,
diğerinin adresi `alternatif_urller` alanında saklanır.

### 4.5 Liste sayfası tespiti
Kategori sayfaları (`/kampanyalar/giyim-ve-aksesuar` gibi) tekil kampanya değil,
onlarca kampanyanın bağlantı listesidir. Başlık tekrar oranına bakan bir kural ile
138 belge `liste_sayfasi` olarak işaretlenmiş ve retrieval'da düşük önceliğe
alınmıştır; aksi halde anlamsız tekrar blokları cevaplara karışmaktadır.

### 4.6 Standart formata dönüştürme (şartname 5.6)

| Girdi | Çıktı |
|---|---|
| `%2,05` / `% 2.05` / `2.05 %` | `2.05` |
| `500 TL` / `500₺` / `500 Türk Lirası` | `500.0` |

### 4.7 Tarih doğrulama
Tarih ayrıştırmasında makul olmayan yıllar (kaynak yazım hatası kaynaklı `2076`
gibi) reddedilir; yalnızca 2015–2035 aralığı kabul edilir.

### 4.8 Chunk'lama
Cümle sınırında, hedef 1100 karakter, 180 karakter kelime sınırına hizalanmış
örtüşme. 250 karakterden kısa kuyruk parçalar önceki chunk'a birleştirilir.

---

## 5. Model veya Kural Yapısının Açıklaması

### 5.1 Yönlendirici (analiz.py)

Yönlendirme **kural tabanlıdır, LLM'e bırakılmamıştır.** Gerekçe: yönlendirme hatası
tüm cevabı geçersiz kılar ve LLM tabanlı yönlendirmede hatanın nedeni izlenemez.
Kural tabanlı yapı test edilebilir ve aynı soru her zaman aynı yola gider.

Sorudan çıkarılan slotlar: banka, ürün tipi, metrik, aktiflik durumu, sıralama
sinyali, sayma sinyali, özel isim varlığı.

| Sinyal | Yol |
|---|---|
| "en uzun", "en yüksek", "hangi banka", "karşılaştır" | SQL |
| "kaç tane", "kaç kampanya", "listele" | SQL |
| "kaç taksit", "kaç ay", "ne kadar indirim" | RAG |
| Sözlükte olmayan özel isim (marka adı) | RAG |
| "nedir", "nasıl işler", "koşulları" | RAG |

**Öncelik kuralı:** Sıralama sinyali diğerlerini ezer. "Araç finansmanında en uzun
vade kaç ay?" sorusunda "kaç ay" RAG sinyali olmasına rağmen "en uzun" ifadesi
toplu veri gerektirdiği için soru SQL'e yönlenir.

### 5.2 SQL katmanı (sql_arac.py)

**Sıralama cevapları dil modeline yazdırılmaz.** "En uzun vadeli konut finansmanı
hangi bankada?" gibi sorularda cevap, veritabanı sonucundan şablonla üretilir.

Gerekçe deneyle belirlenmiştir. Bu tür sorularda cevap zaten bir olgu listesidir;
dil modelinin katkısı yalnızca ifadedir, buna karşılık gözlemlenen riskler somuttur:
aynı değeri sunan yedi bankadan birini seçip tek cevap gibi sunma, sorgu sonucundaki
ilgisiz satırlardan (arsa finansmanı) yanlış değer okuma ve kaynakta bulunmayan vade
aralığı önerme. Prompt düzeyinde iki farklı düzeltme denenmiş, ikisi de yetersiz
kalmıştır.

Şablon yaklaşımı üç kazanım sağlar: cevap her zaman veriyle birebir tutarlıdır,
tekrarlanabilirdir ve 0.01 saniyede üretilir. Şartnamenin chatbot tanımı olan
"kullanıcının sorusunu analiz ederek ilgili veri alanını tespit etme ve doğru bilgiyi
sunma" davranışı korunur; şartnamenin örnek chatbot cevapları da yapılandırılmış
biçimdedir.

Dil modeli, gerçekten anlama ve sentez gerektiren yerlerde devrededir: açıklama
soruları, kampanya detayları, banka karşılaştırmaları, terminoloji düzeltmeleri.

LLM'e serbest SQL yazdırılmaz; **şablon + parametre** yaklaşımı kullanılır.
Gerekçeleri: SQL enjeksiyonu imkânsızdır, aynı soru her zaman aynı sorguyu üretir,
ve sorgular test edilebilir. Bedeli, kalıp dışına çıkan soruların RAG'e düşmesidir —
bu güvenli bir geri düşüştür.

Üç şablon: sıralama, sayma, karşılaştırma.

### 5.3 Retrieval katmanı (getir.py)

1. **Metadata filtresi** — banka, geçerlilik durumu, liste sayfası hariç tutma
2. **Vektör araması** — 30 aday
3. **Alaka kontrolü** — göreli eşik (aşağıda)
4. **Belge çeşitliliği** — aynı belgeden en fazla 2 chunk
5. **Top-k** — 6 chunk

**Alaka kontrolü göreli çalışır.** Mutlak eşik (belirli bir skorun altını elemek)
denenmiş ve başarısız olmuştur: soru tarzına göre benzerlik skorları 0.55–0.80
arasında gezindiği için sabit eşik meşru soruları da elemiştir. Bunun yerine önce
"en iyi eşleşme yeterince iyi mi" sorulur (taban 0.55), değilse hiç sonuç
döndürülmez; iyiyse en iyiden 0.15'ten fazla geride kalan adaylar elenir.

### 5.4 Sohbet bağlamı yönetimi

Takip sorularını çözmek için önceki turlar saklanır, fakat iki kısıtla:

**Yalnızca kullanıcı soruları saklanır, modelin cevapları saklanmaz.** Modelin kendi
çıktısını geri beslemek, önceki cevabın iddialarını yeni cevaba taşır. Gözlemlenen
bir örnekte aynı soru ilk seferde doğru ("Türkiye Emlak, 2 puan"), ikinci seferde
yanlış ("Kuveyt Türk, 10 puan") cevaplanmıştır; neden, ilk cevabın kaynak listesinde
geçen bankanın ikinci cevaba sızmasıdır. Takip sorusunu çözmek için gereken şey
önceki *soru*, önceki *cevap* değildir.

**Bağlam yalnızca gerçek takip sorularında gönderilir.** Kendi kendine yeten sorular
("Yapı Kredi'nin kampanyası var mı?") temiz bağlamla çalışır; "peki kâr payı ne
kadar?" gibi eksiltili sorular önceki soruların bankasını devralır.

### 5.5 Güvenlik kontrolleri (boru.py)

- **Dil koruması**: Cevapta 3 veya daha fazla Latin dışı harf varsa cevap
  kullanılmaz. Kullanılan model çok dilli olduğundan bağlam zayıfladığında başka
  dile kayabilmektedir; prompt kuralı bunu azaltır fakat garanti etmez.
- **Kaynak tutarlılığı**: Model "bu bilgi kaynaklarda yok" diyorsa kaynak listesi
  temizlenir. Aksi halde kullanıcı reddedilen bir soruda bağlantılar görüp bilgi
  varmış izlenimine kapılır.
- **Sohbet ayrımı**: Selamlama ve teşekkür gibi girdiler retrieval'a hiç gitmez.
- **Terminoloji güvencesi**: Sistem promptu katılım bankacılığı terimlerini zorunlu
  kılar, fakat model kullanıcının yanlış terimini tekrarlayabilmektedir. Bu nedenle
  çıktı üzerinde ikinci bir düzeltme katmanı çalışır: "kâr oranı" → "kâr payı oranı",
  "faiz oranı" → "kâr payı oranı", "kredi çekmek" → "finansman kullanmak".

### 5.6 Geçerlilik bilgisi

Kampanya geçerliliği modele hesaplattırılmaz. Her kaynak bloğuna
`DURUM: SÜRESİ DOLMUŞ` etiketi yazılır. Tarih karşılaştırmasını modele bırakmak
hataya açıktır: gözlemlenen bir örnekte model "31 Aralık 2025" tarihini cevabında
yazdığı hâlde kampanyayı "hâlâ geçerli" olarak sunmuştur.

---

## 6. Farklı Bankalara Ait Benzer Ürünlerin Nasıl Karşılaştırıldığı

Karşılaştırma, metinlerin ortak bir şemaya indirgenmesiyle mümkün olur. Her belge
`urun_tipi` alanına sınıflandırılır (konut, araç, ihtiyaç, kart, katılma hesabı vb.)
ve karşılaştırılabilir sayısal alanlar normalize edilerek çıkarılır.

### Şartname 5.7'de belirtilen beş kriter

| Kriter | Alan | API ucu |
|---|---|---|
| En düşük kâr payı oranı | `kar_payi_orani` | `/panel/kriterler` |
| En yüksek ödül miktarı | `odul_miktari` | `/panel/kriterler` |
| En uzun vade seçeneği | `vade_ay_max` | `/panel/kriterler` |
| En düşük masraf | `tahsis_ucreti`, `masraf_bilgisi` | `/panel/kriterler` |
| En avantajlı kampanya | `indirim_orani` | `/panel/kriterler` |

Karşılaştırma hem dashboard'daki "Kriterler" sekmesinde tablo olarak, hem de
chatbot üzerinden doğal dille sunulur.

### Örnek

Kullanıcı: *"Kuveyt Türk ile Albaraka'nın konut finansmanını karşılaştır"*

Sistem her iki bankanın konut finansmanı kayıtlarını `urun_tipi='konut'` filtresiyle
çeker, maksimum vade, kâr payı oranı ve tutar alanlarını yan yana koyar, sonucu
LLM'e vererek doğal dilde açıklatır. Sayısal değerler modelden değil veritabanından
gelir; model yalnızca ifade eder.

---

## 7. Projenin Çalıştırılması İçin Adım Adım Talimatlar

### Gereksinimler

- Python 3.10+
- NVIDIA GPU (8 GB+ VRAM önerilir; CPU ile de çalışır, daha yavaştır)
- Ollama (https://ollama.com/download)
- ~12 GB disk (model dosyaları dâhil)

### Kurulum

```bash
unzip katilim_rag_sistem.zip
cd sistem
python kur.py --kontrol        # eksikleri listeler, indirme yapmaz
python kur.py                  # bağımlılıklar + model + index
```

`kur.py` sırasıyla: Python sürümü ve disk alanını denetler, GPU tespit eder,
CUDA'lı torch kurar, bağımlılıkları yükler, Ollama modelini indirir ve Chroma
indeksini oluşturur. Yarıda kesilirse aynı komut kaldığı yerden devam eder.

### Çalıştırma

```bash
python -m uvicorn katilim_rag.api:app --port 8000    # http://localhost:8000
python -m katilim_rag.cli                            # terminal arayüzü
python -m katilim_rag.cli -s "soru" --detay          # retrieval ayrıntısı
python -m katilim_rag.cli -s "soru" --llmsiz         # LLM'siz, yalnız retrieval
```

**8 GB VRAM notu:** Gömme modeli ile LLM aynı anda GPU'ya sığmaz.
`SORGU_CIHAZ=cpu` ile gömme modeli CPU'ya alınmalıdır; tek sorgunun gömülmesi
CPU'da yaklaşık 0.1 saniye sürer, buna karşılık LLM'in tamamı GPU'da kalır.
Bu ayar olmadan cevap süresi 185 saniyeye kadar çıkmaktadır.

### Ayarlanabilir parametreler

Tümü `config.py` içinde veya ortam değişkeniyle:

| Parametre | Varsayılan | Açıklama |
|---|---|---|
| `TOP_K_ARAMA` | 12 | vektör aramasından çekilen aday |
| `TOP_K_CEVAP` | 8 | LLM'e verilen chunk |
| `DOC_BASINA_MAX` | 2 | aynı belgeden azami chunk |
| `MIN_VEKTOR_SKOR` | 0.55 | alaka tabanı |
| `GORELI_BANT` | 0.15 | en iyiye göre eleme bandı |
| `SICAKLIK` | 0.0 | deterministik üretim |
| `RERANK_AKTIF` | 1 | cross-encoder yeniden sıralama |

---

## 8. Karşılaşılan Problemler ve Çözüm Yaklaşımları

### 8.1 Kâr payı oranlarının kaynakta bulunmaması

**Problem.** Şartnamenin ilk sırada saydığı alan olan kâr payı oranı, 1114 kaydın
yalnızca 23'ünde tespit edilebilmiştir. İnceleme sonucunda sorunun çıkarım
algoritmasında değil, kaynak veride olduğu görülmüştür. Bankaların oran tabloları
JavaScript ile istemci tarafında doldurulmakta, statik HTML çekildiğinde tablo
başlıkları gelmekte fakat değerler boş kalmaktadır:

```
Finans Portalı Kâr Payı Oranları   1 Ay %   3 Ay %   6 Ay %   1 Yıl %
```

**Çözüm yaklaşımı.** Playwright tabanlı, JavaScript çalıştırıp render sonrası tabloyu
okuyan bir toplayıcı geliştirilmiştir (`scrape_oranlar.py`). Toplayıcı çerez
bannerlarını metin eşleşmesiyle kapatır, lazy-load içerik için sayfayı kaydırır,
akordeon ve sekmeleri açar, `%` + rakam görünene kadar bekler. Hedef sayfa listesi
mevcut veriden türetilmiştir (`hedef_sayfalar.csv`, 59 sayfa).

**Durum.** Toplayıcı geliştirilmiş ve test edilmiştir; yarışma süre kısıtı nedeniyle
toplanan verinin sisteme entegrasyonu tamamlanamamıştır. Dashboard bu eksikliği
kullanıcıya açıkça bildirir.

### 8.2 Metadata alanının sessizce ezilmesi

**Problem.** İndeksleme sırasında `doc_id` alanı, chunk metadata'sında bulunmadığı
için boş değerle ezilmekteydi. Sonuç olarak belge çeşitliliği filtresi tüm chunk'ları
tek belgeden geliyormuş gibi değerlendiriyor ve LLM'e 6 yerine yalnızca 2 chunk
gidiyordu. Hata dışarıdan görünmüyordu; cevaplar makul görünmekle birlikte üçte bir
bağlamla üretiliyordu.

**Çözüm.** İndeksleme düzeltilmiş, ayrıca mevcut indeksleri yeniden kurmayı
gerektirmemek için `doc_id` chunk kimliğinden türetilecek şekilde geriye dönük
uyumluluk eklenmiştir.

### 8.3 Marka bazlı soruların yanlış katmana yönlenmesi

**Problem.** "Bellona kampanyasında kaç taksit yapılabiliyor?" sorusundaki "kaç"
ifadesi sayma kuralını tetikliyor, soru SQL katmanına gidiyordu. SQL tablosunda marka
adı bulunmadığından sonuç boş dönüyordu. 14 marka sorusunun tamamı bu nedenle
başarısızdı.

**Çözüm.** İki kural eklenmiştir: (a) "kaç taksit / kaç ay / ne kadar indirim" gibi
belge içi değer soruları sayma sayılmaz, (b) sistemin sözlüğünde bulunmayan bir özel
isim geçiyorsa soru doğrudan RAG'e yönlenir. Yönlendirme doğruluğu %58'den %100'e
çıkmıştır.

Bu ikinci kuralın ilk uygulamasında Türkçe ekleri sonek kırpma ile atmak
denenmiş, yöntem "Albaraka" kelimesini "albar"a indirgediği için her soruyu marka
sorusu sanmıştır. Önek eşleşmesine geçilerek düzeltilmiştir.

### 8.4 Alaka eşiği olmaması ve mutlak eşiğin başarısızlığı

**Problem.** Retrieval katmanı, soru ne olursa olsun en yakın 6 chunk'ı döndürüyordu.
Korpusta bulunmayan bir konu sorulduğunda (örneğin katılım bankası olmayan bir kurum)
model alakasız metinlerle baş başa kalıyor, ya alakasız kaynak listeliyor ya da
uydurmaya yöneliyordu.

**İlk çözüm denemesi ve başarısızlığı.** Mutlak bir benzerlik eşiği (0.62) konulmuş,
genel başarı 0.877'den 0.854'e **düşmüştür**. Neden: soru tarzına göre skorlar
0.55–0.80 arasında değiştiğinden sabit eşik meşru soruları da elemiştir.

**Nihai çözüm.** Göreli eşik: önce en iyi eşleşmenin yeterliliği kontrol edilir,
ardından en iyiden belirli bir bandın gerisinde kalan adaylar elenir.

### 8.5 Modelin başka dile kayması

**Problem.** Bağlam zayıf kaldığında model cevabın ortasında Çince üretmeye
başlamıştır. Sistem promptuna eklenen dil kuralı sıklığı azaltmış fakat tamamen
engelleyememiştir.

**Çözüm.** Prompt kuralına ek olarak çıktı tarafında sert bir kontrol konulmuştur:
cevapta üç veya daha fazla Latin dışı **harf** varsa cevap kullanılmaz. Tek tük
yabancı noktalama (`。`) ise gerçek bir dil kayması sayılmaz, sessizce Türkçe
karşılığına çevrilir.

### 8.6 GPU bellek çakışması

**Problem.** 8 GB VRAM'de gömme modeli (2.2 GB) ile dil modeli (4.7 GB) birlikte
yüklendiğinde Ollama modelin bir kısmını CPU'ya taşımakta, cevap süresi 185 saniyeye
çıkmaktaydı.

**Çözüm.** Gömme modeli sorgu anında CPU'ya alınmıştır (`SORGU_CIHAZ=cpu`).
Tek bir sorgunun gömülmesi CPU'da ihmal edilebilir sürede tamamlanır, buna karşılık
LLM'in tamamı GPU'da kalır. Süre 185 saniyeden 6 saniyeye inmiştir. Ayrıca modelin
bellekten atılmasını engellemek için her istekte `keep_alive` gönderilir.

### 8.7 Reranker cihaz çakışması

**Problem.** Yeniden sıralama modeli, gömme modeliyle aynı cihaz ayarını
paylaşıyordu. Gömme modeli VRAM çakışması nedeniyle CPU'ya alınınca reranker da
CPU'ya düşmüş, 12 adayı uzun bağlamla puanlamak cevap süresine ~60 saniye eklemiştir.

**Çözüm.** Reranker'a ayrı cihaz ayarı verilmiştir: gömme CPU'da (sorgu başına tek
cümle, ihmal edilebilir maliyet), reranker GPU'da. VRAM yetmezse yükleme sırasında
otomatik olarak CPU'ya düşer ve konsola uyarı yazar. Bağlam uzunluğu da chunk
ortalamasına uygun biçimde 512 token'a indirilmiştir. Cevap süresi ısınma sonrası
4-6 saniyeye inmiştir.

**Not.** İlk sorgu, model belleğe yüklendiği için 40-60 saniye sürebilir. Demo
öncesinde bir ısıtma sorgusu yapılması önerilir.

### 8.8 Ölçüm aracının kendi hataları

Değerlendirme sisteminin ürettiği bazı bayrakların sistem hatası değil ölçüm hatası
olduğu tespit edilmiştir:

- Sayı ayrıştırma deseni `2026` yılını `202` + `6` olarak bölüyor ve her cevapta
  sahte bir "dayanaksız sayı" uyarısı üretiyordu.
- HTTP adaptörü sunucu cevabını üç alana kırpıyor, sayısal dayanak denetimi için
  gereken chunk içerikleri kaybolduğundan doğru sayılar dayanaksız görünüyordu.
- Reddetme kalıbı sistemdekinden dar olduğu için doğru reddetmeler "uydurma riski"
  olarak işaretleniyordu.

Bu bulgu, ölçüm aracının da doğrulanması gerektiğini göstermektedir.

---

## 9. Model Çıktılarının Örnekleri

### 9.1 Yapılandırılmış çıktı (metin → veri)

**Girdi (ham kampanya metni):**
> "Vakıf Katılım müşterileri Lizay Pırlanta mağazalarında yapacakları pırlanta
> alışverişlerinde %50'ye varan indirim fırsatından yararlanabilir…"

**Çıktı (yapılandırılmış kayıt):**

```json
{
  "banka_adi": "Vakıf Katılım Bankası A.Ş.",
  "baslik": "Lizaydan Yapacaginiz Taki Alisverislerinizde 50ye Varan Indirim",
  "belge_turu": "kampanya",
  "kampanya_turu": "kart_kampanyasi",
  "urun_tipi": "kredi_karti",
  "indirim_orani": 50.0,
  "kampanya_bitis": "2026-12-01",
  "gecerlilik": "aktif",
  "hedef_kitle": "mevcut_musteri",
  "kaynak_url": "https://www.vakifkatilim.com.tr/..."
}
```

### 9.2 SQL yolu — sıralama sorusu

**Soru:** "En uzun vadeli konut finansmanı hangi bankada?"
**Yol:** SQL (0.05 sn)
**Cevap:** Kuveyt Türk, Albaraka Türk, Türkiye Emlak Katılım, Türkiye Finans,
Ziraat Katılım ve Vakıf Katılım konut finansmanında 120 aya varan vade sunmaktadır.

Sayısal değer veritabanından gelir; model yalnızca ifade eder. Bu soru RAG ile
cevaplansaydı yalnızca çekilen 6 chunk içindeki en büyük değer bildirilirdi.

### 9.3 RAG yolu — açıklama sorusu

**Soru:** "Katılma hesabı nasıl işliyor?"
**Yol:** RAG, 5 farklı bankadan 6 chunk
**Cevap:** Müşteri katılım bankasıyla ortaklık kurar ve belirli bir tutarı katılma
hesabına yatırır. Bu fon, faizsiz bankacılık ilkelerine uygun olarak ticaret, sanayi
ve hizmet sektörlerinin finansmanında kullanılır. Elde edilen kâr veya zarar,
havuzdaki hisse oranında paylaşılır. Önceden taahhüt edilen bir getiri yoktur.

### 9.4 Tuzak sorusu — korpusta bulunmayan kurum

**Soru:** "Halkbank Katılım'ın konut finansmanı kaç ay vadeli?"
**Cevap:** Eldeki kaynaklarda Halkbank Katılım'ın konut finansmanı hakkında bilgi
bulunmamaktadır.

Kaynak listesi boş döner; sistem mevcut olmayan bilgi için bağlantı sunmaz.

### 9.5 Terminoloji düzeltmesi

**Soru:** "Bu kampanyaların faiz oranları ne kadar?"
**Cevap:** Katılım bankacılığında faiz değil kâr payı uygulanır. [devamında kâr payı
bilgisi]

---

## 10. Modelin Performansını Değerlendirmek İçin Kullanılan Yöntemler

### 10.1 Değerlendirme seti

138 soruluk bir set oluşturulmuştur. Set iki bağımsız kaynağın birleşimidir; bu,
sistemin kendi test verisine aşırı uyum sağlamasını (overfitting) tespit etmek
amacıyla bilinçli bir tercihtir.

| Kaynak | Soru | Özellik |
|---|---|---|
| İç set | 44 | Altın cevaplar doğrudan veritabanından üretilmiştir |
| Bağımsız set | 94 | Sistem bilinmeden yazılmıştır |

Soru kategorileri: tanım, sıralama, sayma, karşılaştırma, kampanya detayı,
kampanya sayısal, kademeli ödül, hedef kitle, hariç tutma, ifade varyantı,
geçerlilik, halüsinasyon tuzağı, dayanıklılık (prompt enjeksiyonu), kapsam dışı,
sohbet, bozuk yazım.

### 10.2 Metrikler

Değerlendirme **tamamen deterministiktir; LLM hakem kullanılmaz.** Gerekçe: hakem
model kullanıldığında puan çalıştırmalar arası dalgalanır ve bir iyileştirmenin
gerçek mi gürültü mü olduğu ayırt edilemez.

| Metrik | Ölçtüğü |
|---|---|
| `anahtar_kapsam` | Beklenen terimlerin cevapta bulunma oranı |
| `deger_dogru` | Beklenen sayısal değerin doğruluğu |
| `banka_isabet` | Doğru bankanın tespiti |
| `yasak_temiz` | Yasaklı ifade (terminoloji hatası) yokluğu |
| `yol_dogru` | Sorunun doğru katmana yönlendirilmesi |
| `kaynak_var` | Kaynak gösterimi |
| `sayi_dayanakli` | Cevaptaki sayıların kaynaklarda bulunması |
| `bos_sonuc` | Kapsam dışı soruda kaynak uydurmama |
| `davranis` | Tuzak sorularda doğru davranış |

### 10.3 Sonuçlar ve gelişim

| Aşama | Puan | Not |
|---|---|---|
| İlk ölçüm (44 soru) | 0.748 | — |
| Yönlendirme + metadata düzeltmesi | 0.905 | İki kritik hata giderildi |
| Birleşik set (138 soru) | 0.877 | Bağımsız sorular eklendi |
| Güvenlik katmanları (dil koruması, eşik, geçerlilik) | 0.84 – 0.90 | Ayar döngüleri |
| Veri birleştirme (1.114 kayıt) + tüm katmanlar | 0.865 | Zengin veri entegre edildi |
| **Sohbet bağlamı izolasyonu + terminoloji katmanı** | **0.875** | Nihai sürüm |

**Son durum:** 0.875 (iç set 0.911, bağımsız set 0.857).

Tam puan alan kategoriler: kampanya araması, kampanya detayı, sayma, ürün soruları,
sohbet, bozuk yazım toleransı. Diğer güçlü sonuçlar: yönlendirme isabeti 0.935,
şartname kapsam kontrolü 0.92, değer doğruluğu 0.87, terminoloji uyumu 0.993,
sayısal dayanak 0.982.

Bağımsız sette (sistem bilinmeden yazılmış 94 soru) elde edilen 0.857, iç setteki
0.911'e yakındır; aradaki fark aşırı uyum (overfitting) sınırları içindedir.

Bağımsız sette elde edilen puanın iç sete yakın olması, sistemin kendi test verisine
aşırı uyum sağlamadığını göstermektedir.

### 10.4 Ölçümün sınırları

Bu değerlendirme setinin **mutlak bir başarı ölçüsü olmadığı** belirtilmelidir.
Sorular ve altın cevaplar proje ekibince belirlenmiştir. Metrikler kelime
eşleşmesine dayandığından, doğru bilgiyi farklı kelimelerle ifade eden bir cevap
puan kaybedebilmektedir.

Ölçümün asıl değeri mutlak puan değil, **iyileştirmeleri izlenebilir kılmasıdır.**
Nitekim gözle fark edilemeyecek üç ciddi hata (bölüm 8.2, 8.3, 8.4) bu sayede
tespit edilmiştir.

Ayrıca ölçümler arası ±0.02 dalgalanma gözlenmiştir. Dil modelinin üretim sıcaklığı
0.0'a çekilerek üretim deterministik hâle getirilmiş, böylece sonraki ölçümlerin
tekrarlanabilirliği sağlanmıştır.

### 10.5 Test aracının taşınabilirliği

Değerlendirme aracı belirli bir sisteme bağlı değildir; HTTP ucu veya Python
fonksiyonu üzerinden herhangi bir RAG sistemine bağlanabilir. Veri kümesinden
bağımsız 10 soru ayrıca işaretlenmiştir; farklı korpusla çalışan sistemler
`--sadece-genel` bayrağıyla adil biçimde ölçülebilir.

---

## Ek: Bilinen Eksikler

- **Tekrarlanabilirlik:** `veri/katilim.db`, ham kurulum scripti (`build_db.py`)
  çıktısının üzerine uygulanan zenginleştirmelerin ürünüdür; `build_db.py` tek
  başına bu DB'yi birebir üretmez. Bu nedenle veri düzeltmeleri
  `migrasyon_2026_08.py` ile kayıt-bazlı ve idempotent uygulanır (kâr payı
  artefakt temizliği — 9 hücre, `kampanya_turu` kanonlaştırması,
  `dolayli_kar_payi` etiketleme). Teslim edilen DB esas alınmalıdır; ezilmemelidir.
- **İktisat Katılım (BDDK faaliyet izni 26.02.2026):** ad çözümleme sözlüğüne
  eklendi; ürün verisi toplanacak.

Şeffaflık amacıyla, tamamlanamayan hususlar aşağıda listelenmiştir:

1. **Kâr payı oranı kapsamı** — 1.114 kaydın 178'inde mevcut (%16). Yapılandırılmış
   veri seti entegrasyonuyla ilk sürümdeki %2.6'dan sekiz kat artırılmıştır; kalan
   eksikliğin nedeni ve çözüm yaklaşımı bölüm 8.1'de açıklanmıştır.
2. **Masraf bilgisi kapsamı** — 36 belge. Bu bilginin kaynak metinlerde seyrek
   bulunması nedeniyledir.
3. **Güncellik kategorisi** — 0.63'tür; belirli bir kampanyanın en güncel sürümünü
   ayırt etme konusunda iyileştirmeye açıktır.
4. **Kısa sorgular** — 0.6'dır. Bağlamsız anahtar kelime girdileri ("KUVEYT TÜRK
   KATILMA HESABI") niyet çıkarımı için yeterli sinyal taşımamaktadır.
