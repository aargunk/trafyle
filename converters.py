"""Dosya dönüştürme: taranmış belge → metin (OCR), PDF → metin/Word, video → ses, görüntü biçimleri.

Hepsi bilgisayarda çalışır, internete bir şey gönderilmez.
- OCR: macOS'ta yerleşik Vision çatısı (pyobjc), Windows'ta yerleşik Windows.Media.Ocr (pywinrt). Ek indirme gerekmez.
- PDF metni: pdfminer.six (MIT lisansı).
- Video → ses: PyAV (ffmpeg).
- Görüntüler: macOS'ta yerleşik `sips` aracı; Windows'ta Pillow (+ HEIC için pillow-heif).
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
from dataclasses import dataclass, field
from typing import Callable, Optional

IS_MAC = sys.platform == "darwin"
IS_WINDOWS = os.name == "nt"
INSTALLER = "Kur.bat" if IS_WINDOWS else "Kur.command"

IMAGE_EXTS = (".jpg", ".jpeg", ".png", ".heic", ".heif", ".tif", ".tiff", ".bmp", ".gif", ".webp")
PDF_EXTS = (".pdf",)
VIDEO_EXTS = (".mp4", ".mov", ".m4v", ".mkv", ".avi", ".webm", ".wmv", ".flv", ".3gp", ".mpg", ".mpeg", ".ts")


class Cancelled(Exception):
    pass


# ------------------------------------------------------------------ işlemler

@dataclass
class Op:
    key: str
    title: str
    desc: str
    exts: tuple
    outputs: list  # (etiket, uzantı)


OPS = [
    Op("ocr", "Taranmış belge → metin",
       "Fotoğrafı çekilmiş ya da taranmış sayfalardaki yazıyı okur.",
       IMAGE_EXTS + PDF_EXTS, [("Metin (.txt)", ".txt"), ("Word (.docx)", ".docx")]),
    Op("pdf", "PDF → metin / Word",
       "PDF'teki yazıyı paragraflarıyla çıkarır. Sayfa düzeni taşınmaz.",
       PDF_EXTS, [("Metin (.txt)", ".txt"), ("Word (.docx)", ".docx")]),
    Op("video", "Video → ses",
       "Video dosyasından ya da YouTube vb. bağlantıdan sesi alır.",
       VIDEO_EXTS, [("M4A (.m4a)", ".m4a"), ("MP3 (.mp3)", ".mp3"), ("WAV (.wav)", ".wav")]),
    Op("image", "Görüntü biçimi",
       "HEIC'i JPG'ye çevirir, biçim değiştirir, küçültür.",
       IMAGE_EXTS, [("JPG (.jpg)", ".jpg"), ("PNG (.png)", ".png")]),
]
OP_BY_KEY = {o.key: o for o in OPS}
ALL_EXTS = tuple(sorted(set(IMAGE_EXTS + PDF_EXTS + VIDEO_EXTS)))

IMAGE_SIZES = [("Aynı boyut", 0), ("En fazla 3000 px", 3000), ("En fazla 2000 px", 2000),
               ("En fazla 1600 px", 1600), ("En fazla 1200 px", 1200), ("En fazla 800 px", 800)]
JPG_QUALITY = [("Yüksek", 90), ("Orta", 75), ("Düşük (küçük dosya)", 60)]


_URL_RE = re.compile(r"^https?://[^\s/$.?#][^\s]*$", re.I)


def is_url(text: str) -> bool:
    return bool(_URL_RE.match(text.strip()))


def ops_for(path: str) -> list[str]:
    if is_url(path):
        return ["video"]
    p = path.lower()
    return [o.key for o in OPS if p.endswith(o.exts)]


def unique_path(path: str) -> str:
    if not os.path.exists(path):
        return path
    stem, ext = os.path.splitext(path)
    i = 1
    while os.path.exists(f"{stem} ({i}){ext}"):
        i += 1
    return f"{stem} ({i}){ext}"


def default_link_dir() -> str:
    if IS_WINDOWS:
        try:
            import winplat
            d = winplat.known_folder("downloads")
            if d:
                return d
        except Exception:  # noqa: BLE001
            pass
    d = os.path.join(os.path.expanduser("~"), "Downloads")
    return d if os.path.isdir(d) else os.path.expanduser("~")


def out_path(src: str, ext: str, out_dir: Optional[str]) -> str:
    if is_url(src):  # gerçek ad indirme sırasında belli olur
        return os.path.join(out_dir or default_link_dir(), "_baglanti" + ext)
    stem = os.path.splitext(os.path.basename(src))[0]
    folder = out_dir or os.path.dirname(src)
    return unique_path(os.path.join(folder, stem + ext))


@dataclass
class Outcome:
    path: str                       # yazılan dosya
    note: str = ""                  # kullanıcıya kısa bilgi
    text: Optional[str] = None      # metin çıktılarında içerik (Seslendir'e göndermek için)
    title: Optional[str] = None     # bağlantılarda videonun adı


Progress = Callable[[float, str], None]


def _noop(_f: float, _m: str) -> None:
    pass


def _check(cancel: Optional[threading.Event]):
    if cancel is not None and cancel.is_set():
        raise Cancelled()


# ------------------------------------------------------------------ metin yazma

@dataclass
class Block:
    text: str
    heading: bool = False


def write_text(blocks: list[Block], dst: str, title: str = "") -> str:
    """Bloklardan .txt ya da .docx yazar; düz metni döndürür."""
    plain = "\n\n".join(b.text for b in blocks)
    if dst.lower().endswith(".docx"):
        from docx import Document
        from docx.shared import Pt

        doc = Document()
        st = doc.styles["Normal"]
        st.font.name = "Calibri"
        st.font.size = Pt(11)
        for b in blocks:
            if b.heading:
                doc.add_heading(b.text, level=2)
            else:
                doc.add_paragraph(b.text)
        if title:
            doc.core_properties.title = title
        doc.save(dst)
    else:
        with open(dst, "w", encoding="utf-8") as f:
            f.write(plain + "\n")
    return plain


def _join_lines(lines: list[str]) -> str:
    """Satır sonlarında bölünmüş paragrafı birleştirir; satır sonu tirelerini kaldırır."""
    out = ""
    for ln in (s.strip() for s in lines):
        if not ln:
            continue
        if not out:
            out = ln
        elif out.endswith("-") and len(out) > 1 and out[-2].isalpha() and ln[:1].islower():
            out = out[:-1] + ln
        else:
            out += " " + ln
    return re.sub(r"[ \t]+", " ", out).strip()


_PAGE_NO = re.compile(r"^(sayfa\s*)?\d{1,4}(\s*/\s*\d{1,4})?$", re.I)


# ------------------------------------------------------------------ OCR (macOS Vision)

def ocr_available() -> bool:
    if IS_WINDOWS:
        try:
            import winplat
            import pypdfium2  # noqa: F401
            from PIL import Image  # noqa: F401
            return winplat.ocr_available()
        except Exception:  # noqa: BLE001
            return False
    if not IS_MAC:
        return False
    try:
        import Vision  # noqa: F401
        import Quartz  # noqa: F401
        return True
    except Exception:  # noqa: BLE001
        return False


def _vision_langs(req) -> list[str]:
    want = ["tr-TR", "en-US"]
    try:
        got, _err = req.supportedRecognitionLanguagesAndReturnError_(None)
        got = [str(x) for x in (got or [])]
        langs = [w for w in want if w in got]
        return langs or ["en-US"]
    except Exception:  # noqa: BLE001  (eski macOS: Türkçe desteklenmiyor)
        return ["en-US"]


def _ocr_lines(handler) -> list[tuple[str, float, float, float]]:
    """Vision ile metin satırlarını okur: (metin, üst, alt, sol) — 0..1, üst = 0."""
    import Vision

    req = Vision.VNRecognizeTextRequest.alloc().init()
    req.setRecognitionLevel_(Vision.VNRequestTextRecognitionLevelAccurate)
    req.setUsesLanguageCorrection_(True)
    req.setRecognitionLanguages_(_vision_langs(req))
    ok, err = handler.performRequests_error_([req], None)
    if not ok:
        raise RuntimeError(f"Metin tanıma başarısız: {err}")
    lines = []
    for obs in req.results() or []:
        cands = obs.topCandidates_(1)
        if not cands:
            continue
        text = str(cands[0].string()).strip()
        if not text:
            continue
        bb = obs.boundingBox()  # sol-alt köşe orijinli, 0..1
        top = 1.0 - (bb.origin.y + bb.size.height)
        bottom = 1.0 - bb.origin.y
        lines.append((text, top, bottom, bb.origin.x))
    return lines


def _lines_to_blocks(lines: list[tuple[str, float, float, float]]) -> list[Block]:
    """Satırları dikey boşluklara göre paragraflara ayırır."""
    if not lines:
        return []
    lines = sorted(lines, key=lambda l: (round(l[1], 3), l[3]))
    heights = sorted(l[2] - l[1] for l in lines)
    h = heights[len(heights) // 2] or 0.01
    blocks: list[list[str]] = [[lines[0][0]]]
    prev_bottom = lines[0][2]
    for text, top, bottom, _x in lines[1:]:
        if top - prev_bottom > h * 0.9:
            blocks.append([text])
        else:
            blocks[-1].append(text)
        prev_bottom = max(prev_bottom, bottom)
    out = []
    for b in blocks:
        t = _join_lines(b)
        if t and not _PAGE_NO.match(t):
            out.append(Block(t))
    return out


def _ocr_image(path: str) -> list[Block]:
    import Vision
    from Foundation import NSURL

    url = NSURL.fileURLWithPath_(os.path.abspath(path))
    handler = Vision.VNImageRequestHandler.alloc().initWithURL_options_(url, {})
    return _lines_to_blocks(_ocr_lines(handler))


def _pdf_page_image(doc, index: int, scale: float = 2.5):
    """PDF sayfasını (1'den başlar) beyaz zeminli bir CGImage'a çizer."""
    import Quartz

    page = Quartz.CGPDFDocumentGetPage(doc, index)
    box = Quartz.CGPDFPageGetBoxRect(page, Quartz.kCGPDFCropBox)
    bw, bh = box.size.width, box.size.height
    if Quartz.CGPDFPageGetRotationAngle(page) % 180 == 90:
        bw, bh = bh, bw
    # çok büyük sayfalarda belleği koru
    scale = min(scale, 5000 / max(bw, bh, 1))
    w, h = max(1, int(bw * scale)), max(1, int(bh * scale))
    cs = Quartz.CGColorSpaceCreateDeviceRGB()
    ctx = Quartz.CGBitmapContextCreate(None, w, h, 8, 0, cs, Quartz.kCGImageAlphaPremultipliedLast)
    Quartz.CGContextSetRGBFillColor(ctx, 1, 1, 1, 1)
    Quartz.CGContextFillRect(ctx, Quartz.CGRectMake(0, 0, w, h))
    Quartz.CGContextScaleCTM(ctx, scale, scale)
    t = Quartz.CGPDFPageGetDrawingTransform(page, Quartz.kCGPDFCropBox, Quartz.CGRectMake(0, 0, bw, bh), 0, True)
    Quartz.CGContextConcatCTM(ctx, t)
    Quartz.CGContextDrawPDFPage(ctx, page)
    return Quartz.CGBitmapContextCreateImage(ctx)


def _pdf_page_count_mac(path: str):
    import Quartz
    from Foundation import NSURL

    doc = Quartz.CGPDFDocumentCreateWithURL(NSURL.fileURLWithPath_(os.path.abspath(path)))
    if doc is None:
        raise RuntimeError("PDF açılamadı.")
    if Quartz.CGPDFDocumentIsEncrypted(doc) and not Quartz.CGPDFDocumentUnlockWithPassword(doc, b""):
        raise RuntimeError("PDF parola korumalı.")
    return doc, Quartz.CGPDFDocumentGetNumberOfPages(doc)


# ------------------------------------------------------------------ OCR (Windows)

def _pil_open(path: str):
    """Görüntüyü Pillow ile açar (HEIC desteğiyle) ve fotoğraf yönünü düzeltir."""
    from PIL import Image, ImageOps

    if path.lower().endswith((".heic", ".heif")):
        try:
            from pillow_heif import register_heif_opener
            register_heif_opener()
        except ImportError as e:
            raise RuntimeError("HEIC desteği kurulu değil. " + INSTALLER + "'a yeniden çift tıklayın.") from e
    im = Image.open(path)
    im.load()
    return ImageOps.exif_transpose(im)


_WIN_TR_MISSING = [False]


def _win_ocr_pil(img) -> list[Block]:
    import winplat

    limit = winplat.max_image_dimension()
    if max(img.size) > limit:
        img = img.copy()
        img.thumbnail((limit, limit))
    if img.mode not in ("RGB", "L"):
        from PIL import Image

        bg = Image.new("RGB", img.size, "white")
        rgba = img.convert("RGBA")
        bg.paste(rgba, mask=rgba.split()[-1])
        img = bg
    fd, tmp = tempfile.mkstemp(suffix=".png", prefix="trafyle-ocr-")
    os.close(fd)
    try:
        img.save(tmp, "PNG")
        lines, turkish = winplat.ocr_png(tmp)
    finally:
        try:
            os.remove(tmp)
        except OSError:
            pass
    if not turkish:
        _WIN_TR_MISSING[0] = True
    return _lines_to_blocks(lines)


def _win_ocr_pdf_pages(path: str, pages: Optional[list[int]], on_progress: Progress,
                       cancel: Optional[threading.Event]) -> dict[int, list[Block]]:
    import pypdfium2 as pdfium

    try:
        doc = pdfium.PdfDocument(path)
    except Exception as e:  # noqa: BLE001
        raise RuntimeError("PDF açılamadı (parola korumalı olabilir).") from e
    try:
        n = len(doc)
        todo = pages or list(range(1, n + 1))
        out: dict[int, list[Block]] = {}
        for k, i in enumerate(todo):
            _check(cancel)
            on_progress(k / len(todo), f"Sayfa {i}/{n} okunuyor…")
            page = doc[i - 1]
            w, h = page.get_size()
            scale = min(2.5, 5000 / max(w, h, 1))
            img = page.render(scale=scale).to_pil()
            out[i] = _win_ocr_pil(img)
            page.close()
        return out
    finally:
        doc.close()


def ocr_pdf_pages(path: str, pages: Optional[list[int]] = None, on_progress: Progress = _noop,
                  cancel: Optional[threading.Event] = None) -> dict[int, list[Block]]:
    """PDF sayfalarını görüntü olarak okur. Sayfa numaraları 1'den başlar."""
    if IS_WINDOWS:
        return _win_ocr_pdf_pages(path, pages, on_progress, cancel)
    import objc
    import Vision

    doc, n = _pdf_page_count_mac(path)
    todo = pages or list(range(1, n + 1))
    out: dict[int, list[Block]] = {}
    for k, i in enumerate(todo):
        _check(cancel)
        on_progress(k / len(todo), f"Sayfa {i}/{n} okunuyor…")
        with objc.autorelease_pool():
            img = _pdf_page_image(doc, i)
            handler = Vision.VNImageRequestHandler.alloc().initWithCGImage_options_(img, {})
            out[i] = _lines_to_blocks(_ocr_lines(handler))
    return out


def ocr(src: str, dst: str, on_progress: Progress = _noop, cancel: Optional[threading.Event] = None) -> Outcome:
    if not ocr_available():
        raise RuntimeError("Metin tanıma (OCR) bu bilgisayarda kullanılamıyor. "
                           f"{INSTALLER}'a yeniden çift tıklayıp kurulumu tamamlayın.")
    _WIN_TR_MISSING[0] = False
    if src.lower().endswith(".pdf"):
        pages = ocr_pdf_pages(src, None, on_progress, cancel)
        blocks = [b for i in sorted(pages) for b in pages[i]]
        note = f"{len(pages)} sayfa okundu"
    else:
        on_progress(0.1, "Görüntü okunuyor…")
        blocks = _win_ocr_pil(_pil_open(src)) if IS_WINDOWS else _ocr_image(src)
        note = "Görüntü okundu"
    if IS_WINDOWS and _WIN_TR_MISSING[0]:
        note += " · Türkçe tanıma yüklü değil, ş/ğ/ı hatalı olabilir"
    _check(cancel)
    if not blocks:
        raise RuntimeError("Görüntüde okunabilir yazı bulunamadı.")
    text = write_text(blocks, dst, os.path.splitext(os.path.basename(src))[0])
    return Outcome(dst, f"{note} · {len(text.split())} kelime", text)


# ------------------------------------------------------------------ PDF → metin

def _pdf_blocks(path: str, on_progress: Progress, cancel) -> list[list[Block]]:
    """Sayfa sayfa metin blokları (pdfminer). Satırlar boşluk ve yazı boyutuna göre paragraflanır."""
    from pdfminer.high_level import extract_pages
    from pdfminer.layout import LAParams, LTChar, LTTextContainer, LTTextLine
    from pdfminer.pdfpage import PDFPage

    with open(path, "rb") as f:
        total = sum(1 for _ in PDFPage.get_pages(f)) or 1
    pages_lines = []   # her sayfa: [(metin, y0, y1, boyut)]
    sizes: list[float] = []
    for pno, page in enumerate(extract_pages(path, laparams=LAParams())):
        _check(cancel)
        on_progress(pno / total, f"Sayfa {pno + 1}/{total}…")
        lines = []
        for el in page:
            if not isinstance(el, LTTextContainer):
                continue
            for line in el:
                if not isinstance(line, LTTextLine):
                    continue
                text = line.get_text().strip()
                if not text:
                    continue
                csz = [ch.size for ch in line if isinstance(ch, LTChar) and ch.get_text().strip()]
                size = sum(csz) / len(csz) if csz else line.height
                sizes.extend([size] * len(text))
                lines.append((text, line.y0, line.y1, size))
        pages_lines.append(lines)
    body = sorted(sizes)[len(sizes) // 2] if sizes else 0.0

    pages = []
    for lines in pages_lines:
        gaps = sorted(a[1] - b[2] for a, b in zip(lines, lines[1:]) if 0 <= a[1] - b[2] < (a[2] - a[1]) * 3)
        typical = gaps[len(gaps) // 2] if gaps else 0.0
        groups: list[list] = []
        for ln in lines:
            if groups:
                prev = groups[-1][-1]
                gap = prev[1] - ln[2]
                h = max(prev[2] - prev[1], 1.0)
                same_size = abs(ln[3] - prev[3]) <= max(prev[3], 1) * 0.15
                if same_size and 0 <= gap <= max(typical * 1.5, h * 0.35) + 0.5:
                    groups[-1].append(ln)
                    continue
            groups.append([ln])
        blocks = []
        for g in groups:
            text = _join_lines([x[0] for x in g])
            if not text or _PAGE_NO.match(text):
                continue
            size = g[0][3]
            heading = bool(body) and size >= body * 1.2 and len(text) < 140 and not text.endswith(".")
            blocks.append(Block(text, heading))
        pages.append(blocks)
    return pages


def pdf_to_text(src: str, dst: str, on_progress: Progress = _noop,
                cancel: Optional[threading.Event] = None) -> Outcome:
    try:
        pages = _pdf_blocks(src, lambda f, m: on_progress(f * 0.8, m), cancel)
    except Cancelled:
        raise
    except Exception as e:  # noqa: BLE001
        msg = str(e)
        if "password" in msg.lower() or "encrypt" in msg.lower():
            raise RuntimeError("PDF parola korumalı; açılamadı.") from e
        raise RuntimeError(f"PDF okunamadı: {msg}") from e
    # Yazısı olmayan (taranmış) sayfaları OCR ile oku
    empty = [i + 1 for i, p in enumerate(pages) if sum(len(b.text) for b in p) < 15]
    ocr_note = ""
    if empty:
        if ocr_available():
            res = ocr_pdf_pages(src, empty, lambda f, m: on_progress(0.8 + f * 0.2, "Taranmış " + m.lower()), cancel)
            for i, blocks in res.items():
                pages[i - 1] = blocks
            ocr_note = f" · {len(empty)} taranmış sayfa OCR ile okundu"
        elif len(empty) == len(pages):
            raise RuntimeError("Bu PDF'te seçilebilir yazı yok; taranmış bir belge olabilir. "
                               "“Taranmış belge → metin” işlemini deneyin.")
        else:
            ocr_note = f" · {len(empty)} sayfada yazı bulunamadı"
    blocks = [b for p in pages for b in p]
    if not blocks:
        raise RuntimeError("PDF'te yazı bulunamadı.")
    _check(cancel)
    text = write_text(blocks, dst, os.path.splitext(os.path.basename(src))[0])
    return Outcome(dst, f"{len(pages)} sayfa · {len(text.split())} kelime{ocr_note}", text)


# ------------------------------------------------------------------ video → ses

def video_to_audio(src: str, dst: str, on_progress: Progress = _noop,
                   cancel: Optional[threading.Event] = None) -> Outcome:
    import av

    ext = os.path.splitext(dst)[1].lower()
    with av.open(src) as inp:
        ast = next((s for s in inp.streams if s.type == "audio"), None)
        if ast is None:
            raise RuntimeError("Bu videoda ses yok.")
        dur = float(inp.duration / 1_000_000) if inp.duration else 0.0
        if not dur and ast.duration and ast.time_base:
            dur = float(ast.duration * ast.time_base)
        src_codec = ast.codec_context.name

        # Ses zaten AAC ise yeniden kodlamadan kopyala: hızlı ve kayıpsız
        if ext == ".m4a" and src_codec == "aac":
            try:
                _remux(inp, ast, dst, dur, on_progress, cancel)
                return Outcome(dst, f"{_fmt_dur(dur)} ses · kayıpsız kopyalandı")
            except Cancelled:
                raise
            except Exception:  # noqa: BLE001  (kapsayıcı uymazsa yeniden kodla)
                if os.path.exists(dst):
                    os.remove(dst)
                inp.seek(0)

        codec, bitrate, fmt_name = {".m4a": ("aac", 160_000, None), ".mp3": ("libmp3lame", 192_000, None),
                                    ".wav": ("pcm_s16le", 0, None)}[ext]
        _transcode(inp, ast, dst, codec, bitrate, dur, on_progress, cancel)
    return Outcome(dst, f"{_fmt_dur(dur)} ses")


def _fmt_dur(sec: float) -> str:
    sec = int(round(sec))
    if sec >= 3600:
        return f"{sec // 3600} sa {sec % 3600 // 60} dk"
    if sec >= 60:
        return f"{sec // 60} dk {sec % 60} sn"
    return f"{sec} sn"


def _remux(inp, ast, dst, dur, on_progress, cancel):
    import av

    out = av.open(dst, "w")
    try:
        if hasattr(out, "add_stream_from_template"):
            ost = out.add_stream_from_template(ast)
        else:
            ost = out.add_stream(template=ast)
        n = 0
        for pkt in inp.demux(ast):
            if pkt.dts is None:
                continue
            pkt.stream = ost
            out.mux(pkt)
            n += 1
            if n % 400 == 0:
                _check(cancel)
                if dur and pkt.pts is not None and pkt.time_base:
                    on_progress(min(1.0, float(pkt.pts * pkt.time_base) / dur), "Ses kopyalanıyor…")
    finally:
        out.close()


def _transcode(inp, ast, dst, codec, bitrate, dur, on_progress, cancel):
    import av

    rate = ast.codec_context.sample_rate or 44100
    channels = ast.codec_context.channels or 2
    layout = "mono" if channels == 1 else "stereo"
    out = av.open(dst, "w")
    try:
        try:
            ost = out.add_stream(codec, rate=rate)
        except Exception as e:  # noqa: BLE001
            raise RuntimeError(f"Bu biçimde kaydedilemiyor ({codec}). Başka bir çıktı biçimi seçin.") from e
        ost.layout = layout
        if bitrate:
            ost.bit_rate = bitrate
        fmt = ost.codec_context.format.name if ost.codec_context.format else "s16"
        res = av.AudioResampler(format=fmt, layout=layout, rate=rate)
        n = 0
        for frame in inp.decode(ast):
            frame.pts = None
            for rf in res.resample(frame):
                for p in ost.encode(rf):
                    out.mux(p)
            n += 1
            if n % 200 == 0:
                _check(cancel)
                if dur and frame.time is not None:
                    on_progress(min(1.0, frame.time / dur), "Ses çıkarılıyor…")
        for rf in res.resample(None):
            for p in ost.encode(rf):
                out.mux(p)
        for p in ost.encode(None):
            out.mux(p)
    finally:
        out.close()


# ------------------------------------------------------------------ bağlantıdan ses (yt-dlp)

def link_available() -> bool:
    try:
        import yt_dlp  # noqa: F401
        return True
    except Exception:  # noqa: BLE001
        return False


def downloader_version() -> str:
    try:
        import yt_dlp
        return yt_dlp.version.__version__
    except Exception:  # noqa: BLE001
        return ""


def _js_runtimes() -> dict:
    """YouTube için JavaScript çalıştırıcısı: pip ile gelen Deno; yoksa sistemdeki Node."""
    rt: dict = {}
    try:
        import deno
        rt["deno"] = {"path": deno.find_deno_bin()}
    except Exception:  # noqa: BLE001
        rt["deno"] = {}
    rt["node"] = {}
    return rt


def safe_name(name: str, limit: int = 90) -> str:
    name = re.sub(r'[\\/:*?"<>|\x00-\x1f]+', " ", name or "")
    name = re.sub(r"\s+", " ", name).strip(" .")
    return (name[:limit].rstrip(" .") or "ses")


class _Log:
    def __init__(self):
        self.errors: list[str] = []

    def debug(self, msg):
        pass

    def info(self, msg):
        pass

    def warning(self, msg):
        pass

    def error(self, msg):
        self.errors.append(str(msg))


def _link_error(msg: str) -> str:
    m = msg.lower()
    if any(k in m for k in ("unable to connect to proxy", "timed out", "getaddrinfo", "name or service",
                            "network is unreachable", "nodename nor servname", "connection refused",
                            "connection reset", "no address associated")):
        return "İnternete bağlanılamadı. Bağlantınızı kontrol edip yeniden deneyin."
    if "unsupported url" in m:
        return "Bu bağlantı desteklenmiyor. Videonun sayfa bağlantısını kopyaladığınızdan emin olun."
    if "not a bot" in m:
        return ("Site, bu bilgisayardan gelen isteği geçici olarak engelledi (robot denetimi). "
                "Bir süre sonra yeniden deneyin.")
    if "is live" in m or "live event" in m or "premieres in" in m:
        return "Canlı ya da henüz başlamamış yayınlar desteklenmiyor. Yayın bittikten sonra deneyin."
    if any(k in m for k in ("private video", "sign in to confirm your age", "members-only", "join this channel",
                            "login required", "requires authentication", "inappropriate for some users")):
        return "Bu video gizli, yaş doğrulaması, üyelik ya da giriş gerektiriyor; alınamadı."
    if "http error 404" in m or "not found" in m:
        return "Sayfa bulunamadı (404). Bağlantıyı kontrol edin."
    if "video unavailable" in m or "has been removed" in m or "not available in your country" in m:
        return "Video kaldırılmış ya da bu bölgede erişilemiyor."
    detail = re.sub(r"^error:\s*", "", msg.strip(), flags=re.I)[:220]
    return ("Bağlantıdaki ses alınamadı. Site değişmiş olabilir: “Bağlantı desteğini güncelle” düğmesiyle "
            f"güncelleyip yeniden deneyin.\n\nAyrıntı: {detail}")


def link_to_audio(url: str, ext: str, out_dir: str, on_progress: Progress = _noop,
                  cancel: Optional[threading.Event] = None) -> Outcome:
    """Bağlantıdaki videonun yalnızca ses kanalını indirir ve istenen biçimde kaydeder."""
    if not link_available():
        raise RuntimeError(f"Bağlantı desteği kurulu değil. {INSTALLER}'a yeniden çift tıklayın.")
    from yt_dlp import YoutubeDL

    tmp = tempfile.mkdtemp(prefix="trafyle-")
    log = _Log()

    def hook(d):
        if cancel is not None and cancel.is_set():
            raise Cancelled()
        if d.get("status") == "downloading":
            total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
            got = d.get("downloaded_bytes") or 0
            if total:
                frac = min(1.0, got / total)
                on_progress(frac * 0.85, f"Ses indiriliyor… %{int(frac * 100)} · {got / 1048576:.0f}/{total / 1048576:.0f} MB")
            else:
                on_progress(0.05, f"Ses indiriliyor… {got / 1048576:.1f} MB")

    def no_live(info, *, incomplete=False):
        if info.get("is_live") or info.get("live_status") in ("is_live", "is_upcoming"):
            return "Canlı yayınlar desteklenmiyor (is live)."
        return None

    opts = {
        # Önce yalnızca ses; site ayrı ses sunmuyorsa en düşük çözünürlüklü video (sesi sonra ayrılır)
        "format": "bestaudio[ext=m4a]/bestaudio/worst[acodec!=none][height>=144]/best",
        "outtmpl": {"default": os.path.join(tmp, "%(id)s.%(ext)s")},
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
        "logger": log,
        "progress_hooks": [hook],
        "match_filter": no_live,
        "socket_timeout": 30,
        "retries": 5,
        "fragment_retries": 5,
        "js_runtimes": _js_runtimes(),
        "remote_components": ["ejs:github"],
        "cachedir": os.path.join(tmp, "cache"),
    }
    try:
        on_progress(0.0, "Bağlantı açılıyor…")
        try:
            with YoutubeDL(opts) as ydl:
                info = ydl.extract_info(url, download=True)
        except Cancelled:
            raise
        except Exception as e:  # noqa: BLE001
            if cancel is not None and cancel.is_set():
                raise Cancelled() from e
            raise RuntimeError(_link_error(str(e) or "; ".join(log.errors))) from e
        if info is None:
            raise RuntimeError(_link_error("; ".join(log.errors) or "is live"))
        if info.get("_type") == "playlist" or info.get("entries"):
            raise RuntimeError("Bu bir oynatma listesi. Listedeki tek bir videonun bağlantısını verin.")
        files = [d.get("filepath") for d in info.get("requested_downloads") or [] if d.get("filepath")]
        if not files or not os.path.exists(files[0]):
            raise RuntimeError(_link_error("; ".join(log.errors) or "indirilen dosya bulunamadı"))
        _check(cancel)
        title = info.get("title") or info.get("id") or "ses"
        os.makedirs(out_dir, exist_ok=True)
        dst = unique_path(os.path.join(out_dir, safe_name(title) + ext))
        try:
            res = video_to_audio(files[0], dst, lambda f, m: on_progress(0.85 + f * 0.15, "Kaydediliyor…"), cancel)
        except Exception:
            if os.path.exists(dst):
                os.remove(dst)
            raise
        site = info.get("extractor_key") or ""
        site = {"Youtube": "YouTube", "Generic": ""}.get(site, site)
        res.note = res.note.replace(" · kayıpsız kopyalandı", "") + (f" · {site}" if site else "")
        res.title = title
        return res
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def update_downloader() -> tuple[bool, str]:
    """Bağlantı bileşenini (yt-dlp) günceller. Siteler sık değiştiği için ara sıra gerekir."""
    if getattr(sys, "frozen", False):
        return False, "Paketlenmiş sürümde güncelleme, uygulamanın yeni sürümüyle gelir."
    r = subprocess.run([sys.executable, "-m", "pip", "install", "-U", "-q", "yt-dlp", "yt-dlp-ejs", "deno"],
                       capture_output=True, text=True, timeout=600)
    if r.returncode != 0:
        return False, (r.stderr or r.stdout).strip()[-400:]
    r2 = subprocess.run([sys.executable, "-c", "import yt_dlp;print(yt_dlp.version.__version__)"],
                        capture_output=True, text=True)
    return True, r2.stdout.strip()


# ------------------------------------------------------------------ görüntüler

def _image_size_sips(src: str) -> tuple[int, int]:
    r = subprocess.run(["sips", "-g", "pixelWidth", "-g", "pixelHeight", src],
                       capture_output=True, text=True, check=True)
    w = int(re.search(r"pixelWidth:\s*(\d+)", r.stdout).group(1))
    h = int(re.search(r"pixelHeight:\s*(\d+)", r.stdout).group(1))
    return w, h


def convert_image(src: str, dst: str, max_px: int = 0, quality: int = 85,
                  on_progress: Progress = _noop, cancel: Optional[threading.Event] = None) -> Outcome:
    ext = os.path.splitext(dst)[1].lower()
    on_progress(0.2, "Görüntü dönüştürülüyor…")
    if IS_MAC and shutil.which("sips"):
        w, h = _image_size_sips(src)
        fmt = {".jpg": "jpeg", ".jpeg": "jpeg", ".png": "png"}[ext]
        cmd = ["sips", "-s", "format", fmt]
        if fmt == "jpeg":
            cmd += ["-s", "formatOptions", str(quality)]
        if max_px and max(w, h) > max_px:
            cmd += ["-Z", str(max_px)]
            nw, nh = (max_px, round(h * max_px / w)) if w >= h else (round(w * max_px / h), max_px)
        else:
            nw, nh = w, h
        cmd += [src, "--out", dst]
        r = subprocess.run(cmd, capture_output=True, text=True)
        if r.returncode != 0 or not os.path.exists(dst):
            raise RuntimeError("Görüntü dönüştürülemedi: " + (r.stderr.strip() or r.stdout.strip())[-300:])
    else:
        try:
            from PIL import Image
        except ImportError as e:
            raise RuntimeError("Görüntü dönüştürme bu sistemde kullanılamıyor.") from e
        with _pil_open(src) as im:
            if max_px and max(im.size) > max_px:
                im.thumbnail((max_px, max_px), Image.LANCZOS)
            if ext in (".jpg", ".jpeg"):
                if im.mode in ("RGBA", "LA", "P"):
                    bg = Image.new("RGB", im.size, "white")
                    rgba = im.convert("RGBA")
                    bg.paste(rgba, mask=rgba.split()[-1])
                    im = bg
                im.convert("RGB").save(dst, "JPEG", quality=quality, optimize=True)
            else:
                im.save(dst, "PNG", optimize=True)
            nw, nh = im.size
    _check(cancel)
    kb = os.path.getsize(dst) / 1024
    size = f"{kb / 1024:.1f} MB" if kb >= 1024 else f"{kb:.0f} KB"
    return Outcome(dst, f"{nw}×{nh} px · {size}".replace(".", ","))


# ------------------------------------------------------------------ tek giriş noktası

def run(op: str, src: str, dst: str, options: dict, on_progress: Progress = _noop,
        cancel: Optional[threading.Event] = None) -> Outcome:
    try:
        if op == "ocr":
            return ocr(src, dst, on_progress, cancel)
        if op == "pdf":
            return pdf_to_text(src, dst, on_progress, cancel)
        if op == "video":
            if is_url(src):
                return link_to_audio(src, os.path.splitext(dst)[1], os.path.dirname(dst), on_progress, cancel)
            return video_to_audio(src, dst, on_progress, cancel)
        if op == "image":
            return convert_image(src, dst, int(options.get("max_px", 0)), int(options.get("quality", 85)),
                                 on_progress, cancel)
        raise ValueError(op)
    except Exception:
        # yarım kalan çıktıyı bırakma
        if os.path.exists(dst):
            try:
                os.remove(dst)
            except OSError:
                pass
        raise
