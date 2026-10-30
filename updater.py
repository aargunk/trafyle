"""Yeni sürüm denetimi.

GitHub'daki son sürümün numarasını sorar (https://api.github.com/repos/<depo>/releases/latest).
Gönderilen tek şey bu istektir; hiçbir dosya, metin ya da kişisel bilgi gönderilmez.
Kullanıcı Hakkında penceresinden kapatabilir.
"""
from __future__ import annotations

import json
import re
import ssl
import urllib.request
from typing import Optional

COPYRIGHT = "Argun Karacabey"
GITHUB_REPO = "aargunk/trafyle"
RELEASES_URL = f"https://github.com/{GITHUB_REPO}/releases/latest"
PROJECT_URL = f"https://github.com/{GITHUB_REPO}"
SITE_URL = f"https://{GITHUB_REPO.split('/')[0].lower()}.github.io/{GITHUB_REPO.split('/')[1]}/"
CHECK_INTERVAL = 24 * 3600   # günde en fazla bir kez


def parse_version(v: str) -> tuple:
    nums = re.findall(r"\d+", v or "")
    return tuple(int(n) for n in nums[:3]) + (0,) * (3 - len(nums[:3]))


def is_newer(latest: str, current: str) -> bool:
    return parse_version(latest) > parse_version(current)


def _ctx():
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except Exception:  # noqa: BLE001
        return ssl.create_default_context()


def latest_release(timeout: int = 10) -> Optional[dict]:
    """{"version": "3.4.0", "url": "...", "notes": "..."} ya da sürüm yoksa/erişilemezse None."""
    req = urllib.request.Request(f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest",
                                 headers={"Accept": "application/vnd.github+json", "User-Agent": "Trafyle"})
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=_ctx()) as r:
            j = json.loads(r.read().decode("utf-8"))
    except Exception:  # noqa: BLE001
        return None
    tag = j.get("tag_name") or ""
    if not tag or j.get("draft") or j.get("prerelease"):
        return None
    return {"version": tag.lstrip("vV"), "url": j.get("html_url") or RELEASES_URL,
            "notes": (j.get("body") or "").strip()}
