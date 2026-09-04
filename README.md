# MakineRAG

Tamamen **yerelde** calisan, taranmis PDF'ler icin Turkce soru-cevap ve konu haritasi sistemi.

- Belgeler **Ingilizce / Romence** taranmis PDF olabilir -> Tesseract OCR ile metne cevrilir.
- Sorular ve cevaplar, basliklar, ozetler ve raporlar **Turkce** uretilir.
- Internet gerekmez (ilk kurulumda model indirmeleri haric). Veri disari cikmaz.

---

## 1. Mimari

```
data/pdf/*.pdf
      |
      v  [ocr.py]  gomulu metin katmani varsa onu al, yoksa 300 DPI render + Tesseract (ron+eng)
data/ocr/<doc_id>.json          sayfa sayfa metin + OCR bayragi
      |
      v  [metadata.py]  kural (takma ad eslesmesi) + LLM ile siniflandirma
data/manifest.jsonl             makine kodu, belge turu, Turkce baslik/ozet/anahtar kelimeler
      |
      v  [chunk.py + embed.py + index_build.py]
data/index/                     Chroma (bge-m3 vektorleri) + bm25.pkl
      |
      +--> [retrieve.py]  TR sorgu -> EN/RO'ya cevrilir -> yogun + BM25 -> RRF -> makine filtresi
      +--> [chat.py]      Turkce, kaynak numarali cevap
      +--> [report.py]    makine bazli Turkce konu/baslik haritasi (map-reduce)
      |
      v  [server/api.py]  FastAPI: JSON uc noktalari + SSE ile token akisi
   web/  index.html + style.css + app.js   (cerceve yok, CDN yok, cevrimdisi calisir)
```

### HTTP arayuzu

| Uc nokta | Isi |
|---|---|
| `GET /api/durum` | belge/sayfa/parca sayilari, model adlari, Ollama ve motor durumu |
| `GET /api/makineler` | makine listesi + belge sayilari (yan paneldeki filtre) |
| `GET /api/turler` | belge turu dagilimi |
| `GET /api/belgeler` | `makine`, `tur`, `q`, `sirala`, `yon`, `limit`, `ofset` ile filtreli liste |
| `GET /api/belge/{id}` | tek belge: meta + sayfa sayfa OCR durumu ve onizleme |
| `GET /api/belge/{id}/pdf` | orijinal PDF (tarayicida `#page=N` ile ilgili sayfa acilir) |
| `POST /api/sor` | **SSE akisi**: once `kaynaklar`, sonra `parca` token'lari, sonunda `bitti` |
| `GET/POST /api/raporlar` | konu haritalarini oku / arka planda uret |
| `GET /api/isler` | uzun suren rapor islerinin durumu |

Etkilesimli API dokumantasyonu: <http://127.0.0.1:8000/api/docs>

Arayuzun tamami tek bir HTML + CSS + JS uclusudur; harici font, CDN veya JS cercevesi
kullanmaz, bu yuzden internetsiz ortamda da sorunsuz acilir.

### Neden bu secimler

| Karar | Sebep |
|---|---|
| **Cok dilli gomme modeli** | Turkce soru ile Ingilizce/Romence belge ayni vektor uzayinda eslesmeli. Varsayilan `bge-m3`; `Qwen/Qwen3-Embedding-0.6B` yari boyutta bir alternatif. Hangisinin sizin belgelerinizde daha iyi oldugunu olcmek icin bkz. bolum 6. `nomic-embed-text` tek dillidir, bu is icin uygun degildir. |
| **Hibrit arama (yogun + BM25)** | Parca numarasi, hata kodu, olcu degeri gibi tam eslesmeler icin BM25; kavramsal sorular icin vektor aramasi. |
| **Sorgu cevirisi** | BM25 kelime esler; Turkce "yaglama" ile Ingilizce "lubrication" eslesmez. LLM sorguyu EN/RO'ya da cevirir. |
| **Yapisal parcalama + baglam oneki** | Kilavuzlar bolum basliklarinda bolunur, tablolar bolunmez; gomulen metnin basina Turkce belge/bolum basligi eklenir. Bkz. bolum 5. |
| **Sayfa bazli izleme** | Her cevap `dosya.pdf s.42` seklinde dogrulanabilir kaynak verir. |
| **Kaldigi yerden devam** | 1000+ PDF'in OCR'i saatler surer; her adim tekrar calistirildiginda islenmisleri atlar. |

