# LinguaTech — Evrensel Kurulum Rehberi

Bu sürüm Windows, Linux ve macOS üzerinde temiz bir kullanıcı hesabından
kurulabilecek şekilde hazırlanmıştır. Kurulum proje içinde `.venv` adlı yalıtılmış
bir Python ortamı oluşturur; bilgisayardaki diğer Python projelerini değiştirmez.

Kurulum aracı yalnızca desteklenen bileşenleri otomatik kurar. İşletim sistemi
uygulaması olan **Ollama**, kullanıcı tarafından bir kez kurulmalıdır.

## 1. Sistem gereksinimleri

| Gereksinim | Destek / öneri |
|---|---|
| İşletim sistemi | 64 bit Windows 10/11, güncel Linux veya macOS |
| Python | 64 bit Python 3.10, 3.11 veya 3.12 |
| Boş disk | En az 12 GB; 20 GB önerilir |
| Bellek | 7B model için 16 GB RAM önerilir; düşük bellekte 3B model kullanılabilir |
| İnternet | İlk kurulum ve model indirmeleri için gerekli |
| GPU | Zorunlu değil; NVIDIA, Apple Silicon veya yalnız CPU kullanılabilir |

Python 3.13 bu teslim sürümünde kullanılmamalıdır. PyTorch'un resmi kurulum
matrisi Python 3.9–3.12 aralığını temel aldığı için kurulum aracı 3.10–3.12 ile
sınırlandırılmıştır.

## 2. Önce Ollama'yı kurun

Ollama'yı işletim sisteminize uygun paketle kurun:

- <https://ollama.com/download>

Kurulumdan sonra Ollama uygulamasını açın. Linux'ta servis otomatik başlamadıysa:

```bash
ollama serve
```

Bu komut terminali meşgul edeceği için gerekiyorsa ayrı bir terminalde çalıştırın.

## 3. Tek komutla kurulum

Önce bu projenin kök klasöründe terminal açın. `kur.py`, `gereksinimler.txt`,
`katilim_rag/` ve `veri/` aynı proje kökünde bulunmalıdır.

### Windows PowerShell veya Komut İstemi

```powershell
python kur.py
```

### Linux veya macOS

```bash
python3 kur.py
```

Kurulum aracı sırasıyla:

1. Python sürümünü, mimariyi ve boş disk alanını kontrol eder.
2. Proje içinde `.venv` oluşturur.
3. Uyumlu Python paketlerini bu sanal ortama kurar.
4. `BAAI/bge-m3` gömme modelini indirir.
5. `BAAI/bge-reranker-v2-m3` reranker modelini indirir.
6. Ollama'daki `qwen2.5:7b-instruct` modelini kontrol eder ve eksikse indirir.
7. Teslim edilen Chroma indeksini gerçekten açıp kayıt okur.
8. İndeks bozuk veya uyumsuzsa silmez; `chroma_yedek_TARIH_SAAT` adıyla
   yedekleyip yeniden oluşturur.
9. SQL yolu ile gömme–Chroma–reranker zincirini uçtan uca test eder.

Kurulum yarıda kesilirse aynı komutu tekrar çalıştırabilirsiniz. Tamamlanmış
adımlar yeniden kullanılacaktır.

## 4. Uygulamayı çalıştırma

Kurulum tamamlandıktan sonra sistem Python'u yerine proje içindeki `.venv`
yorumlayıcısını kullanın.

### Windows

```powershell
.\.venv\Scripts\python.exe -m uvicorn katilim_rag.api:app --port 8000
```

### Linux veya macOS

```bash
./.venv/bin/python -m uvicorn katilim_rag.api:app --port 8000
```

Tarayıcıdan açın:

<http://localhost:8000>

Terminal arayüzü için:

```powershell
# Windows
.\.venv\Scripts\python.exe -m katilim_rag.cli
```

```bash
# Linux veya macOS
./.venv/bin/python -m katilim_rag.cli
```

## 5. Kurulumu doğrulama

Hızlı ve salt okunur kontrol:

```bash
python kur.py --kontrol
```

Linux/macOS'ta `python` yerine `python3` kullanabilirsiniz. Gömme modeli,
Chroma sorgusu ve reranker ile gerçek RAG testi de yapılsın:

```bash
python kur.py --kontrol --tam
```

`--kontrol` hiçbir paket indirmez, indeks oluşturmaz veya dosya değiştirmez.

## 6. GPU'suz veya düşük donanımlı bilgisayar

GPU zorunlu değildir. İndeksi kesin olarak CPU ile oluşturmak için:

```bash
python kur.py --cpu
```

CPU üzerinde kurulum ve cevap üretimi çalışır; ilk indeksleme ve RAG soruları daha
uzun sürebilir. Hazır indeks sağlamsa yeniden indeksleme yapılmaz.

