"""Trafyle dönüştürme motoru.

- faster-whisper ile ses/video dosyasını metne çevirir.
- sherpa-onnx ile konuşmacıları ayırır (isteğe bağlı).
- Modeller uygulamaya gömülmez; ilk kullanımda kullanıcının bilgisayarına indirilir.
- Ses çözme faster-whisper'ın kendi kütüphanesiyle (PyAV) yapılır; ayrı ffmpeg gerekmez.
- Her şey bilgisayarda çalışır; kayıtlar internete gönderilmez.
"""
from __future__ import annotations

import os
import sys
import time
import threading
from dataclasses import dataclass, field
from typing import Callable, Optional

import numpy as np

SAMPLE_RATE = 16000

# (anahtar, görünen ad, yaklaşık indirme boyutu MB)
MODELS = [
    ("tiny", "Çok hızlı · düşük doğruluk", 75),
    ("base", "Hızlı · orta doğruluk", 145),
    ("small", "Dengeli", 485),
    ("medium", "Yavaş · yüksek doğruluk", 1530),
    ("large-v3-turbo", "En doğru (önerilen)", 1620),
]
MODEL_SIZES = {k: mb for k, _, mb in MODELS}
DEFAULT_MODEL = "large-v3-turbo"

LANGUAGES = [("Türkçe", "tr"), ("İngilizce", "en"), ("Otomatik algıla", None)]

AUDIO_EXTS = (".m4a", ".mp3", ".wav", ".ogg", ".oga", ".opus", ".aac", ".flac", ".wma", ".webm",
              ".mp4", ".m4v", ".mov", ".mkv", ".avi")

# Konuşmacı ayırma modelleri (sherpa-onnx yayınları)
_DIAR_BASE = "https://github.com/k2-fsa/sherpa-onnx/releases/download"
DIAR_SEG_URL = f"{_DIAR_BASE}/speaker-segmentation-models/sherpa-onnx-pyannote-segmentation-3-0.tar.bz2"
DIAR_EMB_URL = f"{_DIAR_BASE}/speaker-recongition-models/nemo_en_titanet_small.onnx"
DIAR_SIZE_MB = 47


def _data_root() -> tuple[str, str]:
    """(yeni klasör, eski SesMetin klasörü)"""
    if sys.platform == "darwin":
        root = os.path.expanduser("~/Library/Application Support")
        return os.path.join(root, "Trafyle"), os.path.join(root, "SesMetin")
    if os.name == "nt":
        root = os.environ.get("APPDATA", os.path.expanduser("~"))
        return os.path.join(root, "Trafyle"), os.path.join(root, "SesMetin")
    root = os.path.expanduser("~/.local/share")
    return os.path.join(root, "trafyle"), os.path.join(root, "sesmetin")


_APP_DIR: Optional[str] = None


def app_dir() -> str:
    """Ayarlar ve indirilen modeller. Eski adla (SesMetin) indirilmiş modeller yeniden indirilmesin diye
    ilk açılışta eski klasör yeni ada taşınır."""
    global _APP_DIR
    if _APP_DIR:
        return _APP_DIR
    base, old = _data_root()
    if not os.path.exists(base) and os.path.isdir(old):
        try:
            os.rename(old, base)
        except OSError:
            pass
    os.makedirs(base, exist_ok=True)
    _APP_DIR = base
    return base


def model_dir(key: str) -> str:
    return os.path.join(app_dir(), "models", key)


def is_downloaded(key: str) -> bool:
    d = model_dir(key)
    return os.path.isfile(os.path.join(d, "model.bin")) and os.path.isfile(os.path.join(d, "config.json"))