---

## 2. Kurulum

```powershell
powershell -ExecutionPolicy Bypass -File D:\MakineRAG\kurulum.ps1
```

Betik sunlari yapar: sanal ortam, Python paketleri, GPU kontrolu, Tesseract + Romence dil paketi
kontrolu, Ollama model kontrolu.

Tesseract kurulu degilse:

```powershell
winget install --id UB-Mannheim.TesseractOCR -e --source winget
```

`--source winget` gereklidir: kurumsal agda `msstore` kaynagi SSL kesmesi yuzunden hata verir.

Yonetici izni olmadan kurulunca Tesseract `%LOCALAPPDATA%\Programs\Tesseract-OCR` altina
gider; `src/ocr.py` bu yolu da arar, ek ayar gerekmez.

Kurulum sihirbazinda **Additional language data -> Romanian** secilmelidir. Secilmezse
`ron.traineddata` eksik kalir; `kurulum.ps1` bunu `tessdata_best` deposundan otomatik indirir.
`tessdata_best` daha dogru ama daha yavastir; OCR suresini yaklasik yariya indirmek icin
ayni dosyayi `tesseract-ocr/tessdata` deposundan alabilirsiniz.

Dogrulama:

```powershell
D:\MakineRAG\.venv\Scripts\python.exe scripts\test_kurulum.py
```

---

## 3. Kullanim

### Adim 0 - Hazirlik
1. PDF'leri `D:\MakineRAG\data\pdf\` icine kopyalayin (alt klasorler de taranir).
2. `config.yaml` icindeki `makineler` bolumune **gercek makine adlarinizi** yazin:

```yaml
makineler:
  - kod: "A"
    ad: "Hidrolik Pres 250T"
    takma_adlar: ["HP-250", "Press 250T", "Presa 250T", "HP250"]
  - kod: "B"
    ad: "CNC Torna TX-40"
    takma_adlar: ["TX-40", "TX40", "Strung CNC TX-40"]
```

Takma adlar belge metninde ve dosya adinda aranir; ne kadar cok varyant yazarsaniz
siniflandirma o kadar dogru olur. Dosya adindaki eslesme govdedekinden 5 kat agir sayilir.

**Takma adlar ayirt edici olmali (en az 3 karakter).** `kod` alanindaki tek harfli
degerler metin taramasinda kullanilmaz: "A" gibi bir desen Romence metindeki bagimsiz
"a" kelimesiyle eslesir ve belgeleri yanlis makineye atar. Ayirt edici olan
`MK-A`, `HP-250`, `TX-40` gibi adlari yazin. (Tek harfli kod yalnizca LLM'in
dondurdugu makine adayini eslestirirken kullanilir.)

### Adim 1 - Boru hattini calistir

```powershell
cd D:\MakineRAG
.\.venv\Scripts\python.exe src\cli.py tumu          # OCR + meta + indeks
```

Tek tek de calistirilabilir:

```powershell
.\.venv\Scripts\python.exe src\cli.py ocr           # sadece OCR   (en uzun adim)
.\.venv\Scripts\python.exe src\cli.py meta          # siniflandirma
.\.venv\Scripts\python.exe src\cli.py index         # vektor + BM25 indeksi
.\.venv\Scripts\python.exe src\cli.py durum         # nerede kaldigini goster
```

Once kucuk bir orneklemle deneyin:

```powershell
.\.venv\Scripts\python.exe src\cli.py ocr --limit 20
```

### Adim 2 - Filtreleme ve basliklar

```powershell
# A makinesinin belgeleri
.\.venv\Scripts\python.exe src\cli.py listele --makine A

# Sadece bakim talimatlari
.\.venv\Scripts\python.exe src\cli.py listele --makine A --tur "bakim talimati"

# A makinesi icin Turkce konu haritasi -> data\raporlar\makine_A_konu_haritasi.md
.\.venv\Scripts\python.exe src\cli.py rapor --makine A

# Tum makineler icin
.\.venv\Scripts\python.exe src\cli.py rapor
```