7B model için belleği yetersiz bilgisayarda daha küçük Ollama modeli kurulabilir:

```bash
python kur.py --model qwen2.5:3b-instruct
```

Farklı model seçildiğinde uygulamayı aynı model adıyla başlatın.

### Windows PowerShell

```powershell
$env:LLM_MODEL="qwen2.5:3b-instruct"
.\.venv\Scripts\python.exe -m uvicorn katilim_rag.api:app --port 8000
```

### Linux veya macOS

```bash
LLM_MODEL=qwen2.5:3b-instruct ./.venv/bin/python -m uvicorn katilim_rag.api:app --port 8000
```

Apple Silicon'da kullanılabilir MPS aygıtı otomatik seçilir. NVIDIA bilgisayarda
kurulu PyTorch CUDA'yı görebiliyorsa CUDA otomatik seçilir. CUDA görülmüyorsa sistem
CPU ile çalışmaya devam eder. NVIDIA'ya özel PyTorch kurulumu gerekiyorsa güncel
komutu <https://pytorch.org/get-started/locally/> sayfasından alın; sabit bir CUDA
sürümünü her bilgisayara zorlamak doğru değildir.

## 7. Gelişmiş seçenekler

| Seçenek | Etkisi |
|---|---|
| `--kontrol` | İndirme ve değişiklik yapmadan sistemi denetler |
| `--kontrol --tam` | Salt okunur kontrole gerçek RAG sorgusu ekler |
| `--cpu` | İndekslemede CUDA/MPS kullanmaz |
| `--hizli` | İlk kurulum sonunda ağır RAG testini atlar |
| `--offline` | Yalnız daha önce indirilmiş modelleri kullanır |
| `--indeksi-yenile` | Çalışan indeksi yedekleyip yeniden oluşturur |
| `--model MODEL_ADI` | Kullanılacak Ollama modelini belirler |

İlk başarılı kurulumdan sonra internet bağlantısı olmayan ortamda kontrol için:

```bash
python kur.py --kontrol --tam
```

Uygulamanın RAG katmanı çalışma zamanında Hugging Face ağına bağlanmaz; modelleri
yalnız yerel önbellekten açar.

## 8. ChromaDB neden 0.6.3'e sabitlendi?

Teslim edilen `veri/chroma` dizini ChromaDB 0.6.x dosya ve API yapısıyla
oluşturulmuştur. `chromadb>=0.5` gibi üst sınırı olmayan bir tanım, ileride farklı
bir ana sürüm kurarak hazır indeksle uyumsuzluk oluşturabilir. Bu nedenle:

```text
chromadb==0.6.3
```

kullanılır. Kurulum ayrıca klasörün yalnızca var olmasını yeterli saymaz; koleksiyonu
açar, kayıt sayısını okur ve diskten örnek kayıt çeker.

## 9. Sorun giderme

### `.venv` oluşturulamıyor

Linux dağıtımınızda venv bileşeni eksik olabilir. Debian/Ubuntu örneği:

```bash
sudo apt install python3-venv
```

Ardından `python3 kur.py` komutunu tekrar çalıştırın.

### Ollama'ya bağlanılamıyor

Ollama uygulamasını açın veya ayrı terminalde `ollama serve` çalıştırın. Kurulum
aracı Python ve RAG bileşenlerini hazırlamaya devam eder ancak Ollama hazır değilse
başarı kodu vermez.

### Model indirilemiyor

İlk kurulumda internet, güvenlik duvarı ve disk alanını kontrol edin. Kurumsal ağ
Hugging Face veya Ollama erişimini engelliyorsa modelleri internet erişimi olan aynı
kullanıcı hesabında bir kez indirin.

### Chroma indeksi bozuk

`python kur.py` komutunu tekrar çalıştırın. Araç bozuk indeksi otomatik olarak
`veri/chroma_yedek_*` klasörüne taşır ve yenisini oluşturur. Yedek kendiliğinden
silinmez.

### Kurulum hızlı kontrolü geçti ama RAG çalışmıyor

```bash
python kur.py --kontrol --tam
```

Bu test gömme modelini, Chroma sorgusunu ve reranker modelini aynı zincirde çalıştırır
ve hatanın gerçek kaynağını gösterir.

## 10. İsteğe bağlı veri tarama araçları

Ana uygulama için Playwright tarayıcı dosyaları zorunlu değildir. Yalnızca
`scrape_oranlar.py` gibi tarama araçları kullanılacaksa sanal ortam içinden tarayıcıyı
bir kez kurun:

```powershell
# Windows
.\.venv\Scripts\python.exe -m playwright install chromium
```

```bash
# Linux veya macOS
./.venv/bin/python -m playwright install chromium
```