def download_model(key: str) -> str:
    """Döküm modelini indirir (bir kerelik). Ağ yoksa anlaşılır bir hata verir."""
    from faster_whisper import download_model as _dl

    target = model_dir(key)
    os.makedirs(target, exist_ok=True)
    try:
        _dl(key, output_dir=target)
    except Exception as e:  # noqa: BLE001
        raise RuntimeError(
            f"Model indirilemedi ({key}). İnternet bağlantınızı kontrol edip tekrar deneyin.\nAyrıntı: {e}"
        ) from e
    if not is_downloaded(key):
        raise RuntimeError(f"Model indirmesi tamamlanmadı ({key}). Tekrar deneyin.")
    return target


# ---------------------------------------------------------------- konuşmacı ayırma modelleri

def diar_dir() -> str:
    return os.path.join(app_dir(), "models", "konusmaci")


def diar_paths() -> tuple[str, str]:
    d = diar_dir()
    return os.path.join(d, "segmentation.onnx"), os.path.join(d, "embedding.onnx")


def diar_downloaded() -> bool:
    return all(os.path.isfile(p) for p in diar_paths())


def _download(url: str, dest: str, on_bytes: Callable[[int, int], None], cancel: threading.Event) -> None:
    import ssl
    import urllib.request

    try:
        import certifi
        ctx = ssl.create_default_context(cafile=certifi.where())
    except Exception:  # noqa: BLE001
        ctx = ssl.create_default_context()
    tmp = dest + ".part"
    req = urllib.request.Request(url, headers={"User-Agent": "Trafyle"})
    with urllib.request.urlopen(req, context=ctx, timeout=60) as r, open(tmp, "wb") as f:
        total = int(r.headers.get("Content-Length") or 0)
        got = 0
        while True:
            if cancel.is_set():
                raise Cancelled()
            chunk = r.read(1 << 16)
            if not chunk:
                break
            f.write(chunk)
            got += len(chunk)
            on_bytes(got, total)
    os.replace(tmp, dest)


def download_diar_models(on_status: Callable[[str], None], cancel: threading.Event) -> None:
    import tarfile

    seg_path, emb_path = diar_paths()
    os.makedirs(diar_dir(), exist_ok=True)
    try:
        if not os.path.isfile(seg_path):
            arc = os.path.join(diar_dir(), "seg.tar.bz2")
            _download(DIAR_SEG_URL, arc, lambda g, t: on_status(
                f"Konuşmacı modeli indiriliyor (1/2, bir kerelik) %{int(100 * g / t) if t else 0}"), cancel)
            with tarfile.open(arc, "r:bz2") as tf:
                member = next(m for m in tf.getmembers() if m.name.endswith("/model.onnx"))
                with tf.extractfile(member) as src, open(seg_path, "wb") as dst:
                    dst.write(src.read())
            os.remove(arc)
        if not os.path.isfile(emb_path):
            _download(DIAR_EMB_URL, emb_path, lambda g, t: on_status(
                f"Konuşmacı modeli indiriliyor (2/2, bir kerelik) %{int(100 * g / t) if t else 0}"), cancel)
    except Cancelled:
        raise
    except Exception as e:  # noqa: BLE001
        raise RuntimeError(
            "Konuşmacı ayırma modeli indirilemedi. İnternet bağlantınızı kontrol edin "
            f"ya da konuşmacı ayırmayı kapatıp tekrar deneyin.\nAyrıntı: {e}") from e


# ---------------------------------------------------------------- veri yapıları

@dataclass
class Segment:
    start: float
    end: float
    text: str
    speaker: str = ""


@dataclass
class Result:
    segments: list[Segment]
    duration: float
    language: str
    model: str
    speakers: list[str] = field(default_factory=list)
    audio: Optional[np.ndarray] = field(default=None, repr=False)  # int16, 16 kHz mono (dinleme için)


class Cancelled(Exception):
    pass


def load_audio(path: str) -> np.ndarray:
    """Ses ya da video dosyasını 16 kHz mono float32 diziye çevirir."""
    from faster_whisper import decode_audio

    try:
        return decode_audio(path, sampling_rate=SAMPLE_RATE)
    except Exception as e:  # noqa: BLE001
        raise RuntimeError(f"Dosya okunamadı. Desteklenen bir ses/video dosyası olduğundan emin olun.\nAyrıntı: {e}") from e