### Adim 3 - Soru sor

```powershell
# Tek soru
.\.venv\Scripts\python.exe src\cli.py sor "A makinesinde yag degisim araligi nedir?" --makine A

# Etkilesimli sohbet  (/m A ile filtre, /temizle, /q)
.\.venv\Scripts\python.exe src\cli.py sohbet
```

### Web arayuzu

```powershell
powershell -ExecutionPolicy Bypass -File D:\MakineRAG\baslat.ps1
# veya:  .\.venv\Scripts\python.exe server\api.py
```

Tarayicida <http://127.0.0.1:8000> acilir. Uc sekme vardir:

- **Sohbet** — Turkce soru, akan cevap, altinda tiklanabilir kaynak kartlari.
  Cevaptaki `[1]` atifina tiklayinca ilgili kaynak karti isaretlenir; karta tiklayinca
  belge cekmecesi acilir ve PDF dogru sayfadan baslar.
- **Belgeler** — makine/tur filtresi, arama, siralanabilir tablo, belge detay cekmecesi
  (sayfa seridinde turuncu kareler OCR ile okunmus sayfalari gosterir).
- **Konu Haritasi** — uretilmis raporlar; buradan yeni rapor uretimi de baslatilabilir
  (arka planda calisir, durumu ekranda izlenir).

Sag ustteki dugme aydinlik/karanlik temayi degistirir, secim tarayicida saklanir.

Farkli bir yapilandirma profili ile calistirmak icin:

```powershell
$env:MAKINERAG_CONFIG = "D:\MakineRAG\config_test.yaml"
.\.venv\Scripts\python.exe server\api.py
```

---

## 4. Ayarlar (`config.yaml`)

| Alan | Aciklama |
|---|---|
| `ocr.diller` | `ron+eng`. Sadece Ingilizce belgeler icin `eng` daha hizli ve daha dogrudur. |
| `ocr.dpi` | 300 dengeli. Kucuk punto / kotu tarama icin 400. Her artis OCR suresini buyutur. |
| `ocr.metin_esigi` | Sayfada bu kadar karakterden az metin varsa OCR calisir. Zaten metin katmani olan PDF'ler boylece hizlica gecilir. |
| `ocr.isci_sayisi` | Paralel surec. 12700H icin 6-8 uygundur; RAM 16 GB oldugu icin 8'i asmayin. |
| `parcalama.strateji` | `yapisal` (varsayilan), `sabit` veya `anlamsal`. Bkz. bolum 5. |
| `parcalama.baglam_oneki` | `true`. Gomulen metnin basina Turkce belge/bolum basligi ekler. |
| `gomme.model` | Cok dilli olmali. `BAAI/bge-m3` (~2,2 GB) veya `Qwen/Qwen3-Embedding-0.6B` (~1,2 GB). Degistirirseniz indeksi bastan kurmak gerekir. |
| `gomme.cihaz` | `cuda`. bge-m3 ~2,5 GB VRAM ister. |
| `gomme.yari_hassasiyet` | `true` yaparsaniz model fp16 yuklenir, VRAM yariya iner. 8 GB'de LLM ile ayni anda calistirmak icin. |
| `gomme.onek_sorgu` / `onek_belge` | Elle vermeyin; model ailesine gore otomatik secilir. E5 gibi modeller onek olmadan sessizce kotu calisir, bunu `src/embed.py` halleder. |
| `llm.model` | `llama3.1:8b` (varsayilan, bu makinede dogrulandi). **`gemma4:12b` ve `gemma4:e4b` bu Ollama 0.32.5 / surucu 595.95 birlesiminde `llama-server terminated ... CUDA error` ile cokuyor** -- baglam boyutundan bagimsiz. Model degistirirken once tek soru ile test edin. |
| `llm.baglam` | 8192. Dusurmeyin; baglam kirpilirsa cevap kalitesi duser. |
| `arama.final_k` | LLM'e verilen parca sayisi. 8 dengeli; 12'ye cikarsaniz `llm.baglam`'i 12288 yapin. |

---

## 5. Parcalama stratejisi

`config.yaml > parcalama.strateji` uc deger alir:

