"""Mikrofondan ses kaydı.

Kayıt, sürerken diske (WAV) yazılır; böylece uzun toplantılar belleği doldurmaz ve uygulama beklenmedik
biçimde kapansa bile o ana kadarki kayıt kaybolmaz. Kayıt bitince M4A'ya çevrilir.
"""
from __future__ import annotations

import datetime as _dt
import math
import os
import queue
import sys
import threading
import wave
from typing import Callable, Optional

import numpy as np

try:
    import sounddevice as sd
    AVAILABLE = True
except Exception:  # noqa: BLE001
    sd = None
    AVAILABLE = False


def default_folder() -> str:
    docs = None
    if os.name == "nt":
        try:
            import winplat
            docs = winplat.known_folder("documents")
        except Exception:  # noqa: BLE001
            docs = None
    docs = docs or os.path.join(os.path.expanduser("~"), "Documents")
    if not os.path.isdir(docs):
        docs = os.path.expanduser("~")
    return os.path.join(docs, "Trafyle Kayıtları")


def input_devices() -> list[tuple[int, str]]:
    """Kayıt yapılabilen aygıtlar: [(sıra no, ad)]. Aynı adlı tekrarları atlar."""
    if not AVAILABLE:
        return []
    out, seen = [], set()
    try:
        devices = sd.query_devices()
        # Windows aynı mikrofonu her ses altyapısı (MME, DirectSound, WASAPI, WDM-KS) için ayrı listeler;
        # yalnızca varsayılan altyapıdakileri göster.
        api = None
        if os.name == "nt":
            try:
                di = default_input()
                api = devices[di]["hostapi"] if di is not None else sd.default.hostapi
            except Exception:  # noqa: BLE001
                api = None
        for i, d in enumerate(devices):
            if api is not None and d.get("hostapi") != api:
                continue
            if d.get("max_input_channels", 0) > 0:
                name = str(d.get("name", f"Aygıt {i}")).strip()
                if name not in seen:
                    seen.add(name)
                    out.append((i, name))
    except Exception:  # noqa: BLE001
        return []
    return out


def default_input() -> Optional[int]:
    if not AVAILABLE:
        return None
    try:
        dev = sd.default.device
        idx = dev[0] if isinstance(dev, (list, tuple)) else dev
        return int(idx) if idx is not None and int(idx) >= 0 else None
    except Exception:  # noqa: BLE001
        return None


def new_name(folder: str) -> str:
    stamp = _dt.datetime.now().strftime("%Y-%m-%d %H.%M")
    base = os.path.join(folder, f"Kayıt {stamp}")
    path, n = base, 2
    while os.path.exists(path + ".m4a") or os.path.exists(path + ".wav"):
        path = f"{base} ({n})"
        n += 1
    return path