def speaker_name(i: int) -> str:
    return f"Konuşmacı {i}"


def diarize(audio: np.ndarray, num_speakers: int = 0,
            on_progress: Callable[[float], None] = lambda f: None,
            cancel: Optional[threading.Event] = None) -> list[tuple[float, float, int]]:
    """Konuşmacı dönemlerini (başlangıç, bitiş, konuşmacı no) döndürür. num_speakers=0: otomatik."""
    import sherpa_onnx as so

    cancel = cancel or threading.Event()
    seg_path, emb_path = diar_paths()
    cfg = so.OfflineSpeakerDiarizationConfig(
        segmentation=so.OfflineSpeakerSegmentationModelConfig(
            pyannote=so.OfflineSpeakerSegmentationPyannoteModelConfig(model=seg_path),
            num_threads=max(1, (os.cpu_count() or 4) // 2)),
        embedding=so.SpeakerEmbeddingExtractorConfig(model=emb_path, num_threads=max(1, (os.cpu_count() or 4) // 2)),
        clustering=so.FastClusteringConfig(num_clusters=num_speakers if num_speakers > 0 else -1, threshold=0.6),
        min_duration_on=0.3,
        min_duration_off=0.5,
    )
    if not cfg.validate():
        raise RuntimeError("Konuşmacı ayırma modeli yüklenemedi. Model dosyalarını silip tekrar indirmeyi deneyin.")
    sd = so.OfflineSpeakerDiarization(cfg)

    def cb(done: int, total: int) -> int:
        if not cancel.is_set():
            on_progress(done / total if total else 0.0)
        return 0

    # Kütüphane işlemi yarıda kesmeye izin vermediği için ayrı iş parçacığında çalıştırılır;
    # iptal edilince sonucu beklemeden dönülür (arka plandaki hesap kendiliğinden biter).
    box: dict = {}

    def run():
        try:
            box["result"] = sd.process(audio, callback=cb).sort_by_start_time()
        except Exception as e:  # noqa: BLE001
            box["error"] = e

    th = threading.Thread(target=run, daemon=True)
    th.start()
    while th.is_alive():
        if cancel.is_set():
            raise Cancelled()
        th.join(0.1)
    if cancel.is_set():
        raise Cancelled()
    if "error" in box:
        raise RuntimeError(f"Konuşmacılar ayrılamadı: {box['error']}")
    return [(float(s.start), float(s.end), int(s.speaker)) for s in box["result"]]


def assign_speakers(segments: list[Segment], turns: list[tuple[float, float, int]]) -> list[str]:
    """Her metin parçasına en çok örtüştüğü konuşmacıyı atar.

    Konuşmacılar ilk konuştukları sıraya göre "Konuşmacı 1, 2, …" diye adlandırılır.
    Döndürülen liste kullanılan adlardır.
    """
    if not turns:
        return []
    order: dict[int, str] = {}
    for _, _, spk in sorted(turns):
        if spk not in order:
            order[spk] = speaker_name(len(order) + 1)
    for seg in segments:
        best, best_ov = None, 0.0
        for a, b, spk in turns:
            ov = min(seg.end, b) - max(seg.start, a)
            if ov > best_ov:
                best, best_ov = spk, ov
        if best is None:  # örtüşme yoksa en yakın dönem
            mid = (seg.start + seg.end) / 2
            best = min(turns, key=lambda t: min(abs(mid - t[0]), abs(mid - t[1])))[2]
        seg.speaker = order[best]
    used = []
    for seg in segments:
        if seg.speaker not in used:
            used.append(seg.speaker)
    return used


class Engine:
    """Yüklü modeli bellekte tutar; aynı modelle art arda dosyalar hızlı işlenir."""

    def __init__(self):
        self._model = None
        self._model_key: Optional[str] = None
        self._lock = threading.Lock()

    def _get_model(self, key: str):
        if self._model is not None and self._model_key == key:
            return self._model
        from faster_whisper import WhisperModel

        self._model = None  # önce eskisini bırak
        self._model = WhisperModel(model_dir(key), device="cpu", compute_type="int8",
                                   cpu_threads=max(1, (os.cpu_count() or 4)))
        self._model_key = key
        return self._model

    def transcribe(
        self,
        path: str,
        model_key: str,
        language: Optional[str] = "tr",
        glossary: str = "",
        vad: bool = True,
        speakers: bool = False,
        num_speakers: int = 0,
        on_status: Callable[[str], None] = lambda s: None,
        on_progress: Callable[[float, Optional[float], Optional[Segment]], None] = lambda f, eta, seg: None,
        cancel: Optional[threading.Event] = None,
    ) -> Result:
        """İlerleme: konuşmacı ayırma açıksa dökümü %0-80, ayırmayı %80-100 arasında bildirir."""
        cancel = cancel or threading.Event()
        with self._lock:
            if not is_downloaded(model_key):
                on_status(f"Model indiriliyor: {model_key} (~{MODEL_SIZES.get(model_key, '?')} MB, bir kerelik)")
                download_model(model_key)
            if speakers and not diar_downloaded():
                download_diar_models(on_status, cancel)
            if cancel.is_set():
                raise Cancelled()

            on_status("Model yükleniyor…")
            model = self._get_model(model_key)
            if cancel.is_set():
                raise Cancelled()

            on_status("Dosya okunuyor…")
            audio = load_audio(path)
            duration = len(audio) / SAMPLE_RATE
            if duration < 0.1:
                raise RuntimeError("Dosyada ses bulunamadı.")

            prompt = None
            terms = [t.strip() for t in glossary.replace("\n", ",").split(",") if t.strip()]
            if terms:
                # Özel isim ve terimler modele ipucu olarak verilir.
                prompt = "Bu kayıtta geçen bazı isim ve terimler: " + ", ".join(terms) + "."

            on_status("Metne dönüştürülüyor…")
            seg_iter, info = model.transcribe(
                audio,
                language=language,
                beam_size=5,
                vad_filter=vad,
                vad_parameters={"min_silence_duration_ms": 500} if vad else None,
                initial_prompt=prompt,
                # Önceki metne koşullama kapalı: Whisper'ın aynı cümleyi tekrar tekrar
                # üretme (döngüye girme) eğilimini büyük ölçüde azaltır.
                condition_on_previous_text=False,
            )

            share = 0.8 if speakers else 1.0
            segments: list[Segment] = []
            t0 = time.monotonic()
            for s in seg_iter:
                if cancel.is_set():
                    raise Cancelled()
                text = s.text.strip()
                if not text:
                    continue
                seg = Segment(float(s.start), float(s.end), text)
                segments.append(seg)
                frac = share * (min(1.0, seg.end / duration) if duration else 0.0)
                elapsed = time.monotonic() - t0
                eta = elapsed * (1 - frac) / frac if frac > 0.02 else None
                on_progress(frac, eta, seg)

            names: list[str] = []
            if speakers and segments:
                on_status("Konuşmacılar ayrılıyor…")
                t1 = time.monotonic()

                def dprog(f: float):
                    frac = share + (1 - share) * f
                    el = time.monotonic() - t1
                    eta = el * (1 - f) / f if f > 0.05 else None
                    on_progress(frac, eta, None)

                turns = diarize(audio, num_speakers, dprog, cancel)
                names = assign_speakers(segments, turns)

            audio16 = (np.clip(audio, -1, 1) * 32767).astype(np.int16)
            return Result(segments=segments, duration=duration, language=info.language or (language or ""),
                          model=model_key, speakers=names, audio=audio16)