| Strateji | Nasil boler | Ne zaman |
|---|---|---|
| `yapisal` | Bolum basliklarinda (`5.2 Lubrication`, `FC-902`, buyuk harfli satirlar) boler; tablo ve liste bloklarini bolmez | **Varsayilan.** Teknik kilavuzlar zaten numarali bolumlerden olusur; hata kodu ve yedek parca tablolari bolununce anlamini kaybeder |
| `sabit` | Sabit boyut, cumle/paragraf sinirinda keser | En hizli ve en basit; yapisi olmayan duz metinler |
| `anlamsal` | Ardisik paragraflari gomup kosinus mesafesinin sicradigi yerden boler | Deneysel. Her paragrafi ayrica gommek gerekir, indeks suresine saatler ekler |

**`anlamsal` neden varsayilan degil:** belgeler taranmis oldugu icin OCR metninde
cumle ve paragraf sinirlari guvenilmez -- yontem tam olarak buna dayanir. Ayrica
tablo satirlari birbirinden "anlamsal olarak uzak" gorundugu icin tablolar
parcalanir. Yine de olcebilmeniz icin dahil edildi.

### Baglam oneki

`parcalama.baglam_oneki: true` iken her parcanin **gomulen** metninin basina su
satir eklenir:

```
[Belge: MK-A Hidrolik Pres Bakim Kilavuzu | Makine: A | Tur: bakim talimati | Bolum: 2. LUBRICATION]
```

Kullaniciya ve LLM'e gosterilen govde degismez; yalnizca vektor ve BM25 indeksleri
bu zenginlestirilmis metni gorur. Turkce baslik boylece gomulen metnin icine girdigi
icin Turkce sorgu ile Ingilizce/Romence belge eslesmesi belirgin kolaylasir. Bu,
parcalayici secmekten genellikle daha cok kazandirir.

### Stratejileri karsilastirma

Ayni olcum koşumu parcalayicilari da karsilastirir:

```powershell
.\.venv\Scripts\python.exe scripts\gomme_karsilastir.py --ornek 40 `
    --parcalayici sabit yapisal anlamsal --modeller BAAI/bge-m3
```

Cikti satirlari `model @ parcalayici` seklinde etiketlenir, parca sayisi ve
ortalama parca uzunlugu da raporlanir.

> Parcalama stratejisini degistirmek de indeksi bastan kurmayi gerektirir
> (`index --yeniden`), tipki gomme modeli gibi.

---

## 6. Gomme modeli secimi

Siralama tablolarindaki farklar, sizin belgelerinizde OCR gurultusu ve alan jargonu
yaninda kucuk kalir. Dogru yaklasim kendi belgelerinizde olcmektir:

```powershell
# 1) Degerlendirme sorularini uret (LLM belgelerden Turkce soru yazar,
#    dogru cevap = sorunun cikarildigi belge)
.\.venv\Scripts\python.exe scripts\gomme_karsilastir.py --ornek 40 --soru-uret 25

# 2) data\degerlendirme\sorular.json dosyasini acin.
#    Uretilen sorulari duzeltin ve GERCEKTEN soracaginiz sorulari ekleyin --
#    olcumun degerini asil bu belirler.

# 3) Modelleri karsilastirin
.\.venv\Scripts\python.exe scripts\gomme_karsilastir.py --ornek 40 `
    --modeller BAAI/bge-m3 Qwen/Qwen3-Embedding-0.6B
```

Cikti, her model icin dogru belgeyi ilk sirada / ilk 3'te / ilk 5'te getirme oranini
ve MRR@10 degerini, ayrica kodlama hizini ve VRAM kullanimini verir. Referans olarak
cevirisiz BM25 satiri da eklenir -- dense modelin gercekten ne kazandirdigini gorursunuz.

Betik gercek Chroma indeksine dokunmaz, her sey bellekte hesaplanir; modelleri sirayla
yukleyip bosaltir, 8 GB VRAM yeter. Olcum sirasinda `ollama stop gemma4:12b` demek
GPU'yu rahatlatir.

