#!/bin/bash
# Trafyle'ı gerçek bir Mac uygulaması olarak paketler ve Uygulamalar klasörünüze kurar.
# Mikrofon izni ve Dock'ta doğru ad/simge için gereklidir. Finder'da çift tıklayın.
# İlk seferde 5–10 dakika sürebilir. Daha önce Kur.command çalıştırılmış olmalı.
set -u
cd "$(dirname "$0")" || exit 1
bold() { printf "\033[1m%s\033[0m\n" "$1"; }
fail() { printf "\n\033[31m%s\033[0m\n" "$1"; echo; read -r -p "Kapatmak için Enter'a basın…" _; exit 1; }

clear
bold "Trafyle paketleniyor"
[ -x ".venv/bin/python" ] || fail "Önce Kur.command'a çift tıklayıp kurulumu yapın."
.venv/bin/python -m pip install -q pyinstaller || fail "PyInstaller yüklenemedi. İnternet bağlantınızı kontrol edin."
export TRAFYLE_BUILD_DIR="$HOME/Library/Caches/TrafyleBuild"
SKIP_INSTALL=1 PY=.venv/bin/python ./build.sh || fail "Paketleme başarısız oldu. Hata mesajını Claude'a iletebilirsiniz."

APP="$HOME/Applications/Trafyle.app"
bold "Kuruluyor: $APP"
osascript -e 'tell application "Trafyle" to quit' >/dev/null 2>&1
mkdir -p "$HOME/Applications"
rm -rf "$APP"
ditto --noextattr "$TRAFYLE_BUILD_DIR/dist/Trafyle.app" "$APP" || fail "Uygulama kopyalanamadı."
codesign --verify --deep "$APP" >/dev/null 2>&1 || codesign --force --deep --sign - "$APP"
# Önceki (Python üzerinden açılan) sürümden kalmış olabilecek mikrofon kararını sıfırla
tccutil reset Microphone com.trafyle.app >/dev/null 2>&1
touch "$APP"
echo
bold "Hazır."
rm -rf "$TRAFYLE_BUILD_DIR"   # geçici paketleme dosyalarını temizle
echo "Trafyle artık gerçek bir uygulama. İlk kayıtta Mac mikrofon izni soracak: “İzin ver”i seçin."
echo "Dock'taki Trafyle simgesini bir kez kaldırıp yeniden eklemeniz gerekebilir."
open "$APP"
read -r -p "Bu pencereyi kapatmak için Enter'a basın…" _