class Recorder:
    """Mikrofon kaydı. Ses kartından gelen bloklar bir kuyruk üzerinden ayrı bir iş parçacığında diske yazılır."""

    def __init__(self, wav_path: str, device: Optional[int] = None):
        self.wav_path = wav_path
        self.device = device
        self.samplerate = 48000
        self.channels = 1
        self._q: "queue.Queue[Optional[np.ndarray]]" = queue.Queue()
        self._stream = None
        self._writer: Optional[threading.Thread] = None
        self._wave: Optional[wave.Wave_write] = None
        self.frames = 0                 # diske yazılan örnek sayısı
        self.paused = False
        self.level = 0.0                # 0..1 (anlık ses seviyesi, dB ölçeğinde)
        self.peak = 0.0
        self.max_abs = 0                # hiç ses gelmiyorsa 0 kalır (izin verilmemiş olabilir)
        self.error: Optional[str] = None
        self.overflows = 0

    # --- yaşam döngüsü
    def start(self) -> None:
        if not AVAILABLE:
            raise RuntimeError("Bu bilgisayarda ses kaydı kullanılamıyor.")
        info = sd.query_devices(self.device, "input")
        self.samplerate = int(info.get("default_samplerate") or 48000)
        os.makedirs(os.path.dirname(self.wav_path), exist_ok=True)
        last_err = None
        for ch in (1, min(2, int(info.get("max_input_channels") or 1))):
            try:
                self._stream = sd.InputStream(device=self.device, channels=ch, samplerate=self.samplerate,
                                              dtype="int16", callback=self._callback)
                self.channels = ch
                break
            except Exception as e:  # noqa: BLE001
                last_err = e
                self._stream = None
        if self._stream is None:
            raise RuntimeError(f"Mikrofon açılamadı: {last_err}")
        self._wave = wave.open(self.wav_path, "wb")
        self._wave.setnchannels(1)
        self._wave.setsampwidth(2)
        self._wave.setframerate(self.samplerate)
        self._writer = threading.Thread(target=self._write_loop, daemon=True)
        self._writer.start()
        self._stream.start()

    def _callback(self, indata, frames, _time, status):  # ses kartı iş parçacığı: kısa tut
        if status and getattr(status, "input_overflow", False):
            self.overflows += 1
        if self.paused:
            self.level *= 0.6
            return
        x = indata[:, 0] if indata.shape[1] == 1 else indata.mean(axis=1).astype(np.int16)
        self._q.put(x.copy())
        a = int(np.abs(x).max()) if len(x) else 0
        self.max_abs = max(self.max_abs, a)
        rms = float(np.sqrt(np.mean(np.square(x.astype(np.float32))))) if len(x) else 0.0
        db = 20 * math.log10(max(rms, 1.0) / 32768.0)
        lvl = max(0.0, min(1.0, (db + 60) / 60))
        self.level = max(lvl, self.level * 0.7)
        self.peak = max(lvl, self.peak * 0.97)

    def _write_loop(self):
        try:
            while True:
                block = self._q.get()
                if block is None:
                    break
                self._wave.writeframes(block.astype("<i2").tobytes())   # başlık her yazımda güncellenir
                self.frames += len(block)
        except Exception as e:  # noqa: BLE001
            self.error = f"Kayıt diske yazılamadı: {e}"

    def pause(self):
        self.paused = True

    def resume(self):
        self.paused = False

    @property
    def seconds(self) -> float:
        return self.frames / float(self.samplerate or 1)

    def stop(self) -> float:
        """Kaydı durdurur, dosyayı kapatır; süreyi (sn) döndürür."""
        try:
            if self._stream is not None:
                self._stream.stop()
                self._stream.close()
        except Exception:  # noqa: BLE001
            pass
        self._stream = None
        self._q.put(None)
        if self._writer is not None:
            self._writer.join(timeout=10)
        if self._wave is not None:
            try:
                self._wave.close()
            except Exception:  # noqa: BLE001
                pass
            self._wave = None
        return self.seconds

    def discard(self):
        self.stop()
        try:
            os.remove(self.wav_path)
        except OSError:
            pass


def finalize(wav_path: str, m4a_path: str, on_progress: Callable[[float], None] = lambda f: None) -> str:
    """WAV kaydı M4A'ya çevirir (yaklaşık 10 kat küçük) ve WAV'ı siler. M4A yolunu döndürür.
    Çeviri başarısız olursa WAV olduğu gibi bırakılır ve onun yolu döner."""
    import converters

    try:
        converters.video_to_audio(wav_path, m4a_path, lambda f, m: on_progress(f))
    except Exception:  # noqa: BLE001
        if os.path.exists(m4a_path):
            try:
                os.remove(m4a_path)
            except OSError:
                pass
        return wav_path
    try:
        os.remove(wav_path)
    except OSError:
        pass
    return m4a_path


def permission_help() -> str:
    if sys.platform == "darwin":
        return ("Mikrofondan ses gelmiyor. Trafyle'ın mikrofon izni kapalı olabilir:\n"
                "Sistem Ayarları › Gizlilik ve Güvenlik › Mikrofon › Trafyle'ı açın, sonra kaydı yeniden başlatın.")
    if os.name == "nt":
        return ("Mikrofondan ses gelmiyor. Windows'ta mikrofon erişimi kapalı olabilir:\n"
                "Ayarlar › Gizlilik ve güvenlik › Mikrofon › “Masaüstü uygulamalarının mikrofonunuza erişmesine izin ver”i açın.")
    return "Mikrofondan ses gelmiyor. Mikrofonun bağlı ve açık olduğunu kontrol edin."


def fmt_clock(sec: float) -> str:
    sec = int(sec)
    return f"{sec // 3600:02d}:{sec % 3600 // 60:02d}:{sec % 60:02d}"


__all__ = ["AVAILABLE", "Recorder", "default_folder", "default_input", "finalize", "fmt_clock",
           "input_devices", "new_name", "permission_help"]
