"""Windows'a özgü yardımcılar: Windows'un yerleşik metin tanıması (OCR) ve konuşma sesleri.

İkisi de Windows Runtime (WinRT) üzerinden, pywinrt paketleriyle kullanılır; internet gerekmez.
Bu dosya yalnızca Windows'ta içe aktarılır.
"""
from __future__ import annotations

import asyncio
import ctypes
import io
import os
import sys
import wave
from typing import Optional

import numpy as np

IS_WINDOWS = os.name == "nt"


def _ro_init() -> None:
    """Çalışan iş parçacığında Windows Runtime'ı başlatır (zaten başlatıldıysa zararsız)."""
    if IS_WINDOWS:
        try:
            from winrt.runtime import MTA, init_apartment
            init_apartment(MTA)
        except Exception:  # noqa: BLE001  (zaten başlatılmışsa hata verir; sorun değil)
            try:
                ctypes.windll.combase.RoInitialize(1)  # RO_INIT_MULTITHREADED
            except Exception:  # noqa: BLE001
                pass


def _run(coro):
    _ro_init()
    return asyncio.run(coro)


def _static(cls, name: str):
    """pywinrt sürümleri arasında statik özellik farkı: Cls.prop ya da Cls.get_prop()."""
    if hasattr(cls, name):
        v = getattr(cls, name)
        return v() if callable(v) and not hasattr(v, "__iter__") else v
    return getattr(cls, "get_" + name)()


# ------------------------------------------------------------------ OCR

def ocr_available() -> bool:
    if not IS_WINDOWS:
        return False
    try:
        from winrt.windows.media.ocr import OcrEngine  # noqa: F401
        from winrt.windows.graphics.imaging import BitmapDecoder  # noqa: F401
        from winrt.windows.storage import StorageFile  # noqa: F401
        return True
    except Exception:  # noqa: BLE001
        return False


def _ocr_engine():
    from winrt.windows.globalization import Language
    from winrt.windows.media.ocr import OcrEngine

    for tag in ("tr-TR", "tr"):
        try:
            if OcrEngine.is_language_supported(Language(tag)):
                eng = OcrEngine.try_create_from_language(Language(tag))
                if eng is not None:
                    return eng, True
        except Exception:  # noqa: BLE001
            pass
    eng = OcrEngine.try_create_from_user_profile_languages()
    if eng is None:
        raise RuntimeError("Windows metin tanıma dili bulunamadı. " + OCR_HOWTO)
    return eng, False


OCR_HOWTO = ("Türkçe metin tanıma için: Ayarlar › Zaman ve dil › Dil ve bölge › Türkçe'yi ekleyin "
             "(ya da Türkçe'nin yanındaki ⋯ › Dil seçenekleri › “Optik karakter tanıma”yı yükleyin).")


def max_image_dimension() -> int:
    try:
        from winrt.windows.media.ocr import OcrEngine
        return int(_static(OcrEngine, "max_image_dimension"))
    except Exception:  # noqa: BLE001
        return 10000


def ocr_png(path: str) -> tuple[list[tuple[str, float, float, float]], bool]:
    """PNG dosyasındaki satırları okur → ([(metin, üst, alt, sol) 0..1], türkçe_mi)."""

    async def go():
        from winrt.windows.graphics.imaging import BitmapAlphaMode, BitmapDecoder, BitmapPixelFormat, SoftwareBitmap
        from winrt.windows.storage import FileAccessMode, StorageFile

        f = await StorageFile.get_file_from_path_async(os.path.abspath(path))
        stream = await f.open_async(FileAccessMode.READ)
        decoder = await BitmapDecoder.create_async(stream)
        bmp = await decoder.get_software_bitmap_async()
        try:
            bmp = SoftwareBitmap.convert_with_alpha(bmp, BitmapPixelFormat.BGRA8, BitmapAlphaMode.PREMULTIPLIED)
        except Exception:  # noqa: BLE001
            pass
        eng, turkish = _ocr_engine()
        res = await eng.recognize_async(bmp)
        h = float(bmp.pixel_height) or 1.0
        w = float(bmp.pixel_width) or 1.0
        lines = []
        for line in res.lines:
            text = str(line.text).strip()
            if not text:
                continue
            rects = [wd.bounding_rect for wd in line.words]
            if rects:
                top = min(r.y for r in rects) / h
                bottom = max(r.y + r.height for r in rects) / h
                left = min(r.x for r in rects) / w
            else:
                top = bottom = left = 0.0
            lines.append((text, top, bottom, left))
        return lines, turkish

    return _run(go())


