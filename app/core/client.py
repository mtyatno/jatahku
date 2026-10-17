"""Identitas klien dari header `X-Jatahku-Client: <platform>/<versi>/<build>`.

ADR-M9 + aturan mobile #3 (AGENTS.md): server mengubah perilaku hanya
berdasarkan header ini, tidak pernah menebak dari user agent atau origin.
Header kosong/rusak = klien `unknown` (web lama, bot, skrip) dan diperlakukan
seperti web hari ini.

Contoh: `web/0.1.0/46a22cc`, `android/1.2.0/37`, `ios/1.2.0/41`.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from fastapi import Request

HEADER = "X-Jatahku-Client"
PLATFORMS = ("web", "android", "ios")

_VERSION = re.compile(r"^\d{1,4}(?:\.\d{1,4}){0,2}$")
_BUILD = re.compile(r"^[0-9A-Za-z._-]{1,40}$")


@dataclass(frozen=True)
class ClientInfo:
    platform: str  # web | android | ios | unknown
    version: str | None = None
    build: str | None = None

    @property
    def is_native(self) -> bool:
        return self.platform in ("android", "ios")


UNKNOWN = ClientInfo("unknown")


def parse_client(value: str | None) -> ClientInfo:
    """Header → ClientInfo. Tidak pernah melempar; isi yang tidak dikenal → UNKNOWN."""
    if not value or len(value) > 100:
        return UNKNOWN
    parts = value.strip().split("/")
    platform = parts[0].strip().lower()
    if platform not in PLATFORMS:
        return UNKNOWN
    version = parts[1].strip() if len(parts) > 1 else ""
    build = parts[2].strip() if len(parts) > 2 else ""
    return ClientInfo(
        platform=platform,
        version=version if _VERSION.match(version) else None,
        build=build if _BUILD.match(build) else None,
    )


def client_of(request: Request) -> ClientInfo:
    return parse_client(request.headers.get(HEADER))


def version_tuple(version: str | None) -> tuple[int, int, int] | None:
    """'1.2' → (1, 2, 0). None/rusak → None."""
    if not version or not _VERSION.match(version):
        return None
    nums = [int(p) for p in version.split(".")]
    return tuple((nums + [0, 0])[:3])  # type: ignore[return-value]


def is_older(version: str | None, than: str | None) -> bool:
    """True bila `version` jelas lebih lama dari `than`. Versi tak terbaca → False
    (jangan pernah mengunci user karena header rusak)."""
    a, b = version_tuple(version), version_tuple(than)
    return a is not None and b is not None and a < b
