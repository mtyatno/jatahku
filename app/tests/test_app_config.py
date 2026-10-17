"""Paket mobile 1.3: header X-Jatahku-Client, GET /app/config, POST /app/errors.

Run: python -m unittest app.tests.test_app_config -v
"""
import os
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost:5432/test")
os.environ.setdefault("JWT_SECRET", "test-secret")

import json
import unittest
from unittest.mock import AsyncMock, MagicMock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.routes import app_config as route
from app.core.client import UNKNOWN, ClientInfo, is_older, parse_client, version_tuple
from app.core.database import get_db
from app.services.app_config import FEATURES, build_config, parse_overrides
from app.tests.fakes import FakeResult


class ParseClientTests(unittest.TestCase):
    def test_full_header(self):
        self.assertEqual(parse_client("android/1.2.0/37"), ClientInfo("android", "1.2.0", "37"))
        self.assertEqual(parse_client("web/0.1.0/46a22cc"), ClientInfo("web", "0.1.0", "46a22cc"))
        self.assertEqual(parse_client(" IOS/1.0/5 "), ClientInfo("ios", "1.0", "5"))

    def test_partial_header(self):
        self.assertEqual(parse_client("ios"), ClientInfo("ios"))
        self.assertEqual(parse_client("android/1.2.0"), ClientInfo("android", "1.2.0"))

    def test_garbage_never_raises(self):
        for value in (None, "", "windows/1.0/1", "x" * 200, "////", "web/abc/!!"):
            info = parse_client(value)
            self.assertIn(info.platform, ("unknown", "web"))
        self.assertEqual(parse_client("web/abc/!!"), ClientInfo("web"))
        self.assertIs(parse_client("desktop/1/1"), UNKNOWN)

    def test_versions(self):
        self.assertEqual(version_tuple("1.2"), (1, 2, 0))
        self.assertIsNone(version_tuple("1.x"))
        self.assertTrue(is_older("1.2.0", "1.10.0"))  # numerik, bukan teks
        self.assertFalse(is_older("1.10.0", "1.2.0"))
        self.assertFalse(is_older("1.2", "1.2.0"))
        # Versi tak terbaca atau tanpa batas tidak pernah mengunci user.
        self.assertFalse(is_older(None, "9.0.0"))
        self.assertFalse(is_older("1.0.0", None))


class BuildConfigTests(unittest.TestCase):
    def test_web_today(self):
        cfg = build_config(ClientInfo("web", "0.1.0", "abc"))
        self.assertEqual(cfg["config_version"], 1)
        self.assertEqual(cfg["sales_mode"], "web")
        self.assertEqual(cfg["update"]["status"], "ok")
        self.assertEqual(cfg["features"], FEATURES)
        self.assertTrue(cfg["links"]["privacy"].startswith("https://"))

    def test_unknown_client_behaves_like_web(self):
        cfg = build_config(UNKNOWN)
        self.assertEqual(cfg["client"]["platform"], "unknown")
        self.assertEqual(cfg["sales_mode"], "web")
        self.assertEqual(cfg["update"]["status"], "ok")

    def test_native_defaults_have_no_sales(self):
        for platform in ("android", "ios"):
            self.assertEqual(build_config(ClientInfo(platform, "1.0.0", "1"))["sales_mode"], "none")

    def test_min_and_latest_version(self):
        overrides = {"platforms": {"android": {"min_supported_version": "1.2.0", "latest_version": "1.4.0"}}}
        status = lambda v: build_config(ClientInfo("android", v, "1"), overrides)["update"]["status"]
        self.assertEqual(status("1.1.9"), "required")
        self.assertEqual(status("1.3.0"), "recommended")
        self.assertEqual(status("1.4.0"), "ok")
        self.assertEqual(status(None), "ok")
        # Batas Android tidak menyentuh iOS maupun web.
        self.assertEqual(build_config(ClientInfo("ios", "1.0.0"), overrides)["update"]["status"], "ok")
        self.assertEqual(build_config(ClientInfo("web", "0.1.0"), overrides)["update"]["status"], "ok")
        cfg = build_config(ClientInfo("web", "0.1.0"), overrides)
        self.assertEqual(cfg["versions"]["android"]["min_supported"], "1.2.0")

    def test_feature_overrides(self):
        overrides = {"features": {"receipt_inbox": {"web": True}, "push": True, "baru": {"ios": True}}}
        web = build_config(ClientInfo("web"), overrides)["features"]
        android = build_config(ClientInfo("android"), overrides)["features"]
        self.assertTrue(web["receipt_inbox"])
        self.assertFalse(android["receipt_inbox"])
        self.assertTrue(android["push"])
        self.assertNotIn("baru", android)  # flag tanpa nilai untuk platform ini tidak muncul

    def test_invalid_sales_mode_falls_back(self):
        overrides = {"platforms": {"ios": {"sales_mode": "gratis"}}}
        self.assertEqual(build_config(ClientInfo("ios"), overrides)["sales_mode"], "none")

    def test_ota_slot(self):
        overrides = {"platforms": {"android": {"ota": {"channel": "stable", "bundle_version": "5"}}}}
        ota = build_config(ClientInfo("android"), overrides)["ota"]
        self.assertEqual(ota["channel"], "stable")
        self.assertIsNone(ota["bundle_url"])

    def test_defaults_not_mutated(self):
        build_config(ClientInfo("android"), {"platforms": {"android": {"sales_mode": "store"}}})
        self.assertEqual(build_config(ClientInfo("android"))["sales_mode"], "none")

    def test_parse_overrides(self):
        self.assertEqual(parse_overrides(None), {})
        self.assertEqual(parse_overrides("{bukan json"), {})
        self.assertEqual(parse_overrides("[1, 2]"), {})
        self.assertEqual(parse_overrides('{"features": {"push": true}}'), {"features": {"push": True}})


