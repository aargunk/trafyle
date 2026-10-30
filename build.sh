#!/bin/bash
# Trafyle.app paketini oluşturur. Kullanım:  ./build.sh
set -e
cd "$(dirname "$0")"

PY=${PY:-python3.12}
if ! "$PY" -c "import tkinter" 2>/dev/null; then
    echo "❌ $PY içinde tkinter yok. Kurmak için: python.org'dan Python 3.12 kurun"
    exit 1
fi

if [ ! -d .venv ]; then
    echo "🔧 Sanal ortam oluşturuluyor…"
    $PY -m venv .venv
fi
source .venv/bin/activate
if [ -z "${SKIP_INSTALL:-}" ]; then
    pip install -q --upgrade pip
    pip install -q -r requirements.txt pyinstaller
fi
export TRAFYLE_RELEASE_BUILD=1

# Paketleme iCloud'un eşitlemediği bir klasörde yapılır: iCloud (Masaüstü/Belgeler) dosyalara ek bilgi
# (xattr) iliştirir ve macOS imzalama aracı bunları kabul etmez.
SRC="$(pwd)"
OUTDIR="${TRAFYLE_BUILD_DIR:-$HOME/Library/Caches/TrafyleBuild}"
APPOUT="$OUTDIR/dist/Trafyle.app"

echo "📦 Paketleniyor (birkaç dakika sürebilir)…"
rm -rf "$OUTDIR" build dist
mkdir -p "$OUTDIR"
pyinstaller --noconfirm --windowed \
    --distpath "$OUTDIR/dist" --workpath "$OUTDIR/build" --specpath "$OUTDIR" \
    --name "Trafyle" \
    --osx-bundle-identifier "com.trafyle.app" \
    --collect-all faster_whisper \
    --collect-all ctranslate2 \
    --collect-all av \
    --collect-binaries onnxruntime \
    --collect-all tkinterdnd2 \
    --collect-all _sounddevice_data \
    --collect-all sherpa_onnx \
    --collect-data certifi \
    --collect-data pdfminer \
    --collect-all yt_dlp \
    --collect-all yt_dlp_ejs \
    --collect-all deno \
    --add-binary "$(python -c 'import deno; print(deno.find_deno_bin())'):bin" \
    --hidden-import Vision --hidden-import Quartz --hidden-import objc \
    --hidden-import sounddevice \
    --collect-submodules keyring \
    --paths "$SRC" \
    --icon "$SRC/assets/AppIcon.icns" \
    --add-data "$SRC/assets:assets" \
    "$SRC/app.py"

echo ""
# Info.plist: mikrofon izni açıklaması (yoksa macOS mikrofonu sormadan engeller) ve sürüm
PLIST="$APPOUT/Contents/Info.plist"
VER=$(python -c "import re;print(re.search(r'APP_VERSION = \"([^\"]+)\"', open('app.py').read()).group(1))")
plutil -replace NSMicrophoneUsageDescription -string "Trafyle, mikrofondan ses kaydı yapıp yazıya dökmek için mikrofonunuzu kullanır. Kayıtlar yalnızca bilgisayarınızda saklanır." "$PLIST"
plutil -replace CFBundleShortVersionString -string "$VER" "$PLIST"
plutil -replace CFBundleVersion -string "$VER" "$PLIST"
plutil -replace CFBundleDisplayName -string "Trafyle" "$PLIST"
plutil -replace NSHighResolutionCapable -bool true "$PLIST"
# Info.plist değiştiği için uygulamayı yeniden imzala (yerel, ücretsiz "ad-hoc" imza).
# Apple Developer kimliği olmadan yerel imza; kullanıcı ilk açılışta Gizlilik ve Güvenlik'ten onaylar.
xattr -cr "$APPOUT"
codesign --force --deep --sign - "$APPOUT"
codesign --verify --deep "$APPOUT" && echo "İmza doğrulandı."
echo "✅ Tamamlandı: $APPOUT ($(du -sh "$APPOUT" | cut -f1))"
echo "Modeller uygulamaya gömülü değildir; ilk kullanımda indirilir."