**Onemli:** gomme modeli indeksin ayrilmaz parcasidir. Sonradan degistirmek
`index --yeniden` demektir (1000 PDF'te 20-45 dk), bu yuzden karari buyuk kosudan
once verin. Iki model arasindaki fark %5'in altindaysa bu orneklem buyuklugunde
gurultudur; kucuk ve hizli olani secin.

---

## 7. Beklenen sureler (bu makinede)

| Adim | 1000 PDF icin tahmin |
|---|---|
| OCR (8 isci, 300 DPI, ort. 15 sayfa) | 4 - 9 saat |
| Meta cikarimi (llama3.1:8b) | 1 - 2 saat |
| Gomme + indeks (bge-m3, GPU) | 20 - 45 dk |
| Konu haritasi (makine basina) | 20 - 60 dk |
| Soru cevaplama | 5 - 20 sn |

Daha buyuk bir modele gecmek isterseniz once `ollama run <model> "merhaba"` ile tek soru
deneyin; bu makinede gemma4 ailesi cokuyor (bkz. bolum 4).

---

## 8. Sik karsilasilan durumlar

**Cevap Ingilizce geliyor** -> `llm.sicaklik` degerini 0.1'de tutun. Kucuk modellerde
(3B ve alti) dil kaymasi olabilir; 8B ve uzeri kullanin.

**Makine "bilinmiyor" cikiyor** -> `config.yaml > makineler > takma_adlar` listesini genisletin,
sonra `python src\cli.py meta --yeniden`. Hangi adlarin gectigini gormek icin manifest'teki
`makine_adaylari` alanina bakin.

**OCR metni bozuk** -> `ocr.dpi` degerini 400 yapin ve o belgeleri `--yeniden` ile tekrar isleyin.
Cok kotu taramalar icin Tesseract yerine `deepseek-ocr:3b` (Ollama'da yuklu) alternatiftir.

**GPU bellegi yetmiyor** -> `gomme.batch` degerini 4'e dusurun, ya da indeksleme sirasinda
Ollama'yi durdurun (`ollama stop llama3.1:8b`) - ikisi ayni anda 8 GB VRAM'i zorlar.

**GPU bellegi yetmiyor (devam)** -> `gomme.yari_hassasiyet: true` yapin; model fp16 yuklenir,
VRAM yariya iner ve kalite farki bu is icin ihmal edilebilir.

**Belge eklendi** -> Yeni PDF'leri `data\pdf` icine atin ve `python src\cli.py tumu` calistirin;
sadece yeni dosyalar islenir.

---

## 9. Kurumsal ag: sertifika ve indirme sorunlari

Kurumsal aglar HTTPS trafigini kesip kendi kok sertifikalariyla yeniden imzalayabilir.
Python bu kok sertifikayi tanimadigi icin pip ve HuggingFace indirmeleri soyle patlar:

```
SSLError: [SSL: CERTIFICATE_VERIFY_FAILED] self-signed certificate in certificate chain
```

Cozum, Windows sertifika deposunu certifi paketiyle birlestirmektir:

```powershell
powershell -ExecutionPolicy Bypass -File D:\MakineRAG\scripts\sertifika_olustur.ps1
```

Bu, `certs\ca-bundle.pem` dosyasini uretir. `src/sertifika.py` bu dosyayi otomatik
bulup `SSL_CERT_FILE`, `REQUESTS_CA_BUNDLE` ve `PIP_CERT` degiskenlerine yerlestirir --
`config.yukle()` her calistigi anda devreye girer, ek bir sey yapmaniz gerekmez.
Normal aglarda dosya olusmaz ve hicbir davranis degismez.

`certs/` dizini `.gitignore` disindadir; sertifika paketi makineye ozeldir, paylasmayin.

**"upgrade torch to at least v2.6" hatasi** -> Bazi depolar (`BAAI/bge-m3`) Hub'da yalnizca
`pytorch_model.bin` ile yayinlanir ve transformers 5.x bunu torch 2.6'nin altinda
yuklemez. 2,5 GB'lik torch yukseltmesi yerine agirligi bir kez cevirin:

```powershell
.\.venv\Scripts\python.exe scripts\safetensors_cevir.py BAAI/bge-m3
```

Cevrimden sonra `src/embed.py` modeli yerel safetensors surumunden yukler. Isterseniz
snapshot dizinindeki `pytorch_model.bin` dosyasini silip 2,2 GB disk kazanabilirsiniz.
