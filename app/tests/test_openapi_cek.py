"""Mobile 1.4 — cek perubahan API yang memutus (`app/scripts/openapi_cek.py`, ADR-M9).

Run: python -m unittest app.tests.test_openapi_cek -v
"""
import copy
import os
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost:5432/test")
os.environ.setdefault("JWT_SECRET", "test-secret")

import unittest

from app.scripts.openapi_cek import bandingkan


def _doc():
    """OpenAPI kecil bergaya FastAPI: $ref, anyOf untuk Optional, list, enum."""
    return {
        "openapi": "3.1.0",
        "paths": {
            "/envelopes/": {
                "get": {
                    "parameters": [
                        {"in": "query", "name": "aktif", "required": False, "schema": {"type": "boolean"}},
                    ],
                    "responses": {"200": {"content": {"application/json": {"schema": {
                        "type": "array", "items": {"$ref": "#/components/schemas/Amplop"}}}}}},
                },
                "post": {
                    "requestBody": {"required": True, "content": {"application/json": {
                        "schema": {"$ref": "#/components/schemas/AmplopBaru"}}}},
                    "responses": {"201": {"content": {"application/json": {
                        "schema": {"$ref": "#/components/schemas/Amplop"}}}}},
                },
            },
            "/health": {"get": {"responses": {"200": {"content": {"application/json": {"schema": {}}}}}}},
        },
        "components": {"schemas": {
            "Amplop": {
                "type": "object",
                "required": ["id", "name", "group_id", "jenis"],
                "properties": {
                    "id": {"type": "string", "format": "uuid"},
                    "name": {"type": "string"},
                    "budget": {"type": "number"},
                    "group_id": {"anyOf": [{"type": "string"}, {"type": "null"}]},
                    "jenis": {"$ref": "#/components/schemas/Jenis"},
                    "anak": {"type": "array", "items": {"$ref": "#/components/schemas/Amplop"}},
                },
            },
            "AmplopBaru": {
                "type": "object",
                "required": ["name"],
                "properties": {
                    "name": {"type": "string"},
                    "emoji": {"anyOf": [{"type": "string"}, {"type": "null"}]},
                    "jenis": {"$ref": "#/components/schemas/Jenis"},
                    "budget": {"type": "number"},
                },
            },
            "Jenis": {"type": "string", "enum": ["harian", "bulanan"]},
        }},
    }


def _cek(ubah):
    lama = _doc()
    baru = copy.deepcopy(lama)
    ubah(baru)
    return bandingkan(lama, baru)


def _s(doc):
    return doc["components"]["schemas"]


class TanpaPerubahanTests(unittest.TestCase):
    def test_sama_persis(self):
        p = _cek(lambda d: None)
        self.assertEqual(p.memutus, [])
        self.assertEqual(p.peringatan, [])


class AditifBolehTests(unittest.TestCase):
    """Perubahan yang hanya menambah tidak boleh menggagalkan CI."""

    def assertAman(self, ubah):
        p = _cek(ubah)
        self.assertEqual(p.memutus, [], p.memutus)

    def test_path_baru(self):
        self.assertAman(lambda d: d["paths"].__setitem__("/app/config", {"get": {"responses": {}}}))

    def test_method_baru(self):
        self.assertAman(lambda d: d["paths"]["/health"].__setitem__("post", {"responses": {}}))

    def test_field_respons_baru(self):
        self.assertAman(lambda d: _s(d)["Amplop"]["properties"].__setitem__("warna", {"type": "string"}))

    def test_field_request_opsional_baru(self):
        self.assertAman(lambda d: _s(d)["AmplopBaru"]["properties"].__setitem__("warna", {"type": "string"}))

    def test_parameter_opsional_baru(self):
        self.assertAman(lambda d: d["paths"]["/envelopes/"]["get"]["parameters"].append(
            {"in": "query", "name": "q", "required": False, "schema": {"type": "string"}}))

    def test_field_request_jadi_opsional(self):
        self.assertAman(lambda d: _s(d)["AmplopBaru"].__setitem__("required", []))

    def test_request_menerima_null(self):
        self.assertAman(lambda d: _s(d)["AmplopBaru"]["properties"].__setitem__(
            "budget", {"anyOf": [{"type": "number"}, {"type": "null"}]}))

    def test_respons_opsional_jadi_wajib(self):
        self.assertAman(lambda d: _s(d)["Amplop"]["required"].append("budget"))

    def test_respons_tidak_lagi_null(self):
        self.assertAman(lambda d: _s(d)["Amplop"]["properties"].__setitem__("group_id", {"type": "string"}))

    def test_skema_respons_kosong_jadi_bertipe(self):
        self.assertAman(lambda d: d["paths"]["/health"]["get"]["responses"]["200"]["content"][
            "application/json"].__setitem__("schema", {"type": "object", "properties": {"ok": {"type": "boolean"}}}))

    def test_request_integer_jadi_number(self):
        lama = _doc()
        _s(lama)["AmplopBaru"]["properties"]["budget"] = {"type": "integer"}
        baru = _doc()
        self.assertEqual(bandingkan(lama, baru).memutus, [])

    def test_ref_diganti_isi_yang_sama(self):
        def ubah(d):
            _s(d)["Amplop"]["properties"]["jenis"] = {"type": "string", "enum": ["harian", "bulanan"]}
        self.assertAman(ubah)


