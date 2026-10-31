"""Türkçe metni seslendirmeye hazırlar: sayıları, tarihleri, kısaltmaları ve sembolleri okunduğu gibi yazar.

Tüm sesler (Mac ve Windows'un Türkçe sesleri) aynı hazırlanmış metni okur; telaffuz
hatalarının çoğu bu adımda giderilir. Kullanıcının telaffuz sözlüğü en önce uygulanır.
"""
from __future__ import annotations

import re
from typing import Iterable, Optional

# ------------------------------------------------------------------ sayılar

_ONES = ["", "bir", "iki", "üç", "dört", "beş", "altı", "yedi", "sekiz", "dokuz"]
_TENS = ["", "on", "yirmi", "otuz", "kırk", "elli", "altmış", "yetmiş", "seksen", "doksan"]
_SCALES = [(10 ** 12, "trilyon"), (10 ** 9, "milyar"), (10 ** 6, "milyon"), (1000, "bin")]
_DIGITS = ["sıfır"] + _ONES[1:]


def _under_thousand(n: int) -> list[str]:
    out = []
    h, r = divmod(n, 100)
    if h:
        out += ([] if h == 1 else [_ONES[h]]) + ["yüz"]
    t, o = divmod(r, 10)
    if t:
        out.append(_TENS[t])
    if o:
        out.append(_ONES[o])
    return out


def number_words(n: int) -> str:
    """1984 → 'bin dokuz yüz seksen dört'."""
    if n == 0:
        return "sıfır"
    if n < 0:
        return "eksi " + number_words(-n)
    if n >= 10 ** 15:
        return " ".join(_DIGITS[int(d)] for d in str(n))
    words: list[str] = []
    for value, name in _SCALES:
        q, n = divmod(n, value)
        if q:
            if value == 1000 and q == 1:
                words.append("bin")                       # "bir bin" değil
            else:
                words += _under_thousand(q) + [name]
    words += _under_thousand(n)
    return " ".join(words)


_VOWELS = "aeıioöuü"
_ORD_SPECIAL = {"dört": "dördüncü"}


def _harmony_i(word: str) -> str:
    for ch in reversed(word):
        if ch in "aı":
            return "ı"
        if ch in "ei":
            return "i"
        if ch in "ou":
            return "u"
        if ch in "öü":
            return "ü"
    return "i"


def ordinal_words(n: int) -> str:
    """3 → 'üçüncü', 21 → 'yirmi birinci', 100 → 'yüzüncü'."""
    words = number_words(n).split()
    last = words[-1]
    if last in _ORD_SPECIAL:
        words[-1] = _ORD_SPECIAL[last]
    else:
        i = _harmony_i(last)
        words[-1] = last + ("nc" if last[-1] in _VOWELS else i + "nc") + i
    return " ".join(words)


def _int(s: str) -> int:
    return int(s.replace(".", ""))


def decimal_words(intpart: str, frac: str, sep_word: str = "virgül") -> str:
    head = number_words(_int(intpart))
    # baştaki sıfırlar tek tek okunur: 0,05 → sıfır virgül sıfır beş
    zeros = len(frac) - len(frac.lstrip("0"))
    tail = " ".join(["sıfır"] * zeros + ([number_words(int(frac))] if frac.lstrip("0") else []))
    return f"{head} {sep_word} {tail}".strip()


# ------------------------------------------------------------------ sözlükler

MONTHS = ["", "Ocak", "Şubat", "Mart", "Nisan", "Mayıs", "Haziran", "Temmuz", "Ağustos", "Eylül",
          "Ekim", "Kasım", "Aralık"]

