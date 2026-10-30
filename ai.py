"""Bulut yapay zekâsıyla özetleme — kullanıcının kendi API anahtarıyla.

Bu dosyadaki işlemler METNİ SEÇİLEN SAĞLAYICIYA GÖNDERİR. Trafyle'ın internete metin gönderen tek
bölümü budur ve yalnızca kullanıcı açıkça onay verdikten sonra çalışır (onay arayüzde istenir).

Sağlayıcılar: Anthropic (Claude), OpenAI (ChatGPT), Google (Gemini). Ek SDK gerekmez; doğrudan HTTPS.
Anahtarlar işletim sisteminin anahtar deposunda saklanır (Mac: Anahtar Zinciri, Windows: Kimlik Bilgileri).
"""
from __future__ import annotations

import json
import re
import ssl
import threading
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Callable, Optional

KEYRING_SERVICE = "Trafyle"


@dataclass
class Provider:
    key: str
    name: str            # arayüzde
    company: str         # şirket adı
    product: str         # hizmet adı
    company_dat: str     # "Anthropic'e"
    company_gen: str     # "Anthropic'in"
    product_dat: str     # "Claude'a"
    models: list         # (model kimliği, açıklama) — ilki varsayılan
    key_url: str
    key_help: str


PROVIDERS = [
    Provider("anthropic", "Claude (Anthropic)", "Anthropic", "Claude", "Anthropic'e", "Anthropic'in", "Claude'a",
             [("claude-sonnet-5-5", "Sonnet 5.5 · dengeli (önerilen)"),
              ("claude-haiku-5-5", "Haiku 5.5 · hızlı ve ucuz"),
              ("claude-opus-5-5", "Opus 5.5 · en güçlü")],
             "https://console.anthropic.com/settings/keys",
             "console.anthropic.com adresinde hesap açın › Settings › API Keys › Create Key. "
             "Kullanım için Billing bölümünden kredi yüklemeniz gerekir."),
    Provider("openai", "ChatGPT (OpenAI)", "OpenAI", "ChatGPT", "OpenAI'a", "OpenAI'ın", "ChatGPT'ye",
             [("gpt-6.1-sol", "GPT-6.1 Sol · dengeli (önerilen)"),
              ("gpt-6-luna", "GPT-6 Luna · hızlı ve ucuz"),
              ("gpt-6-astra", "GPT-6 Astra · en güçlü")],
             "https://platform.openai.com/api-keys",
             "platform.openai.com adresinde oturum açın › API keys › Create new secret key. "
             "ChatGPT Plus aboneliği API kullanımını kapsamaz; Billing bölümünden kredi yüklemeniz gerekir."),
    Provider("gemini", "Gemini (Google)", "Google", "Gemini", "Google'a", "Google'ın", "Gemini'ye",
             [("gemini-3.8-flash", "Gemini 3.8 Flash · dengeli (önerilen)"),
              ("gemini-3.5-flash-lite", "Gemini 3.5 Flash-Lite · hızlı ve ucuz")],
             "https://aistudio.google.com/apikey",
             "aistudio.google.com/apikey adresinde Google hesabınızla oturum açın › Create API key. "
             "Ücretsiz kullanım kotası vardır; ücretsiz katmanda Google gönderilen metinleri ürün geliştirmede "
             "kullanabilir."),
]
PROVIDER_BY_KEY = {p.key: p for p in PROVIDERS}


class AIError(Exception):
    pass


class Cancelled(Exception):
    pass


# ------------------------------------------------------------------ anahtar saklama

def _keyring():
    try:
        import keyring
        return keyring
    except Exception:  # noqa: BLE001
        return None


_MEMORY_KEYS: dict[str, str] = {}   # anahtar deposu yoksa yalnızca bu oturum için


def get_key(provider: str) -> str:
    kr = _keyring()
    if kr is not None:
        try:
            return kr.get_password(KEYRING_SERVICE, provider) or ""
        except Exception:  # noqa: BLE001
            pass
    return _MEMORY_KEYS.get(provider, "")


