# Sürüm notları

## 3.4.1 — Lisans temizliği

- Piper sesleri (Fahrettin, Fettah) tamamen kaldırıldı: türetildikleri İngilizce sesin lisansı yalnızca araştırma
  amaçlı kullanıma izin veriyor. Seslendirme artık yalnızca Mac'in ve Windows'un kendi Türkçe seslerini kullanır.
- Piper sesleriyle üretilmiş örnek ses dosyası (ornek-diyalog.m4a) depodan kaldırıldı.
- Lisans listesine GPL lisanslı bileşenlerin (FFmpeg, x264, x265, espeak-ng) kaynak kodu bağlantıları eklendi.
- Konuşmacı ayırma modeli TitaNet'in lisansı teyit edildi (Apache-2.0) ve listede düzeltildi.

## 3.4.0 — Açık kaynak

- Trafyle artık ücretsiz ve açık kaynaklı (GNU GPL-3.0).
- Yeni sürüm bildirimi: yeni bir sürüm yayınlandığında sol altta indirme bağlantısı çıkar (Hakkında'dan kapatılabilir).
- Hazır kurulum dosyaları GitHub Releases'te: Windows için Trafyle-Kurulum.exe, Mac (Apple Silicon) için Trafyle-mac.zip.
- Tanıtım sayfası, gizlilik notu ve kullanım koşulları.

## 3.3.1 — Windows uyarlaması

Kayıt, telaffuz düzeltmesi ve özetleme Windows'ta da çalışır. Güncellemek için Windows'ta **Kur.bat**'a bir kez
çift tıklayın (yeni bileşenler yüklenir; modeller korunur).
- **Mikrofondan kaydet** (Ctrl+R): Windows her mikrofonu birkaç kez listeler; artık her mikrofon bir kez görünür.
  Ses gelmiyorsa: Ayarlar › Gizlilik ve güvenlik › Mikrofon › "Masaüstü uygulamalarının mikrofonunuza erişmesine
  izin ver" açık olmalı. Windows'ta Mac'teki gibi ayrıca paketlemek gerekmez.
- Kayıtlar Belgeler › Trafyle Kayıtları'na, bağlantıdan alınan sesler İndirilenler'e kaydedilir
  (Belgeler/İndirilenler OneDrive'a taşınmışsa oraya).
- **Özetle:** API anahtarı Windows Kimlik Bilgileri Yöneticisi'nde saklanır.
- **Telaffuz:** Telaffuz sözlüğü ve "Okunuşu göster" Windows'un Türkçe sesi (Tolga) ile de çalışır.

## 3.3 — Özetle

- Yeni **Özetle** sekmesi: dökümü, Word/PDF/metin dosyasını ya da yapıştırılan metni yapay zekâyla özetler.
  Özet türleri: kısa özet, ana noktalar, toplantı notu (kararlar ve yapılacaklar), başlıklı ayrıntılı özet.
  Dil seçilebilir; "Ek istek" kutusuna ("öğrenciler için sade bir dille" gibi) not yazılabilir.
- **Kendi hesabınızla:** Claude (Anthropic), ChatGPT (OpenAI) ya da Gemini (Google). "Yapay zekâ ayarları…"ndan
  hizmeti seçip API anahtarınızı girin ("Anahtar sayfasını aç" bağlantısı ve adımlar pencerede). Anahtar Mac'te
  Anahtar Zinciri'nde, Windows'ta Kimlik Bilgileri Yöneticisi'nde saklanır. "Bağlantıyı dene" anahtarı doğrular
  ve hesabınızdaki modelleri listeler.
- **Açık uyarı:** Özetlemede metin seçilen hizmete gönderilir. İlk seferde onay penceresi çıkar ("bir daha sorma"
  seçilmedikçe her seferinde); ekranda kalıcı uyarı vardır. Trafyle'ın diğer tüm işlemleri bilgisayarda kalır.
- Sesten metne ekranında ve Dönüştür'de (PDF/OCR çıktıları) **Özetle** düğmesi. Özet düzenlenebilir;
  Word, PDF, metin ya da Markdown olarak kaydedilebilir, kopyalanabilir, seslendirilebilir.
- Çok uzun metinler parça parça özetlenip birleştirilir.

## 3.2 — daha doğru telaffuz

- Seslendirmeden önce metin Türkçe okunuşa çevrilir (tüm seslerde): ekli sayılar (2023'te → iki bin yirmi üçte),
  sıra sayıları (3. → üçüncü), tarih ve saat, yüzde, para birimleri, ölçü birimleri, ondalıklar, telefon numaraları,
  Roma rakamları (II. → ikinci), unvan ve kısaltmalar (Prof. Dr., vb., bkz.), büyük harfli kısaltmalar
  (TBMM → te be me me; NATO, YÖK gibi okunabilenler kelime olarak) ve yaygın yabancı kelimeler (WhatsApp → vatsap).
- **Telaffuz sözlüğü:** Metinden sese › "Telaffuz sözlüğü…" — yanlış okunan kelimeyi "yazılış = okunuş" biçiminde ekleyin.
- **Okunuşu göster:** metnin seslendirmede tam olarak nasıl okunacağını gösterir; hatalı kelimeyi buradan bulup sözlüğe ekleyin.
- Denemek için klasördeki `ornek-telaffuz.txt` dosyasını "Dosyadan aç…" ile açın.

## 3.1

- **Mikrofondan kaydet:** Soldaki "Mikrofondan kaydet" düğmesi (ya da Cmd+R / Ctrl+R). Mikrofon seçilir, süre ve ses
  seviyesi görünür; Boşluk tuşuyla duraklatılıp sürdürülebilir. "Bitir"e basınca kayıt M4A olarak
  `Belgeler/Trafyle Kayıtları` klasörüne (değiştirilebilir) kaydedilir ve hemen yazıya dökülür.
- Kayıt sürerken diske yazılır; uygulama beklenmedik biçimde kapansa bile o ana kadarki kayıt kaybolmaz.
- Mikrofondan ses gelmiyorsa (ör. Mac'te izin verilmemişse) pencere bunu söyler ve izni nereden açacağınızı gösterir.
- **Mac'te mikrofon izni için Trafyle'ı gerçek uygulama olarak paketleyin:** klasördeki **Paketle.command**'a
  çift tıklayın (ilk seferde 5–10 dk). Kur.command'ın oluşturduğu simge Python'u çağırdığından Mac mikrofon
  iznini Python'a sorar ve sormadan reddeder; Paketle.command bunu düzeltir. İlk kayıtta "İzin ver"i seçin.

## 3.0

- **Yeni ad ve logo: Trafyle** (TRAnsform FILE). Eski SesMetin ayarları ve indirilmiş modeller ilk açılışta
  kendiliğinden yeni ada taşınır; yeniden indirme gerekmez. Kur.command eski SesMetin başlatıcısını kaldırır.
- **Hakkında** ekranı (sol alttaki "Hakkında" ya da Mac'te uygulama menüsü) ve **üçüncü taraf lisansları** listesi.
- **Satışa uygun lisans düzeni:**
  - DFKI sesi kaldırıldı (ticari kullanıma kapalı).
  - Fahrettin ve Fettah sesleri ticari kullanıma kapalı bir İngilizce sesten türetildiği için yalnızca
    kişisel (kaynak koddan) kurulumda görünür; satış paketinde Mac/Windows'un kendi Türkçe sesleri kullanılır.
  - Satış paketinde ses motoru GPL'li espeak-ng olmadan derlenir; yt-dlp'nin GPL'li isteğe bağlı parçası kurulmaz.
- Satış paketleri (`Trafyle-Kurulum.exe`, `Trafyle.app`) GitHub'da otomatik üretilebilir: `.github/workflows/build.yml`.

## 2.5 — Windows sürümü

Trafyle artık Windows 10 ve 11'de de çalışır; tüm özellikler aynıdır.

**Kurulum (Windows):** Klasördeki **Kur.bat** dosyasına çift tıklayın. Windows "bilgisayarınızı korudu" ya da
"güvenlik uyarısı" gösterirse "Ek bilgi › Yine de çalıştır"ı seçin. Kurulum:
- Python 3.12 yoksa otomatik kurmayı önerir (winget ile) ya da indirme sayfasını açar,
- gerekli kütüphaneleri yükler,
- Başlat menüsüne (isteğe bağlı olarak masaüstüne) Trafyle kısayolunu ekler.

Windows'ta farklı çalışan kısımlar:
- **Metin tanıma (OCR):** Windows'un yerleşik metin tanıması kullanılır. Türkçe harfler için Türkçe dil paketi gerekir
  (Ayarlar › Zaman ve dil › Dil ve bölge › Türkçe). Türkçe arayüzlü Windows'ta zaten yüklüdür.
- **Sistem sesi:** Windows'un Türkçe sesi (Tolga, erkek) kullanılır. Yüklü değilse "Türkçe ses ekle…" düğmesi adımları gösterir.
  Fahrettin ve Fettah sesleri her iki sistemde de aynıdır.
- **HEIC fotoğraflar:** pillow-heif ile açılır.
- Hata günlüğü: `%LOCALAPPDATA%\Trafyle\Trafyle.log`

**Tek dosyalık Windows kurulum programı (satış için):** `windows\build.bat` bir Windows bilgisayarda
`Trafyle-Kurulum.exe` üretir (Inno Setup 6 gerekir). Windows bilgisayarınız yoksa depo GitHub'a konduğunda
`.github/workflows/windows-build.yml` aynı dosyayı GitHub'ın Windows makinesinde otomatik üretir.

## 2.4

Üstte yeni **Dönüştür** sekmesi. Dört işlem var; hepsi bilgisayarda çalışır:

- **Taranmış belge → metin (OCR):** Fotoğraf (JPG, PNG, HEIC…) ya da taranmış PDF'teki yazıyı okur.
  Mac'in yerleşik metin tanımasını kullanır; Türkçe tanıma için güncel bir macOS gerekir.
- **PDF → metin / Word:** PDF'teki yazıyı paragraflarıyla .txt ya da .docx olarak çıkarır. Başlıklar Word'de başlık olur;
  sayfa düzeni (sütun, tablo, resim) taşınmaz. Yazısı olmayan taranmış sayfalar otomatik olarak OCR ile okunur.
- **Video → ses:** M4A, MP3 ya da WAV. Ses zaten AAC ise M4A'ya kayıpsız ve hızlıca kopyalanır.
- **Bağlantıdan ses:** Video → ses ekranında YouTube, Vimeo, X, Instagram vb. bir bağlantıyı yapıştırın (ya da tarayıcıdan
  sürükleyin). Video indirilmez, yalnızca ses alınır ve İndirilenler klasörüne kaydedilir. "Bitince metne çevir"
  işaretliyse ses kendiliğinden yazıya dökülür. Siteler sık değiştiği için bir bağlantı çalışmazsa
  "Bağlantı desteğini güncelle"ye basın. Yalnızca kullanma hakkınız olan içerikler için kullanın.
- **Görüntü biçimi:** HEIC → JPG, PNG ↔ JPG, istenen boyuta küçültme, JPG kalitesi.

Çıkan metni "Seslendir" ile Metinden sese ekranına, çıkan sesi "Metne çevir" ile yazıya dökme kuyruğuna gönderebilirsiniz.
PDF ya da fotoğrafı soldaki alana bırakırsanız uygulama kendiliğinden Dönüştür ekranına geçer.
Güncelleme için Kur.command'a yeniden çift tıklayın (yeni bileşenler yüklenir).

## 2.3

- **Mac'in Türkçe sistem sesleri:** Yelda (kadın) gibi Mac'te yüklü Türkçe sesler listede kendiliğinden görünür.
  İndirme gerektirmez ve bilgisayarda çalışır. Yüklü değilse "Yelda'yı ekle…" düğmesi adımları gösterir
  (Sistem Ayarları › Erişilebilirlik › Seslendirilen İçerik › Sistem sesi › Sesleri Yönet… › Türkçe).
- Sesler adlarıyla listelenir: Yelda · kadın, Fahrettin · erkek, Fettah · erkek, DFKI · erkek (kişisel).
  DFKI sesinin lisansı ticari kullanıma kapalıdır; satış sürümünde yer almayacak.
- Konuşmacılara varsayılan olarak birbirinden farklı sesler atanır.

## 2.2

- **Metinden sese:** üstteki "Metinden sese" sekmesinde metni yazın, yapıştırın ya da .txt/.docx dosyasından açın;
  "Sese çevir" ile bilgisayarda seslendirilir. Dinleyip M4A ya da WAV olarak kaydedebilirsiniz.
- Üç Türkçe ses, hız ayarı (0,7× – 1,5×). Her ses ilk kullanımda ~65 MB indirilir.
- "Ad: metin" biçimindeki konuşmalı metinlerde her konuşmacıya ayrı ses verilebilir.
- Döküm ekranındaki "Seslendir" düğmesi, metni konuşmacı adlarıyla birlikte seslendirme ekranına aktarır.
- Kısaltmalar (Prof. Dr., vb., %, TL…) okunmadan önce yazıya çevrilir.

## 2.1

- Yeni görünüm (Gece Mavisi): lacivert yan panel, dosya kartları, ses dalgalı çalar.
- Konuşmacı ayırma: "Konuşmacıları ayır" açıkken her satır bir konuşmacıya atanır
  (kişi sayısı otomatik ya da elle). İlk kullanımda yaklaşık 47 MB model indirilir.
- Konuşmacıları adlandırma ("Konuşmacılar" düğmesi) ve satıra sağ tıklayıp konuşmacı değiştirme.
- Yazı boyutu: A− / A+ düğmeleri ya da Cmd + / Cmd −.
- Dışa aktarılan Word, PDF, metin ve altyazılarda konuşmacı adları.

## 1.x sürümünden bu yana

**Düzeltilen hatalar**
- Kaydedilen dosyaya "Model yükleniyor…" gibi durum satırları artık karışmıyor.
- Hata olduğunda "Tamamlandı" yazmıyor; hata mesajı gösteriliyor.
- Model seçimi paketli uygulamada da çalışıyor (modeller ilk kullanımda indiriliyor).
- Video dosyaları (mp4, mov, mkv…) seçilebiliyor.
- Model her dosyada yeniden yüklenmiyor.

**Motor**
- openai-whisper yerine faster-whisper: daha hızlı, daha az bellek.
- PyTorch ve harici ffmpeg gerekmiyor; paket çok daha küçük.
- Yeni model: large-v3-turbo (en yüksek doğruluk).
- Sessiz bölümleri atlama ve tekrar eden cümle üretimine karşı ayar.
- Özel isim ve terim sözlüğü.

**Yeni özellikler**
- Birden çok dosya için kuyruk, sürükle-bırak.
- İlerleme yüzdesi, kalan süre, iptal.
- Düzeltme ekranı: satırın zamanına tıklayınca kayıt oradan çalar, çalan satır vurgulanır.
- Dışa aktarma: Word, PDF, düz metin, SRT, VTT; zaman damgalı ya da damgasız.
- Ayarlar hatırlanır.
