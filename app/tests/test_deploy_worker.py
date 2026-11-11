"""Unit systemd worker email laporan dan langkahnya di deploy.sh (uji teks/urutan)."""
import subprocess
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
UNIT = REPO / "deploy" / "jatahku-worker.service"
DEPLOY = REPO / "deploy.sh"


class UnitWorkerTest(unittest.TestCase):
    def setUp(self):
        self.lines = UNIT.read_text().splitlines()

    def test_baris_unit(self):
        for baris in [
            "[Unit]", "[Service]", "[Install]",
            "Description=Jatahku worker email laporan",
            "After=network.target postgresql.service redis-server.service",
            "User=jatahku",
            "WorkingDirectory=/opt/jatahku/app",
            "ExecStart=/opt/jatahku/venv/bin/python -m app.services.laporan.worker_email",
            "Restart=always", "RestartSec=5", "Nice=5", "TimeoutStopSec=60",
            "WantedBy=multi-user.target",
        ]:
            self.assertIn(baris, self.lines)

    def test_tanpa_environment_file(self):
        self.assertFalse(any(l.startswith("EnvironmentFile") for l in self.lines))

    def test_komentar_kepala(self):
        self.assertTrue(self.lines[0].startswith("#"))
        self.assertIn("deploy.sh", "\n".join(l for l in self.lines if l.startswith("#")))


class DeployWorkerTest(unittest.TestCase):
    def setUp(self):
        self.src = DEPLOY.read_text()

    def test_sintaks_bash(self):
        r = subprocess.run(["bash", "-n", str(DEPLOY)], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_posisi_blok(self):
        api = self.src.index('echo "✅ API menjalankan')
        unit = self.src.index("jatahku-worker.service")
        restart = self.src.index("systemctl restart jatahku-worker")
        fe = self.src.index("# Frontend")
        self.assertLess(api, unit)
        self.assertLess(unit, restart)
        self.assertLess(restart, fe)

    def test_perintah_pasang(self):
        for s in ["cmp -s", "systemctl daemon-reload", "systemctl enable jatahku-worker",
                  "systemctl is-active --quiet jatahku-worker",
                  "sudo journalctl -u jatahku-worker -n 40 --no-pager"]:
            self.assertIn(s, self.src)
        self.assertIn("/etc/systemd/system/jatahku-worker.service", self.src)

    def test_tidak_menjalankan_ulang_diri(self):
        self.assertNotIn("exec ", self.src)
        self.assertNotIn('"$0"', self.src)

    def test_worker_gagal_keluar_nonnol_di_akhir(self):
        self.assertIn("WORKER_GAGAL=1", self.src)
        cek = self.src.rindex('if [ -n "$WORKER_GAGAL" ]')
        self.assertGreater(cek, self.src.index("Health check"))
        sisa = self.src[cek:]
        self.assertIn("exit 1", sisa)
        # MIG_PENDING tetap ada dan mendahului pemeriksaan akhir worker
        self.assertLess(self.src.rindex('if [ -n "$MIG_PENDING" ]'), cek)


if __name__ == "__main__":
    unittest.main()