ABBREVIATIONS = [
    (r"\bProf\.\s*Dr\.", "Profesör Doktor"),
    (r"\bDoç\.\s*Dr\.", "Doçent Doktor"),
    (r"\bDr\.\s*Öğr\.\s*Üyesi", "Doktor Öğretim Üyesi"),
    (r"\bÖğr\.\s*Gör\.", "Öğretim Görevlisi"),
    (r"\bArş\.\s*Gör\.", "Araştırma Görevlisi"),
    (r"\bYrd\.\s*Doç\.", "Yardımcı Doçent"),
    (r"\bProf\.", "Profesör"),
    (r"\bDoç\.", "Doçent"),
    (r"\bDr\.", "Doktor"),
    (r"\bAv\.", "Avukat"),
    (r"\bMüh\.", "Mühendis"),
    (r"\bSn\.", "Sayın"),
    (r"\bvb\.", "ve benzeri"),
    (r"\bvs\.", "vesaire"),
    (r"\bvd\.", "ve diğerleri"),
    (r"\bBkz\.", "Bakınız"),
    (r"\bbkz\.", "bakınız"),
    (r"\börn\.", "örneğin"),
    (r"\bÖrn\.", "Örneğin"),
    (r"\byy\.", "yüzyıl"),
    (r"\bM\.\s?Ö\.", "milattan önce"),
    (r"\bM\.\s?S\.", "milattan sonra"),
    (r"\bTel\.", "telefon"),
    (r"\bNo\s?:\s?", "numara "),
    (r"\bNo\.\s?", "numara "),
    (r"\bmah\.", "mahallesi"),
    (r"\bMah\.", "Mahallesi"),
    (r"\bcad\.", "caddesi"),
    (r"\bCad\.", "Caddesi"),
    (r"\bsok\.", "sokak"),
    (r"\bSok\.", "Sokak"),
    (r"\bvb\b", "ve benzeri"),
]

UNITS = {
    "km": "kilometre", "m": "metre", "cm": "santimetre", "mm": "milimetre",
    "kg": "kilogram", "gr": "gram", "g": "gram", "mg": "miligram", "ton": "ton",
    "lt": "litre", "l": "litre", "ml": "mililitre",
    "m²": "metrekare", "m2": "metrekare", "km²": "kilometrekare", "m³": "metreküp",
    "sn": "saniye", "dk": "dakika", "sa": "saat",
    "km/s": "kilometre saat", "km/sa": "kilometre saat",
    "GB": "gigabayt", "MB": "megabayt", "KB": "kilobayt", "TB": "terabayt",
    "°C": "derece", "°": "derece",
    "TL": "lira", "₺": "lira", "$": "dolar", "€": "avro", "£": "sterlin",
    "USD": "dolar", "EUR": "avro",
}

LETTERS = {
    "A": "a", "B": "be", "C": "ce", "Ç": "çe", "D": "de", "E": "e", "F": "fe", "G": "ge", "Ğ": "yumuşak ge",
    "H": "he", "I": "ı", "İ": "i", "J": "je", "K": "ke", "L": "le", "M": "me", "N": "ne", "O": "o",
    "Ö": "ö", "P": "pe", "R": "re", "S": "se", "Ş": "şe", "T": "te", "U": "u", "Ü": "ü", "V": "ve",
    "Y": "ye", "Z": "ze", "Q": "kü", "W": "çift ve", "X": "iks",
}

# Yaygın yabancı kelimelerin okunuşu (kullanıcı sözlüğü bunları geçersiz kılabilir)
DEFAULT_LEXICON = {
    "WhatsApp": "vatsap", "YouTube": "yutub", "Google": "gugıl", "Facebook": "feysbuk",
    "Instagram": "instagram", "Twitter": "tivitır", "LinkedIn": "linkedin", "iPhone": "ayfon",
    "iPad": "ayped", "Excel": "eksel", "PowerPoint": "pavırpoynt", "Word": "vörd", "Zoom": "zum",
    "Teams": "tims", "Microsoft": "maykrosoft", "Windows": "vindovs", "Apple": "epıl", "online": "onlayn",
    "e-posta": "e posta", "e-mail": "imeyl", "email": "imeyl", "web": "veb", "site": "sayt",
    "check-in": "çekin", "feedback": "fidbek", "deadline": "dedlayn", "meeting": "miting",
}
# "site" Türkçede de kelime (site = yerleşke); varsayılanda dokunma:
DEFAULT_LEXICON.pop("site")