def set_key(provider: str, value: str) -> bool:
    """Anahtarı kaydeder. Kalıcı depoya yazılabildiyse True, yalnızca bu oturumda tutuluyorsa False."""
    value = (value or "").strip()
    kr = _keyring()
    if kr is not None:
        try:
            if value:
                kr.set_password(KEYRING_SERVICE, provider, value)
            else:
                try:
                    kr.delete_password(KEYRING_SERVICE, provider)
                except Exception:  # noqa: BLE001
                    pass
            _MEMORY_KEYS.pop(provider, None)
            return True
        except Exception:  # noqa: BLE001
            pass
    if value:
        _MEMORY_KEYS[provider] = value
    else:
        _MEMORY_KEYS.pop(provider, None)
    return False


def mask(key: str) -> str:
    return "" if not key else (key[:6] + "…" + key[-4:] if len(key) > 14 else "…")


# ------------------------------------------------------------------ HTTP

def _ctx():
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except Exception:  # noqa: BLE001
        return ssl.create_default_context()


def _request(url: str, headers: dict, body: Optional[dict] = None, timeout: int = 300,
             cancel: Optional[threading.Event] = None) -> dict:
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(url, data=data, method="POST" if data is not None else "GET",
                                 headers={"Content-Type": "application/json", "User-Agent": "Trafyle", **headers})
    result: dict = {}

    def go():
        try:
            with urllib.request.urlopen(req, timeout=timeout, context=_ctx()) as r:
                result["data"] = json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            try:
                payload = e.read().decode("utf-8", "replace")
            except Exception:  # noqa: BLE001
                payload = ""
            result["http"] = (e.code, payload)
        except Exception as e:  # noqa: BLE001
            result["exc"] = e

    t = threading.Thread(target=go, daemon=True)
    t.start()
    while t.is_alive():
        t.join(0.2)
        if cancel is not None and cancel.is_set():
            raise Cancelled()
    if "data" in result:
        return result["data"]
    if "http" in result:
        raise AIError(_http_message(*result["http"]))
    e = result.get("exc")
    raise AIError("Sağlayıcıya bağlanılamadı. İnternet bağlantınızı kontrol edin." + (f"\n\n({e})" if e else ""))


def _http_message(code: int, payload: str) -> str:
    detail = ""
    try:
        j = json.loads(payload)
        err = j.get("error", j)
        detail = err.get("message", "") if isinstance(err, dict) else str(err)
    except Exception:  # noqa: BLE001
        detail = payload[:300]
    low = detail.lower()
    if code in (401, 403) or "api key" in low and ("invalid" in low or "not valid" in low):
        return "API anahtarı geçersiz ya da bu işlem için yetkisi yok. Yapay zekâ ayarlarından anahtarı kontrol edin."
    if code == 402 or "credit" in low or "billing" in low or "insufficient_quota" in low or "quota" in low:
        return ("Hesabınızda kullanılabilir kredi ya da kota kalmamış görünüyor. Sağlayıcının sayfasından "
                "bakiye/kota durumunuzu kontrol edin.\n\n" + detail[:200])
    if code == 429:
        return "Sağlayıcı şu anda çok fazla istek aldığını bildiriyor. Biraz bekleyip yeniden deneyin."
    if code == 404 or "model" in low and ("not found" in low or "does not exist" in low):
        return "Seçilen model bulunamadı ya da hesabınızda kullanılamıyor. Ayarlardan başka bir model seçin.\n\n" + detail[:200]
    if code >= 500:
        return "Sağlayıcının sunucusunda geçici bir sorun var. Biraz sonra yeniden deneyin."
    return f"Sağlayıcı isteği reddetti ({code}).\n\n{detail[:300]}"


# ------------------------------------------------------------------ sağlayıcı çağrıları