class MemutusGagalTests(unittest.TestCase):
    def assertMemutus(self, ubah, potongan):
        p = _cek(ubah)
        self.assertTrue(any(potongan in m for m in p.memutus), p.memutus)

    def test_path_dihapus(self):
        self.assertMemutus(lambda d: d["paths"].pop("/health"), "/health: path dihapus")

    def test_method_dihapus(self):
        self.assertMemutus(lambda d: d["paths"]["/envelopes/"].pop("post"), "POST /envelopes/: method dihapus")

    def test_field_respons_dihapus_di_semua_endpoint(self):
        p = _cek(lambda d: _s(d)["Amplop"]["properties"].pop("name"))
        self.assertIn("GET /envelopes/ → 200[]: field `name` dihapus", p.memutus)
        self.assertIn("POST /envelopes/ → 201: field `name` dihapus", p.memutus)

    def test_field_respons_bersarang_dihapus(self):
        # `anak` memakai skema rekursif; tidak boleh berputar tanpa henti.
        p = _cek(lambda d: _s(d)["Amplop"]["properties"].pop("budget"))
        self.assertIn("GET /envelopes/ → 200[]: field `budget` dihapus", p.memutus)

    def test_respons_wajib_jadi_opsional(self):
        self.assertMemutus(lambda d: _s(d)["Amplop"]["required"].remove("name"), "field `name` tidak lagi selalu ada")

    def test_respons_bisa_null(self):
        self.assertMemutus(lambda d: _s(d)["Amplop"]["properties"].__setitem__(
            "name", {"anyOf": [{"type": "string"}, {"type": "null"}]}), "tipe berubah string → null|string")

    def test_tipe_respons_berubah(self):
        self.assertMemutus(lambda d: _s(d)["Amplop"]["properties"].__setitem__("budget", {"type": "string"}),
                           ".budget: tipe berubah number → string")

    def test_kode_respons_2xx_hilang(self):
        def ubah(d):
            r = d["paths"]["/envelopes/"]["post"]["responses"]
            r["200"] = r.pop("201")
        self.assertMemutus(ubah, "POST /envelopes/: respons 201 hilang")

    def test_field_request_wajib_baru(self):
        def ubah(d):
            _s(d)["AmplopBaru"]["properties"]["warna"] = {"type": "string"}
            _s(d)["AmplopBaru"]["required"].append("warna")
        self.assertMemutus(ubah, "POST /envelopes/ body: field wajib baru `warna`")

    def test_field_request_jadi_wajib(self):
        self.assertMemutus(lambda d: _s(d)["AmplopBaru"]["required"].append("emoji"), "field `emoji` jadi wajib")

    def test_tipe_request_menyempit(self):
        self.assertMemutus(lambda d: _s(d)["AmplopBaru"]["properties"].__setitem__("emoji", {"type": "string"}),
                           "body.emoji: tipe menyempit null|string → string")

    def test_enum_request_berkurang(self):
        self.assertMemutus(lambda d: _s(d)["Jenis"].__setitem__("enum", ["harian"]),
                           'body.jenis: nilai enum tidak diterima lagi: "bulanan"')

    def test_parameter_wajib_baru(self):
        self.assertMemutus(lambda d: d["paths"]["/envelopes/"]["get"]["parameters"].append(
            {"in": "query", "name": "bulan", "required": True, "schema": {"type": "string"}}),
            "parameter wajib baru query `bulan`")

    def test_parameter_jadi_wajib(self):
        self.assertMemutus(lambda d: d["paths"]["/envelopes/"]["get"]["parameters"][0].__setitem__("required", True),
                           "parameter query `aktif` jadi wajib")

    def test_body_jadi_wajib(self):
        def ubah(d):
            d["paths"]["/health"]["get"]["requestBody"] = {"required": True, "content": {}}
        self.assertMemutus(ubah, "GET /health: body request jadi wajib")

    def test_content_type_request_hilang(self):
        def ubah(d):
            body = d["paths"]["/envelopes/"]["post"]["requestBody"]["content"]
            body["multipart/form-data"] = body.pop("application/json")
        self.assertMemutus(ubah, "body request application/json tidak diterima lagi")


class PeringatanTests(unittest.TestCase):
    def test_enum_respons_bertambah_hanya_peringatan(self):
        p = _cek(lambda d: _s(d)["Jenis"]["enum"].append("mingguan"))
        self.assertEqual(p.memutus, [])
        self.assertTrue(any('nilai enum baru: "mingguan"' in m for m in p.peringatan), p.peringatan)

    def test_response_model_dilepas_peringatan(self):
        def ubah(d):
            d["paths"]["/envelopes/"]["get"]["responses"]["200"]["content"]["application/json"]["schema"] = {}
        p = _cek(ubah)
        self.assertEqual(p.memutus, [])
        self.assertTrue(any("response_model dilepas" in m for m in p.peringatan), p.peringatan)


class SkemaAppTests(unittest.TestCase):
    def test_skema_app_dibandingkan_dengan_dirinya_bersih(self):
        from app.main import app
        doc = app.openapi()
        p = bandingkan(doc, copy.deepcopy(doc))
        self.assertEqual(p.memutus, [])
        self.assertEqual(p.peringatan, [])


if __name__ == "__main__":
    unittest.main()
