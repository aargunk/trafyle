#!/bin/bash
# Trafyle kurulumu — Finder'da çift tıklayın.
# 1) Python sanal ortamını kurar ve gerekli kütüphaneleri yükler
# 2) Kendi simgesiyle "Trafyle" uygulamasını oluşturur (Uygulamalar klasörünüze)
# Kurulumdan sonra Trafyle'ı Launchpad'den, Spotlight'tan ya da Dock'tan açabilirsiniz.

set -u
cd "$(dirname "$0")" || exit 1
DIR="$(pwd)"

bold() { printf "\033[1m%s\033[0m\n" "$1"; }
fail() { printf "\n\033[31m%s\033[0m\n" "$1"; echo; read -r -p "Kapatmak için Enter'a basın…" _; exit 1; }

clear
bold "Trafyle kurulumu"
echo "Klasör: $DIR"
echo

# --- 1. Python'u bul (3.12 önerilir; 3.11 ve 3.13 de çalışır)
PY=""
for cand in python3.12 python3.13 python3.11 \
    /Library/Frameworks/Python.framework/Versions/3.12/bin/python3.12 \
    /Library/Frameworks/Python.framework/Versions/3.13/bin/python3.13 \
    /Library/Frameworks/Python.framework/Versions/3.11/bin/python3.11; do
    if command -v "$cand" >/dev/null 2>&1; then PY="$(command -v "$cand")"; break; fi
done
if [ -z "$PY" ]; then
    echo "Python 3.12 bulunamadı. İndirme sayfası açılıyor;"
    echo "“macOS 64-bit universal2 installer”ı kurup bu dosyaya yeniden çift tıklayın."
    open "https://www.python.org/downloads/macos/"
    fail "Kurulum durdu: Python 3.12 gerekli."
fi
echo "Python: $PY ($("$PY" --version 2>&1))"
"$PY" -c "import tkinter" 2>/dev/null || fail "Bu Python'da arayüz kütüphanesi (tkinter) yok. python.org'daki yükleyiciyi kullanın."

# --- 2. Sanal ortam ve kütüphaneler
if [ ! -x ".venv/bin/python" ]; then
    bold "Sanal ortam oluşturuluyor…"
    "$PY" -m venv .venv || fail "Sanal ortam oluşturulamadı."
fi
bold "Kütüphaneler yükleniyor (ilk seferde birkaç dakika sürebilir)…"
.venv/bin/python -m pip install --upgrade pip -q || fail "pip güncellenemedi. İnternet bağlantınızı kontrol edin."
.venv/bin/python -m pip install -r requirements.txt || fail "Kütüphaneler yüklenemedi. Hata mesajını Claude'a iletebilirsiniz."
# Bağlantıdan ses alma bileşeni siteler değiştikçe güncellenmeli: her kurulumda en yeni sürüm
.venv/bin/python -m pip install -U -q yt-dlp yt-dlp-ejs deno || echo "Uyarı: bağlantı desteği güncellenemedi; uygulama içinden yeniden deneyebilirsiniz."

# --- 3. Uygulama simgesi (Trafyle.app)
APPS="$HOME/Applications"
APP="$APPS/Trafyle.app"
bold "Uygulama oluşturuluyor: $APP"
# Eski adla (SesMetin) oluşturulmuş başlatıcıyı kaldır; ayarlar ve modeller ilk açılışta yeni ada taşınır
OLD_DOCK=0
if [ -d "$APPS/SesMetin.app" ]; then
    rm -rf "$APPS/SesMetin.app"
    defaults read com.apple.dock persistent-apps 2>/dev/null | grep -q "SesMetin.app" && OLD_DOCK=1
fi
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources" || fail "Uygulama klasörü oluşturulamadı."
cp "assets/AppIcon.icns" "$APP/Contents/Resources/AppIcon.icns"

cat > "$APP/Contents/Info.plist" <<'PLIST'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>CFBundleName</key><string>Trafyle</string>
    <key>CFBundleDisplayName</key><string>Trafyle</string>
    <key>CFBundleIdentifier</key><string>com.trafyle.app</string>
    <key>CFBundleVersion</key><string>3.4.0</string>
    <key>CFBundleShortVersionString</key><string>3.4.0</string>
    <key>CFBundlePackageType</key><string>APPL</string>
    <key>CFBundleExecutable</key><string>Trafyle</string>
    <key>CFBundleIconFile</key><string>AppIcon</string>
    <key>LSMinimumSystemVersion</key><string>11.0</string>
    <key>NSHighResolutionCapable</key><true/>
    <key>NSMicrophoneUsageDescription</key><string>Trafyle, mikrofondan ses kaydı yapıp yazıya dökmek için mikrofonunuzu kullanır. Kayıtlar yalnızca bilgisayarınızda saklanır.</string>
</dict>
</plist>
PLIST

# Başlatıcı: kurulum klasörünün yolu içine yazılır
{
    echo '#!/bin/bash'
    printf 'DIR=%q\n' "$DIR"
    cat <<'RUN'
if [ ! -f "$DIR/app.py" ] || [ ! -x "$DIR/.venv/bin/python" ]; then
    osascript -e 'display alert "Trafyle açılamadı" message "Program dosyaları taşınmış ya da silinmiş görünüyor. Trafyle klasöründeki Kur.command dosyasına yeniden çift tıklayın." as critical'
    exit 1
fi
cd "$DIR" || exit 1
exec "$DIR/.venv/bin/python" "$DIR/app.py" >>"$HOME/Library/Logs/Trafyle.log" 2>&1
RUN
} > "$APP/Contents/MacOS/Trafyle"
chmod +x "$APP/Contents/MacOS/Trafyle"
mkdir -p "$HOME/Library/Logs"
touch "$APP"   # Finder'ın simgeyi yenilemesi için

# --- 4. İsteğe bağlı: Dock'a ekle
echo
if [ "$OLD_DOCK" = "1" ]; then
    echo "Not: Dock'taki eski SesMetin simgesi artık çalışmaz; simgeyi Dock'tan dışarı sürükleyerek kaldırabilirsiniz."
fi
read -r -p "Trafyle Dock'a eklensin mi? (e/h) " ans
if [ "${ans:-h}" = "e" ] || [ "${ans:-h}" = "E" ]; then
    if ! defaults read com.apple.dock persistent-apps 2>/dev/null | grep -q "Trafyle.app"; then
        defaults write com.apple.dock persistent-apps -array-add \
            "<dict><key>tile-data</key><dict><key>file-data</key><dict><key>_CFURLString</key><string>$APP</string><key>_CFURLStringType</key><integer>0</integer></dict></dict></dict>"
        killall Dock
    fi
fi

echo
bold "Kurulum tamamlandı."
echo "Trafyle'ı Launchpad'den, Spotlight'tan (Cmd+Boşluk → Trafyle) ya da Dock'tan açabilirsiniz."
echo "Not: Bu klasörü taşırsanız Kur.command'a yeniden çift tıklayın."
echo
open "$APP"
read -r -p "Bu pencereyi kapatmak için Enter'a basın…" _
