@echo off
rem Trafyle Windows paketi: dist\Trafyle\Trafyle.exe ve (Inno Setup kuruluysa) kurulum dosyasi uretir.
rem Kullanim: once Kur.bat ile kurulum yapin, sonra bu dosyaya cift tiklayin.
cd /d "%~dp0\.."
set PY=.venv\Scripts\python.exe
if not exist %PY% (
  echo Once Kur.bat ile kurulumu yapin.
  pause
  exit /b 1
)
%PY% -m pip install -q pyinstaller || goto :err
for /f "delims=" %%i in ('%PY% -c "import deno; print(deno.find_deno_bin())"') do set DENO=%%i
rmdir /s /q build dist 2>nul
%PY% -m PyInstaller --noconfirm --windowed --name Trafyle ^
  --icon assets\AppIcon.ico ^
  --add-data "assets;assets" ^
  --add-binary "%DENO%;bin" ^
  --collect-all faster_whisper --collect-all ctranslate2 --collect-all av ^
  --collect-binaries onnxruntime --collect-all tkinterdnd2 --collect-all _sounddevice_data ^
  --collect-all sherpa_onnx --collect-data certifi --collect-data pdfminer ^
  --collect-all yt_dlp --collect-all yt_dlp_ejs --collect-all deno ^
  --collect-all winrt --collect-all pypdfium2 --collect-all pypdfium2_raw --collect-all pillow_heif ^
  --hidden-import sounddevice --hidden-import winplat --collect-submodules keyring ^
  app.py || goto :err
echo.
echo Program hazir: dist\Trafyle\Trafyle.exe
set ISCC="%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"
if exist %ISCC% (
  %ISCC% windows\Trafyle.iss || goto :err
  echo Kurulum dosyasi hazir: dist\Trafyle-Kurulum.exe
) else (
  echo Kurulum dosyasi icin Inno Setup 6 kurun: https://jrsoftware.org/isdl.php
  if defined CI goto :err
)
pause
exit /b 0
:err
echo Paketleme basarisiz oldu.
pause
exit /b 1
