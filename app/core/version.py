"""Versi kode yang sedang berjalan — dibaca SEKALI saat proses start.

`/health` melaporkan `COMMIT`, jadi deploy bisa memastikan proses API yang
melayani benar-benar menjalankan commit yang baru di-pull (bukan sekadar
"API menjawab 200"). Karena dibaca saat import, nilainya tetap commit yang
dimuat proses ini walau `git pull` berikutnya sudah mengubah isi folder.

Urutan sumber: env `JATAHKU_COMMIT` → isi `.git` di root repo (dibaca langsung,
tanpa menjalankan git) → "unknown".
"""
from __future__ import annotations

import os
import re
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
_SHA = re.compile(r"^[0-9a-f]{40}$")


def _sha(value: str) -> str | None:
    value = value.strip()
    return value if _SHA.match(value) else None


def read_git_commit(root: Path) -> str | None:
    """Commit HEAD dari folder `.git` di `root`; None bila tidak terbaca."""
    git = root / ".git"
    try:
        head = (git / "HEAD").read_text().strip()
        if not head.startswith("ref:"):
            return _sha(head)  # detached HEAD
        ref = head.split(":", 1)[1].strip()
        ref_file = git / ref
        if ref_file.is_file():
            return _sha(ref_file.read_text())
        packed = git / "packed-refs"
        if packed.is_file():
            for line in packed.read_text().splitlines():
                parts = line.split()
                if len(parts) == 2 and parts[1] == ref:
                    return _sha(parts[0])
    except (OSError, UnicodeDecodeError):
        return None
    return None


COMMIT: str = (
    _sha(os.environ.get("JATAHKU_COMMIT", "")) or read_git_commit(REPO_ROOT) or "unknown"
)
STARTED_AT: datetime = datetime.now(timezone.utc)
