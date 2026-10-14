"""/health melaporkan commit yang sedang berjalan (app/core/version.py):
- commit dibaca dari .git: ref biasa, packed-refs, detached HEAD
- .git rusak/tidak ada → None (bukan crash)
- respons /health berisi commit + started_at dan tidak boleh di-cache

Run: python -m unittest app.tests.test_health_version -v
"""
import os
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost:5432/test")
os.environ.setdefault("JWT_SECRET", "test-secret")

import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.routes import health
from app.core import version
from app.core.database import get_db
from app.tests.fakes import FakeResult

SHA_A = "a" * 40
SHA_B = "0123456789abcdef0123456789abcdef01234567"


class ReadGitCommitTests(unittest.TestCase):
    def repo(self, files: dict) -> Path:
        root = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: __import__("shutil").rmtree(root, ignore_errors=True))
        for rel, content in files.items():
            path = root / ".git" / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content)
        return root

    def test_branch_ref(self):
        root = self.repo({"HEAD": "ref: refs/heads/main\n", "refs/heads/main": SHA_A + "\n"})
        self.assertEqual(version.read_git_commit(root), SHA_A)

    def test_packed_refs_after_gc(self):
        root = self.repo({
            "HEAD": "ref: refs/heads/main\n",
            "packed-refs": f"# pack-refs with: peeled fully-peeled sorted\n{SHA_B} refs/heads/main\n^{SHA_A}\n",
        })
        self.assertEqual(version.read_git_commit(root), SHA_B)

    def test_detached_head(self):
        root = self.repo({"HEAD": SHA_B + "\n"})
        self.assertEqual(version.read_git_commit(root), SHA_B)

    def test_missing_or_garbage_is_none(self):
        self.assertIsNone(version.read_git_commit(Path(tempfile.mkdtemp())))
        root = self.repo({"HEAD": "ref: refs/heads/main\n", "refs/heads/main": "bukan-sha\n"})
        self.assertIsNone(version.read_git_commit(root))
        root = self.repo({"HEAD": "ref: refs/heads/hilang\n"})
        self.assertIsNone(version.read_git_commit(root))

    def test_this_checkout_reports_a_commit(self):
        # Repo ini sendiri: proses yang berjalan dari checkout git tahu commit-nya.
        if (version.REPO_ROOT / ".git").is_dir():
            self.assertRegex(version.read_git_commit(version.REPO_ROOT) or "", r"^[0-9a-f]{40}$")


class HealthEndpointTests(unittest.TestCase):
    def client(self, db_ok=True, redis_ok=True):
        app = FastAPI()
        app.include_router(health.router)

        async def fake_db():
            db = MagicMock()
            if db_ok:
                db.execute = AsyncMock(return_value=FakeResult(1))
            else:
                db.execute = AsyncMock(side_effect=RuntimeError("db down"))
            yield db

        app.dependency_overrides[get_db] = fake_db
        redis = MagicMock()
        redis.ping = AsyncMock(return_value=True) if redis_ok else AsyncMock(side_effect=RuntimeError("x"))
        redis.close = AsyncMock()
        p = patch.object(health.aioredis, "from_url", return_value=redis)
        p.start()
        self.addCleanup(p.stop)
        return TestClient(app)

    def test_reports_running_commit_and_is_not_cacheable(self):
        with patch.object(health, "COMMIT", SHA_B):
            res = self.client().get("/health")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.headers["cache-control"], "no-store")
        body = res.json()
        self.assertEqual(body["status"], "healthy")
        self.assertEqual(body["commit"], SHA_B)
        self.assertIn("started_at", body)
        self.assertGreaterEqual(body["uptime_s"], 0)

    def test_degraded_still_reports_commit(self):
        with patch.object(health, "COMMIT", SHA_B):
            body = self.client(redis_ok=False).get("/health").json()
        self.assertEqual(body["status"], "degraded")
        self.assertEqual(body["commit"], SHA_B)


if __name__ == "__main__":
    unittest.main()