# ------------------------------------------------------------------ konuşma sesleri

SPEECH_HOWTO = ("Windows'a Türkçe ses eklemek için:\n\n"
                "1. Ayarlar › Zaman ve dil › Konuşma'yı açın.\n"
                "2. “Sesleri yönet” bölümünde “Ses ekle”ye tıklayın.\n"
                "3. Türkçe'yi seçip yükleyin (Tolga, erkek sesi).\n"
                "4. Yükleme bitince bu ekrandaki Ses listesini açın; ses listede görünür.\n\n"
                "Windows sesleri internete bağlanmadan, bilgisayarınızda çalışır.")


def speech_voices() -> list[tuple[str, str, str]]:
    """Yüklü Türkçe Windows sesleri: [(ad, dil, cinsiyet)]."""
    if not IS_WINDOWS:
        return []
    try:
        _ro_init()
        from winrt.windows.media.speechsynthesis import SpeechSynthesizer

        out = []
        for v in _static(SpeechSynthesizer, "all_voices"):
            lang = str(v.language)
            if not lang.lower().startswith("tr"):
                continue
            gender = "kadın" if int(v.gender) == 1 else "erkek"
            out.append((str(v.display_name), lang, gender))
        return out
    except Exception:  # noqa: BLE001
        return []


def speak_to_wav(name: str, text: str, speed: float) -> tuple[np.ndarray, int]:
    """Windows sesiyle metni seslendirir → (float32 mono, örnekleme hızı)."""

    async def go():
        from winrt.windows.media.speechsynthesis import SpeechSynthesizer
        from winrt.windows.storage.streams import DataReader

        synth = SpeechSynthesizer()
        for v in _static(SpeechSynthesizer, "all_voices"):
            if str(v.display_name) == name:
                synth.voice = v
                break
        try:
            synth.options.speaking_rate = max(0.5, min(3.0, float(speed)))
        except Exception:  # noqa: BLE001
            pass
        stream = await synth.synthesize_text_to_stream_async(text)
        size = int(stream.size)
        reader = DataReader(stream.get_input_stream_at(0))
        await reader.load_async(size)
        try:
            data = bytes(reader.read_buffer(size))
        except Exception:  # noqa: BLE001
            arr = bytearray(size)
            reader.read_bytes(arr)
            data = bytes(arr)
        return data

    data = _run(go())
    with wave.open(io.BytesIO(data), "rb") as w:
        sr, ch, width = w.getframerate(), w.getnchannels(), w.getsampwidth()
        raw = w.readframes(w.getnframes())
    if width != 2:
        raise RuntimeError("Windows sesi beklenmeyen biçimde döndü.")
    x = np.frombuffer(raw, dtype="<i2").astype(np.float32) / 32768.0
    if ch > 1:
        x = x.reshape(-1, ch).mean(axis=1)
    return x, sr


# ------------------------------------------------------------------ ekran ölçeği

def enable_dpi_awareness() -> None:
    """Yüksek çözünürlüklü ekranlarda bulanık görünmeyi önler; görev çubuğunda Python yerine
    Trafyle simgesinin görünmesini sağlar."""
    if not IS_WINDOWS:
        return
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("Trafyle.App")
    except Exception:  # noqa: BLE001
        pass
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:  # noqa: BLE001
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:  # noqa: BLE001
            pass


def log_path() -> Optional[str]:
    base = os.environ.get("LOCALAPPDATA")
    if not base:
        return None
    d = os.path.join(base, "Trafyle")
    os.makedirs(d, exist_ok=True)
    return os.path.join(d, "Trafyle.log")