def parse_lexicon(text: str) -> dict[str, str]:
    """'yazılış = okunuş' satırlarını sözlüğe çevirir (=, →, -> ve : ayraçları kabul edilir)."""
    out: dict[str, str] = {}
    for line in (text or "").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        m = re.match(r"^(.+?)\s*(?:=|→|->|:)\s*(.+)$", line)
        if m and m.group(1).strip() and m.group(2).strip():
            out[m.group(1).strip()] = m.group(2).strip()
    return out


def _apply_lexicon(t: str, lex: dict[str, str]) -> str:
    # uzun anahtarlar önce; büyük/küçük harf duyarsız; ekleri korur (WhatsApp'tan → vatsaptan)
    for key in sorted(lex, key=len, reverse=True):
        val = lex[key]
        pat = re.compile(r"(?<![\wÇĞİÖŞÜçğıöşü])" + re.escape(key)
                         + r"(?:['’](?=[a-zçğıöşü])|(?![\wÇĞİÖŞÜçğıöşü]))", re.IGNORECASE)
        t = pat.sub(lambda m, v=val: v, t)
    return t


def tr_upper(s: str) -> str:
    return s.replace("i", "İ").replace("ı", "I").upper()


def tr_lower(s: str) -> str:
    return s.replace("I", "ı").replace("İ", "i").lower()


# ------------------------------------------------------------------ kısaltma (büyük harf) okuma

_CONS = set("BCÇDFGĞHJKLMNPRSŞTVYZQWX")


def _spell(acr: str) -> bool:
    """Harf harf mi okunmalı? (TBMM, ABD, AKP evet; NATO, YÖK, ODTÜ, TÜBİTAK hayır)."""
    if len(acr) <= 2:
        return True
    if not any(ch not in _CONS for ch in acr):
        return True
    run = 0
    for ch in acr:
        run = run + 1 if ch in _CONS else 0
        if run >= 3:
            return True
    if acr[0] in _CONS and acr[1] in _CONS:
        return True
    if acr[-1] in _CONS and acr[-2] in _CONS:
        return True
    return False


_ACR_RE = re.compile(r"(?<![\wÇĞİÖŞÜçğıöşü])([A-ZÇĞİÖŞÜQWX]{2,7})(?:['’]([a-zçğıöşü]+))?(?![\wÇĞİÖŞÜçğıöşü])")


def _acronyms(t: str) -> str:
    def one(m):
        acr, suf = m.group(1), m.group(2) or ""
        if acr in UNITS:            # GB, MB, TL… birim olarak ayrıca ele alınır
            return m.group(0)
        if _spell(acr):
            spoken = " ".join(LETTERS.get(ch, ch.lower()) for ch in acr)
        else:
            spoken = tr_lower(acr)
        return spoken + suf

    def shouty(m):
        # Tamamı büyük harfli satırda (başlık) yalnızca gerçek kısaltmaları harf harf oku: "YAPAY ZEKA VE TBMM"
        acr, suf = m.group(1), m.group(2) or ""
        if acr in UNITS:
            return m.group(0)
        if len(acr) >= 3 and _spell(acr):
            return " ".join(LETTERS.get(ch, ch.lower()) for ch in acr) + suf
        return tr_lower(acr) + suf

    out_lines = []
    for line in t.split("\n"):
        letters = [ch for ch in line if ch.isalpha()]
        caps = letters and sum(ch.isupper() for ch in letters) / len(letters) > 0.8 and len(line.split()) > 2
        out_lines.append(_ACR_RE.sub(shouty if caps else one, line))
    return "\n".join(out_lines)


# ------------------------------------------------------------------ Roma rakamları

_ROMAN = {"I": 1, "V": 5, "X": 10, "L": 50, "C": 100, "D": 500, "M": 1000}


def roman_to_int(s: str) -> Optional[int]:
    if not s or any(ch not in _ROMAN for ch in s):
        return None
    total, prev = 0, 0
    for ch in reversed(s):
        v = _ROMAN[ch]
        total = total - v if v < prev else total + v
        prev = max(prev, v)
    # yalnızca geçerli (kanonik) yazımları kabul et
    return total if 0 < total < 4000 and int_to_roman(total) == s else None