class EndpointTests(unittest.TestCase):
    def client(self, setting=None, db_error=False):
        app = FastAPI()
        app.state.limiter = route.limiter
        app.include_router(route.router, prefix="/app")

        async def fake_db():
            db = MagicMock()
            if db_error:
                db.execute = AsyncMock(side_effect=RuntimeError("db down"))
            else:
                db.execute = AsyncMock(return_value=FakeResult(setting))
            yield db

        app.dependency_overrides[get_db] = fake_db
        return TestClient(app)

    def test_config_reads_header(self):
        res = self.client().get("/app/config", headers={"X-Jatahku-Client": "android/1.0.0/3"})
        self.assertEqual(res.status_code, 200)
        body = res.json()
        self.assertEqual(body["client"], {"platform": "android", "version": "1.0.0", "build": "3"})
        self.assertEqual(body["sales_mode"], "none")
        self.assertIn("max-age", res.headers["cache-control"])
        self.assertEqual(res.headers["vary"], "X-Jatahku-Client")

    def test_config_without_header(self):
        body = self.client().get("/app/config").json()
        self.assertEqual(body["sales_mode"], "web")

    def test_config_uses_app_setting(self):
        setting = json.dumps({"platforms": {"android": {"min_supported_version": "2.0.0"}}})
        body = self.client(setting).get(
            "/app/config", headers={"X-Jatahku-Client": "android/1.9.0/1"}).json()
        self.assertEqual(body["update"]["status"], "required")

    def test_config_survives_db_failure(self):
        res = self.client(db_error=True).get("/app/config")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()["sales_mode"], "web")

    def test_error_report_logs_path_only(self):
        with self.assertLogs("jatahku.client_errors", level="WARNING") as logs:
            res = self.client().post(
                "/app/errors",
                json={"message": "Boom", "url": "https://jatahku.com/auth/tg?token=RAHASIA", "kind": "error"},
                headers={"X-Jatahku-Client": "web/0.1.0/abc"},
            )
        self.assertEqual(res.status_code, 204)
        line = "\n".join(logs.output)
        self.assertIn("platform=web", line)
        self.assertIn("path=/auth/tg", line)
        self.assertNotIn("RAHASIA", line)

    def test_error_report_validates(self):
        self.assertEqual(self.client().post("/app/errors", json={}).status_code, 422)
        self.assertEqual(self.client().post("/app/errors", json={"message": "x" * 3000}).status_code, 422)


if __name__ == "__main__":
    unittest.main()