def redirect_output_if_windowless() -> None:
    """pythonw.exe ile açılınca konsol yoktur; hataları bir günlük dosyasına yazar."""
    if sys.stderr is None or sys.stdout is None:
        p = log_path()
        if p:
            f = open(p, "a", encoding="utf-8", buffering=1)  # noqa: SIM115
            sys.stdout = sys.stdout or f
            sys.stderr = sys.stderr or f


# ------------------------------------------------------------------ pencere / görev çubuğu simgesi

_ICON_HANDLES: list = []


def set_window_icon(tk_window, ico_path: str) -> bool:
    """Görev çubuğunda ve Alt+Tab'da Python yerine Trafyle simgesinin görünmesi için simgeyi
    doğrudan Windows'a (WM_SETICON) verir. Tk'nin iconbitmap'i bazı sistemlerde görev çubuğuna yansımaz."""
    if not IS_WINDOWS or not os.path.exists(ico_path):
        return False
    try:
        from ctypes import wintypes

        user32 = ctypes.windll.user32
        user32.LoadImageW.restype = wintypes.HANDLE
        user32.LoadImageW.argtypes = [wintypes.HINSTANCE, wintypes.LPCWSTR, wintypes.UINT,
                                      ctypes.c_int, ctypes.c_int, wintypes.UINT]
        user32.SendMessageW.restype = ctypes.c_ssize_t
        user32.SendMessageW.argtypes = [wintypes.HWND, wintypes.UINT, ctypes.c_size_t, ctypes.c_ssize_t]
        tk_window.update_idletasks()
        hwnd = int(tk_window.wm_frame(), 16)          # Tk'nin dış (çerçeve) penceresi
        if not hwnd:
            hwnd = user32.GetParent(tk_window.winfo_id())
        IMAGE_ICON, LR_LOADFROMFILE, WM_SETICON = 1, 0x10, 0x0080
        big = max(32, user32.GetSystemMetrics(11))     # SM_CXICON
        small = max(16, user32.GetSystemMetrics(49))   # SM_CXSMICON
        h_big = user32.LoadImageW(None, ico_path, IMAGE_ICON, big, big, LR_LOADFROMFILE)
        h_small = user32.LoadImageW(None, ico_path, IMAGE_ICON, small, small, LR_LOADFROMFILE)
        if h_big:
            user32.SendMessageW(hwnd, WM_SETICON, 1, h_big)    # ICON_BIG: görev çubuğu, Alt+Tab
        if h_small:
            user32.SendMessageW(hwnd, WM_SETICON, 0, h_small)  # ICON_SMALL: başlık çubuğu
        _ICON_HANDLES.extend([h_big, h_small])               # serbest bırakılmasın
        return bool(h_big)
    except Exception:  # noqa: BLE001
        return False


# ------------------------------------------------------------------ bilinen klasörler

_FOLDER_IDS = {
    "documents": "{FDD39AD0-238F-46AF-ADB4-6C85480369C7}",
    "downloads": "{374DE290-123F-4565-9164-39C4925E467B}",
}


def known_folder(name: str) -> Optional[str]:
    """Belgeler / İndirilenler klasörünün gerçek yolu (OneDrive'a taşınmış olsa bile)."""
    if not IS_WINDOWS or name not in _FOLDER_IDS:
        return None
    try:
        import uuid
        from ctypes import wintypes

        class GUID(ctypes.Structure):
            _fields_ = [("Data1", wintypes.DWORD), ("Data2", wintypes.WORD), ("Data3", wintypes.WORD),
                        ("Data4", ctypes.c_ubyte * 8)]

        u = uuid.UUID(_FOLDER_IDS[name])
        g = GUID(u.fields[0], u.fields[1], u.fields[2], (ctypes.c_ubyte * 8)(*u.bytes[8:]))
        path = ctypes.c_wchar_p()
        fn = ctypes.windll.shell32.SHGetKnownFolderPath
        fn.argtypes = [ctypes.POINTER(GUID), wintypes.DWORD, wintypes.HANDLE, ctypes.POINTER(ctypes.c_wchar_p)]
        if fn(ctypes.byref(g), 0, None, ctypes.byref(path)) != 0:
            return None
        result = path.value
        ctypes.windll.ole32.CoTaskMemFree(path)
        return result if result and os.path.isdir(result) else None
    except Exception:  # noqa: BLE001
        return None
