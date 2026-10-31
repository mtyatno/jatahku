#!/usr/bin/env bash
# Cek migrasi Alembic di PostgreSQL, meniru keadaan produksi.
#
# Database produksi tidak bisa dibangun dari migrasi saja: sebagian tabel dibuat
# create_all saat start (main.py), dan migrasi awal hanya membuat 11 tabel.
# Karena itu skema awal dibuat dari model di cabang dasar (create_all + stamp),
# lalu migrasi baru dari PR dijalankan di atasnya:
#   1. upgrade head          -> migrasi baru bisa jalan di skema produksi
#   2. tepat satu head       -> deploy.sh berhenti bila current != heads
#   3. alembic check         -> model PR == skema hasil migrasi (kolom baru
#                               tanpa migrasi tidak lolos, karena create_all
#                               tidak menambah kolom ke tabel yang sudah ada)
#   4. downgrade ke head dasar lalu upgrade lagi -> migrasi bisa dibatalkan
#
# Pakai: DATABASE_URL=postgresql+asyncpg://... JWT_SECRET=... \
#        .github/scripts/cek-migrasi.sh <ref dasar, mis. origin/main atau SHA>
# Database harus kosong. Lihat docs/plugin/03-workflow.md (Cara kerja, Migrasi).
set -euo pipefail

BASE_REF="${1:?pakai: cek-migrasi.sh <ref dasar>}"
ROOT="$(git rev-parse --show-toplevel)"
BASE_DIR="$(mktemp -d)"
git -C "$ROOT" worktree add --detach "$BASE_DIR" "$BASE_REF" >/dev/null 2>&1
trap 'git -C "$ROOT" worktree remove --force "$BASE_DIR" >/dev/null 2>&1 || true' EXIT

echo "== Skema dasar: create_all dari model $BASE_REF"
(
  cd "$BASE_DIR"
  python - <<'PY'
from sqlalchemy import create_engine
from app.core.config import get_settings
from app.core.database import Base
import app.models.models  # noqa: F401  (mendaftarkan semua model)

engine = create_engine(get_settings().DATABASE_URL.replace("+asyncpg", ""))
Base.metadata.create_all(engine)
engine.dispose()
PY
  alembic stamp head >/dev/null
)
BASE_HEAD="$(cd "$BASE_DIR" && alembic heads | awk '{print $1}')"
echo "   head dasar: $BASE_HEAD"

cd "$ROOT"
HEADS="$(alembic heads | grep -c .)"
if [ "$HEADS" != "1" ]; then
  echo "GAGAL: ada $HEADS head Alembic; deploy.sh butuh tepat satu."
  alembic heads
  exit 1
fi

echo "== Migrasi baru: upgrade head"
alembic upgrade head
echo "== Model == skema: alembic check"
alembic check
echo "== Batalkan ke $BASE_HEAD, lalu naikkan lagi"
alembic downgrade "$BASE_HEAD"
alembic upgrade head
echo "OK: migrasi naik-turun dan model cocok dengan skema."