def int_to_roman(n: int) -> str:
    vals = [(1000, "M"), (900, "CM"), (500, "D"), (400, "CD"), (100, "C"), (90, "XC"), (50, "L"),
            (40, "XL"), (10, "X"), (9, "IX"), (5, "V"), (4, "IV"), (1, "I")]
    out = ""
    for v, r in vals:
        while n >= v:
            out += r
            n -= v
    return out


# ------------------------------------------------------------------ ana işlev

_NUM = r"\d{1,3}(?:\.\d{3})+|\d+"          # 1.250.000 ya da 1250
_SUFFIX = r"(?:['’]([a-zçğıöşü]+))?"


def _join_suffix(words: str, suf: Optional[str]) -> str:
    return words + (suf or "")


def normalize(text: str, lexicon: Optional[dict[str, str]] = None, use_default_lexicon: bool = True) -> str:
    t = text
    lex: dict[str, str] = {}
    if use_default_lexicon:
        lex.update(DEFAULT_LEXICON)
    if lexicon:
        lex.update(lexicon)
    if lex:
        t = _apply_lexicon(t, lex)

    for pat, rep in ABBREVIATIONS:
        t = re.sub(pat, rep, t)

    # Tarih: 27.10.2026 / 27/10/2026 / 27-10-2026
    def date(m):
        d, mo, y = int(m.group(1)), int(m.group(2)), m.group(3)
        if not (1 <= d <= 31 and 1 <= mo <= 12):
            return m.group(0)
        yy = int(y) + (2000 if len(y) == 2 else 0)
        return _join_suffix(f"{number_words(d)} {MONTHS[mo]} {number_words(yy)}", m.group(4))
    t = re.sub(r"\b(\d{1,2})[./-](\d{1,2})[./-](\d{4}|\d{2})\b" + _SUFFIX, date, t)

    # Saat: 14:30, saat 14.30, 09:05'te
    def clock(m):
        h, mi = int(m.group(1)), int(m.group(2))
        if h > 24 or mi > 59:
            return m.group(0)
        s = number_words(h) + (" " + ("sıfır " + number_words(mi) if 0 < mi < 10 else number_words(mi)) if mi else "")
        return _join_suffix(s, m.group(3))
    t = re.sub(r"\b(\d{1,2}):(\d{2})\b" + _SUFFIX, clock, t)
    t = re.sub(r"(?i)(?<=saat )(\d{1,2})\.(\d{2})\b" + _SUFFIX, clock, t)

    # Yüzde: %15, % 15,5, %15'i
    def percent(m):
        num = decimal_words(m.group(1), m.group(2)) if m.group(2) else number_words(_int(m.group(1)))
        return _join_suffix("yüzde " + num, m.group(3))
    t = re.sub(r"%\s?(" + _NUM + r")(?:,(\d+))?" + _SUFFIX, percent, t)

    # Para birimi önce: $5, €20, ₺100
    def cur_before(m):
        return number_words(_int(m.group(2))) + " " + UNITS[m.group(1)] + (m.group(3) and "" or "")
    t = re.sub(r"([$€£₺])\s?(" + _NUM + r")()", cur_before, t)

    # Sıra sayısı: "3. sınıf", "21. yüzyıl", "1.'si"
    def ordinal(m):
        return _join_suffix(ordinal_words(_int(m.group(1))), m.group(2))
    t = re.sub(r"(?<![\d.,])(\d{1,4})\.(?:['’]([a-zçğıöşü]+))?(?=\s+[a-zçğıöşü(])", ordinal, t)
    t = re.sub(r"(?<![\d.,])(\d{1,4})\.['’]([a-zçğıöşü]+)", ordinal, t)

    # Roma rakamları: "II. Dünya Savaşı", "XIX. yüzyıl", "Mehmed II"
    def roman_ord(m):
        n = roman_to_int(m.group(1))
        return _join_suffix(ordinal_words(n), m.group(2)) if n else m.group(0)
    t = re.sub(r"(?<![\wÇĞİÖŞÜ])([IVXLCDM]{1,7})\.(?:['’]([a-zçğıöşü]+))?(?=\s)", roman_ord, t)
    t = re.sub(r"(?<=[a-zçğıöşü] )([IVXLC]{2,6})(?:['’]([a-zçğıöşü]+))?(?![\wÇĞİÖŞÜ])",
               lambda m: (_join_suffix(ordinal_words(roman_to_int(m.group(1))), m.group(2))
                          if roman_to_int(m.group(1)) and m.group(1) not in ("CD", "DC", "MC", "CL", "LC") else m.group(0)),
               t)

    # Sayı aralığı: 2020-2024 → "iki bin yirmi, iki bin yirmi dört"
    t = re.sub(r"(\d)\s?[-–]\s?(\d)", r"\1 ile \2", t)

    # Sayı + birim: 5 km, 250 TL, 3,5 GB, 20 °C, 100$
    unit_keys = sorted(UNITS, key=len, reverse=True)
    unit_re = "|".join(re.escape(u) for u in unit_keys)

    def num_unit(m):
        num = decimal_words(m.group(1), m.group(2)) if m.group(2) else number_words(_int(m.group(1)))
        return _join_suffix(num + " " + UNITS[m.group(3)], m.group(4))
    t = re.sub(r"(?<![\d.,])(" + _NUM + r")(?:,(\d+))?\s?(" + unit_re + r")" + _SUFFIX + r"(?![\wçğıöşü²³/])",
               num_unit, t)
    t = re.sub(r"\bTL\b", "lira", t)

    # Bölme / oran: 3/5
    t = re.sub(r"(\d)\s*/\s*(\d)", r"\1 bölü \2", t)

    # Ondalık: 3,5 · 0,25
    def dec(m):
        return _join_suffix(decimal_words(m.group(1), m.group(2)), m.group(3))
    t = re.sub(r"(?<![\d.])(" + _NUM + r"),(\d+)" + _SUFFIX + r"(?!\d)", dec, t)

    # Telefon / uzun numaralar: 0532 123 45 67 → rakam grupları
    def digits(m):
        return " ".join(number_words(int(g)) if not g.startswith("0") or len(g) == 1 else
                        " ".join(_DIGITS[int(c)] for c in g) for g in m.group(0).split())
    t = re.sub(r"\b0\d{3}\s\d{3}\s\d{2}\s\d{2}\b", digits, t)

    # Kalan tam sayılar (ekleriyle): 2023'te → iki bin yirmi üçte
    def plain(m):
        return _join_suffix(number_words(_int(m.group(1))), m.group(2))
    t = re.sub(r"(?<!\d)(?<!\d,)(?<!\d\.)(" + _NUM + r")" + _SUFFIX + r"(?!\d)(?!,\d)(?!\.\d)", plain, t)

    # Büyük harfli kısaltmalar: TBMM → te be me me, NATO → nato
    t = _acronyms(t)

    # Semboller
    t = t.replace("&", " ve ").replace("+", " artı ").replace("=", " eşittir ").replace("@", " et ")
    t = re.sub(r"[ \t]+", " ", t)
    # Cümle başlarını büyük harf yap (cümle bölme ve tonlama için): "iki bin…" → "İki bin…"
    t = re.sub(r"(^|[.!?…]\s+|\n)([a-zçğıöşü])", lambda m: m.group(1) + tr_upper(m.group(2)), t.strip())
    return t


def explain(text: str, lexicon: Optional[dict[str, str]] = None) -> list[tuple[str, str]]:
    """Değişen satırları (önce, sonra) olarak döndürür; arayüzde 'nasıl okunacak' önizlemesi için."""
    out = []
    for line in text.splitlines():
        n = normalize(line, lexicon)
        if n != line.strip():
            out.append((line.strip(), n))
    return out


__all__: Iterable[str] = ["normalize", "number_words", "ordinal_words", "parse_lexicon", "explain",
                          "DEFAULT_LEXICON"]