def complete(provider: str, api_key: str, model: str, system: str, user: str,
             cancel: Optional[threading.Event] = None, max_tokens: int = 8000) -> str:
    if not api_key:
        raise AIError("API anahtarı girilmemiş. Yapay zekâ ayarlarından anahtarınızı ekleyin.")
    if provider == "anthropic":
        j = _request("https://api.anthropic.com/v1/messages",
                     {"x-api-key": api_key, "anthropic-version": "2023-06-01"},
                     {"model": model, "max_tokens": max_tokens, "system": system,
                      "messages": [{"role": "user", "content": user}]}, cancel=cancel)
        text = "".join(b.get("text", "") for b in j.get("content", []) if b.get("type") == "text")
    elif provider == "openai":
        j = _request("https://api.openai.com/v1/chat/completions",
                     {"Authorization": f"Bearer {api_key}"},
                     {"model": model, "messages": [{"role": "system", "content": system},
                                                   {"role": "user", "content": user}]}, cancel=cancel)
        choices = j.get("choices") or [{}]
        text = (choices[0].get("message") or {}).get("content") or ""
    elif provider == "gemini":
        j = _request(f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
                     {"x-goog-api-key": api_key},
                     {"systemInstruction": {"parts": [{"text": system}]},
                      "contents": [{"role": "user", "parts": [{"text": user}]}],
                      "generationConfig": {"maxOutputTokens": max(max_tokens, 16000)}}, cancel=cancel)
        cands = j.get("candidates") or []
        if not cands:
            reason = (j.get("promptFeedback") or {}).get("blockReason")
            raise AIError("Gemini yanıt üretmedi" + (f" ({reason})." if reason else "."))
        text = "".join(p.get("text", "") for p in (cands[0].get("content") or {}).get("parts", []))
    else:
        raise AIError("Bilinmeyen sağlayıcı.")
    text = (text or "").strip()
    if not text:
        raise AIError("Sağlayıcı boş yanıt döndürdü. Başka bir modelle yeniden deneyin.")
    return text


def list_models(provider: str, api_key: str) -> list[str]:
    """Hesapta kullanılabilen metin modellerini getirir (bağlantıyı da doğrular)."""
    if provider == "anthropic":
        j = _request("https://api.anthropic.com/v1/models?limit=100",
                     {"x-api-key": api_key, "anthropic-version": "2023-06-01"}, timeout=30)
        ids = [m.get("id", "") for m in j.get("data", [])]
    elif provider == "openai":
        j = _request("https://api.openai.com/v1/models", {"Authorization": f"Bearer {api_key}"}, timeout=30)
        ids = [m.get("id", "") for m in j.get("data", [])]
        skip = ("embedding", "whisper", "tts", "dall-e", "image", "audio", "realtime", "moderation",
                "transcribe", "search", "davinci", "babbage", "codex", "computer-use")
        ids = [i for i in ids if i.startswith(("gpt", "o")) and not any(s in i for s in skip)]
    elif provider == "gemini":
        j = _request("https://generativelanguage.googleapis.com/v1beta/models?pageSize=200",
                     {"x-goog-api-key": api_key}, timeout=30)
        ids = [m.get("name", "").replace("models/", "") for m in j.get("models", [])
               if "generateContent" in (m.get("supportedGenerationMethods") or [])]
        ids = [i for i in ids if i.startswith("gemini") and "embedding" not in i and "image" not in i
               and "tts" not in i]
    else:
        return []
    return sorted({i for i in ids if i}, reverse=True)


# ------------------------------------------------------------------ özetleme

SUMMARY_TYPES = [
    ("short", "Kısa özet"),
    ("points", "Ana noktalar (madde madde)"),
    ("meeting", "Toplantı notu (kararlar ve yapılacaklar)"),
    ("detailed", "Ayrıntılı özet (başlıklarla)"),
]
LANGUAGES = [("tr", "Türkçe"), ("en", "İngilizce"), ("same", "Metnin dilinde")]

_TASKS = {
    "short": "Metnin tek paragraflık (en fazla 120 kelime), akıcı bir özetini yaz.",
    "points": "Metnin en önemli noktalarını 5–12 maddelik bir liste olarak yaz. Her madde tek cümle olsun.",
    "meeting": ("Bu bir toplantı/görüşme dökümü. Şu başlıklarla bir toplantı notu hazırla:\n"
                "## Katılımcılar (dökümde geçen konuşmacı adları; yoksa bu başlığı atla)\n"
                "## Konuşulan konular\n## Alınan kararlar\n"
                "## Yapılacaklar (kim · ne · ne zaman — dökümde yoksa 'belirtilmedi' yaz)\n"
                "## Açık kalan sorular\n"
                "Dökümde olmayan hiçbir karar, kişi ya da tarih uydurma."),
    "detailed": ("Metnin ayrıntılı bir özetini, konulara göre ## başlıklara ayırarak yaz. Her başlık altında "
                 "kısa paragraflar ya da maddeler kullan. Önemli sayıları, adları ve tarihleri koru."),
}
_LANG = {"tr": "Özeti Türkçe yaz.", "en": "Write the summary in English.",
         "same": "Özeti metnin yazıldığı dilde yaz."}

