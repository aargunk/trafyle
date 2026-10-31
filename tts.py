"""Metinden sese: Türkçe metni bilgisayarda, internete göndermeden seslendirir.

- Bilgisayarın kendi Türkçe sistem sesleri: Mac'te "say" komutuyla (ör. Yelda), Windows'ta Windows
  konuşma motoruyla (ör. Tolga). İndirme gerekmez.
- Konuşmacılı metinlerde ("Ad: metin" satırları) her konuşmacıya ayrı ses verilebilir.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import wave
from typing import Callable, Optional

import numpy as np

import engine

# Yalnızca işletim sisteminin kendi Türkçe sesleri kullanılır. (Önceki sürümlerdeki Piper sesleri, türetildikleri
# İngilizce sesin lisansı dağıtıma ve araştırma dışı kullanıma izin vermediği için kaldırıldı.)
OUT_SR = 22050          # tüm sesler bu örnekleme hızına getirilir
SYS = "sys:"            # sistem sesi anahtarlarının öneki
KNOWN_FEMALE = {"Yelda"}


def _say_bin() -> Optional[str]:
    if sys.platform != "darwin" and not os.environ.get("SESMETIN_SAY"):
        return None
    return os.environ.get("SESMETIN_SAY") or shutil.which("say")


def system_voices() -> list[tuple[str, str]]:
    """Yüklü Türkçe sistem seslerini listeler: [("sys:Yelda", "Yelda · kadın"), …]."""
    if os.name == "nt":
        try:
            import winplat
        except Exception:  # noqa: BLE001
            return []
        out = []
        for name, _lang, gender in winplat.speech_voices():
            short = name.replace("Microsoft ", "").split(" - ")[0]
            out.append((SYS + name, f"{short} · {gender}"))
        return out
    say = _say_bin()
    if not say:
        return []
    try:
        out = subprocess.run([say, "-v", "?"], capture_output=True, text=True, timeout=15).stdout
    except Exception:  # noqa: BLE001
        return []
    found = []
    for line in out.splitlines():
        m = re.match(r"^(.+?)\s+(tr_TR|tr-TR)\s+#", line)
        if not m:
            continue
        name = m.group(1).strip()
        base = name.split(" (")[0]
        gender = " · kadın" if base in KNOWN_FEMALE else ""
        found.append((SYS + name, f"{name}{gender}"))
    # Gelişmiş / Premium sürümler önce gelsin
    found.sort(key=lambda kv: (0 if "(" in kv[0] else 1, kv[0]))
    return found


def all_voices() -> list[tuple[str, str]]:
    return system_voices()


def distinct_voices(voices: list[tuple[str, str]]) -> list[tuple[str, str]]:
    """Aynı sesin farklı sürümlerinden (Yelda / Yelda (Gelişmiş)) yalnızca ilkini bırakır;
    konuşmacılara varsayılan ses dağıtırken kullanılır."""
    seen, out = set(), []
    for k, lbl in voices:
        base = k.split(" (")[0]
        if base not in seen:
            seen.add(base)
            out.append((k, lbl))
    return out


def is_system(key: str) -> bool:
    return key.startswith(SYS)


def voice_label(key: str, voices: Optional[list[tuple[str, str]]] = None) -> str:
    for k, lbl in (voices or all_voices()):
        if k == key:
            return lbl
    return key


def voice_ready(key: str) -> bool:
    return is_system(key)


# ---------------------------------------------------------------- metin hazırlığı



def normalize(text: str, lexicon: Optional[dict[str, str]] = None, use_default_lexicon: bool = True) -> str:
    """Seslendirmede sorun çıkaran yazımları okunduğu gibi yazar (bkz. trnorm)."""
    import trnorm

    return trnorm.normalize(text, lexicon, use_default_lexicon)


_SENT_RE = re.compile(r"(?<=[.!?…])\s+(?=[A-ZÇĞİÖŞÜ0-9\"'“(])")


def sentences(text: str) -> list[str]:
    out = []
    for part in _SENT_RE.split(text.strip()):
        part = part.strip()
        if not part:
            continue
        # Çok uzun cümleleri virgüllerden böl (ses modeli uzun cümlelerde tekleyebilir)
        while len(part) > 280:
            cut = part.rfind(",", 0, 260)
            if cut < 40:
                cut = part.rfind(" ", 0, 260)
            if cut < 40:
                break
            out.append(part[:cut + 1].strip())
            part = part[cut + 1:].strip()
        out.append(part)
    return out


_SPK_RE = re.compile(r"^([^\s:][^:\n]{0,38}):\s+(.+)$")


def detect_speakers(text: str) -> list[str]:
    """Satır başında en az iki kez "Ad: …" biçiminde geçen adları konuşmacı sayar."""
    counts: dict[str, int] = {}
    order: list[str] = []
    for line in text.splitlines():
        m = _SPK_RE.match(line.strip())
        if not m:
            continue
        name = m.group(1).strip()
        if len(name.split()) > 4 or any(ch.isdigit() for ch in name) and not name.startswith("Konuşmacı"):
            continue
        if name not in counts:
            order.append(name)
        counts[name] = counts.get(name, 0) + 1
    return [n for n in order if counts[n] >= 2]


def script(text: str, default_voice: str, speaker_voices: dict[str, str],
           lexicon: Optional[dict[str, str]] = None, use_default_lexicon: bool = True) -> list[tuple[str, str, float]]:
    """Metni (ses, cümle, sonrasındaki sessizlik sn) parçalarına böler."""
    parts: list[tuple[str, str, float]] = []
    paragraphs = [p for p in re.split(r"\n\s*\n", text.strip()) if p.strip()]
    for p in paragraphs:
        lines = [ln.strip() for ln in p.splitlines() if ln.strip()]
        for ln in lines:
            voice = default_voice
            body = ln
            m = _SPK_RE.match(ln)
            if m and m.group(1).strip() in speaker_voices:
                voice = speaker_voices[m.group(1).strip()]
                body = m.group(2)
            for s in sentences(normalize(body, lexicon, use_default_lexicon)):
                parts.append((voice, s, 0.28))
            if parts:
                v, s, _ = parts[-1]
                parts[-1] = (v, s, 0.45)
        if parts:
            v, s, _ = parts[-1]
            parts[-1] = (v, s, 0.7)
    return parts


# ---------------------------------------------------------------- seslendirme

class Synth:
    def synthesize(self, parts: list[tuple[str, str, float]], speed: float,
                   on_status: Callable[[str], None], on_progress: Callable[[float], None],
                   cancel: threading.Event) -> tuple[np.ndarray, int]:
        if not parts:
            raise RuntimeError("Seslendirilecek metin yok.")
        if any(not is_system(v) for v, _, _ in parts):
            raise RuntimeError("Seçili ses bu bilgisayarda bulunamadı. Ses listesinden bir Türkçe ses seçin.")
        on_status("Seslendiriliyor…")
        # Sistem seslerinde art arda gelen aynı sesli cümleler tek seferde okunur (daha doğal ve hızlı)
        merged: list[list] = []
        for voice, sent, pause in parts:
            if (merged and is_system(voice) and merged[-1][0] == voice and merged[-1][2] < 0.6
                    and len(merged[-1][1]) + len(sent) < 700):
                merged[-1][1] += " " + sent
                merged[-1][2] = pause
            else:
                merged.append([voice, sent, pause])
        chunks: list[np.ndarray] = []
        total_chars = sum(len(s) for _, s, _ in merged) or 1
        done = 0
        for voice, sent, pause in merged:
            if cancel.is_set():
                raise engine.Cancelled()
            x = self._say(voice[len(SYS):], sent, speed)
            chunks.append(x)
            chunks.append(np.zeros(int(OUT_SR * pause), dtype=np.float32))
            done += len(sent)
            on_progress(done / total_chars)
        audio = np.concatenate(chunks) if chunks else np.zeros(1, np.float32)
        return np.clip(audio, -1, 1), OUT_SR

    def _say(self, name: str, text: str, speed: float) -> np.ndarray:
        if os.name == "nt":
            import winplat

            x, sr = winplat.speak_to_wav(name, text, speed)
            return _resample(x, sr, OUT_SR)
        say = _say_bin()
        if not say:
            raise RuntimeError("Sistem sesi bu bilgisayarda kullanılamıyor.")
        with tempfile.TemporaryDirectory() as td:
            src = os.path.join(td, "metin.txt")
            out = os.path.join(td, "ses.wav")
            with open(src, "w", encoding="utf-8") as f:
                f.write(text)
            rate = max(90, int(180 * speed))
            r = subprocess.run([say, "-v", name, "-r", str(rate), "-f", src, "-o", out,
                                "--file-format=WAVE", f"--data-format=LEI16@{OUT_SR}"],
                               capture_output=True, text=True, timeout=900)
            if r.returncode != 0 or not os.path.isfile(out):
                raise RuntimeError(f"Sistem sesi ({name}) çalışmadı. {r.stderr.strip()}")
            x, sr = _read_wav(out)
        return _resample(x, sr, OUT_SR)


def _read_wav(path: str) -> tuple[np.ndarray, int]:
    with wave.open(path, "rb") as w:
        sr, ch, width = w.getframerate(), w.getnchannels(), w.getsampwidth()
        raw = w.readframes(w.getnframes())
    if width != 2:
        raise RuntimeError("Beklenmeyen ses biçimi.")
    x = np.frombuffer(raw, dtype="<i2").astype(np.float32) / 32768.0
    if ch > 1:
        x = x.reshape(-1, ch).mean(axis=1)
    return x, sr


def _resample(x: np.ndarray, sr: int, target: int) -> np.ndarray:
    if sr == target or len(x) == 0:
        return x.astype(np.float32)
    n = int(round(len(x) * target / sr))
    return np.interp(np.linspace(0, len(x) - 1, n), np.arange(len(x)), x).astype(np.float32)


def save_audio(path: str, audio: np.ndarray, sr: int) -> None:
    pcm = (np.clip(audio, -1, 1) * 32767).astype(np.int16)
    if path.lower().endswith(".wav"):
        with wave.open(path, "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(sr)
            w.writeframes(pcm.tobytes())
        return
    import av

    out = av.open(path, "w")
    try:
        st = out.add_stream("aac", rate=sr)
        st.layout = "mono"
        frame = av.AudioFrame.from_ndarray(pcm.reshape(1, -1), format="s16", layout="mono")
        frame.sample_rate = sr
        for p in st.encode(frame):
            out.mux(p)
        for p in st.encode(None):
            out.mux(p)
    finally:
        out.close()


def read_text_file(path: str) -> str:
    if path.lower().endswith(".docx"):
        from docx import Document

        return "\n\n".join(p.text for p in Document(path).paragraphs if p.text.strip())
    for enc in ("utf-8", "utf-8-sig", "cp1254", "latin-1"):
        try:
            with open(path, encoding=enc) as f:
                return f.read()
        except UnicodeDecodeError:
            continue
    raise RuntimeError("Dosya okunamadı.")