SYSTEM = ("Sen titiz bir özetleme asistanısın. Yalnızca verilen metindeki bilgilere dayan; metinde olmayan "
          "bilgi ekleme, tahmin yürütme. Metin otomatik konuşma tanıma ile yazıya dökülmüş olabilir; bariz "
          "yazım hatalarını sessizce düzelt. Biçim için yalnızca sade Markdown kullan: '## ' başlık, '- ' madde, "
          "'**kalın**'. Giriş ya da kapanış cümlesi ('İşte özet:' gibi) yazma.")

CHUNK_CHARS = 120_000   # bundan uzun metinler parça parça özetlenir


def _prompt(text: str, kind: str, lang: str, extra: str, title: str) -> str:
    parts = [_TASKS.get(kind, _TASKS["short"]), _LANG.get(lang, _LANG["tr"])]
    if extra.strip():
        parts.append("Kullanıcının ek isteği: " + extra.strip())
    head = f"Belge adı: {title}\n" if title else ""
    return "\n".join(parts) + f"\n\n{head}<metin>\n{text}\n</metin>"


def split_chunks(text: str, size: int = CHUNK_CHARS) -> list[str]:
    if len(text) <= size:
        return [text]
    paras = re.split(r"(\n\s*\n|\n)", text)
    chunks, cur = [], ""
    for p in paras:
        if len(cur) + len(p) > size and cur.strip():
            chunks.append(cur)
            cur = ""
        while len(p) > size:              # tek parça çok uzunsa cümle sınırından böl
            cut = p.rfind(". ", 0, size)
            cut = cut + 1 if cut > size // 2 else size
            chunks.append(p[:cut])
            p = p[cut:]
        cur += p
    if cur.strip():
        chunks.append(cur)
    return chunks


def summarize(text: str, provider: str, model: str, kind: str = "short", lang: str = "tr", extra: str = "",
              title: str = "", on_status: Callable[[str], None] = lambda s: None,
              cancel: Optional[threading.Event] = None) -> str:
    key = get_key(provider)
    text = text.strip()
    if not text:
        raise AIError("Özetlenecek metin yok.")
    chunks = split_chunks(text)
    name = PROVIDER_BY_KEY[provider].name
    if len(chunks) == 1:
        on_status(f"{name} özetliyor…")
        return complete(provider, key, model, SYSTEM, _prompt(text, kind, lang, extra, title), cancel)
    # Uzun metin: önce her parça ayrıntılı özetlenir, sonra özetlerden istenen özet çıkarılır
    notes = []
    for i, ch in enumerate(chunks, 1):
        on_status(f"{name} özetliyor… (bölüm {i}/{len(chunks)})")
        notes.append(complete(provider, key, model, SYSTEM,
                              _prompt(ch, "detailed", lang, "Bu, uzun bir metnin bir bölümüdür; bölümdeki "
                                      "önemli bilgileri eksiksiz koru.", title), cancel))
    on_status(f"{name} bölümleri birleştiriyor…")
    merged = "\n\n".join(f"### Bölüm {i}\n{n}" for i, n in enumerate(notes, 1))
    return complete(provider, key, model, SYSTEM,
                    _prompt(merged, kind, lang, (extra + " ").strip() + " (Metin, uzun bir belgenin bölüm "
                            "özetlerinden oluşuyor; tek, bütünlüklü bir özet yaz.)", title), cancel)


def test_connection(provider: str, api_key: str, model: str) -> str:
    """Anahtarı ve modeli küçük bir istekle dener; başarılıysa kısa bir açıklama döndürür."""
    reply = complete(provider, api_key, model, "Kısa yanıt ver.", "Yalnızca 'tamam' yaz.", max_tokens=300)
    return reply[:40]
