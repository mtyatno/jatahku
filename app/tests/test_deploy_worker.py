"""Unit systemd worker email laporan dan langkahnya di deploy.sh (uji teks/urutan)."""
import os
import re
import shutil
import stat
import subprocess
import tempfile
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
            "Restart=always", "RestartSec=5", "Nice=5", "TimeoutStopSec=60", "NoNewPrivileges=true",
            "WantedBy=multi-user.target",
        ]:
            self.assertIn(baris, self.lines)

    def test_no_new_privileges_di_bagian_service(self):
        service = self.lines.index("[Service]")
        install = self.lines.index("[Install]")
        self.assertTrue(service < self.lines.index("NoNewPrivileges=true") < install)

    def test_tanpa_environment_file(self):
        self.assertFalse(any(l.startswith("EnvironmentFile") for l in self.lines))

    def test_komentar_kepala(self):
        self.assertTrue(self.lines[0].startswith("#"))
        self.assertIn("deploy.sh", "\n".join(l for l in self.lines if l.startswith("#")))


SRC_ASLI = "/opt/jatahku/app/deploy/jatahku-worker.service"
DEST_ASLI = "/etc/systemd/system/jatahku-worker.service"


def _bagian(src, nama):
    m = re.search(
        r"# \[worker-email-laporan:%s\]\n(.*?)# \[/worker-email-laporan:%s\]\n" % (nama, nama),
        src, re.S)
    assert m, nama
    return m.group(1)


class DeployWorkerTest(unittest.TestCase):
    def setUp(self):
        self.src = DEPLOY.read_text()

    def test_sintaks_bash(self):
        r = subprocess.run(["bash", "-n", str(DEPLOY)], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_posisi_blok(self):
        api = self.src.index('echo "✅ API menjalankan')
        awal = self.src.index("# [worker-email-laporan:blok]")
        akhir = self.src.index("# [/worker-email-laporan:blok]")
        fe = self.src.index("# Frontend")
        self.assertLess(api, awal)
        self.assertLess(awal, akhir)
        self.assertLess(akhir, fe)

    def test_jalur_tetap_dan_tanpa_override(self):
        blok = _bagian(self.src, "blok")
        self.assertIn(SRC_ASLI, blok)
        self.assertIn(DEST_ASLI, blok)
        self.assertNotIn("WORKER_UNIT_", self.src)

    def test_tidak_menjalankan_ulang_diri(self):
        self.assertNotIn("exec ", self.src)
        self.assertNotIn('"$0"', self.src)

    def test_pesan_sebelum_mig_pending_dan_cek_akhir_sesudahnya(self):
        mig = self.src.rindex('if [ -n "$MIG_PENDING" ]')
        self.assertLess(self.src.index("# [worker-email-laporan:pesan]"), mig)
        self.assertGreater(self.src.index("# [worker-email-laporan:akhir]"), mig)


# Urutan penting (F-9): sebelum stub `sleep` jalan (berkas penanda `$STATE/tidur`), `show` menjawab NR1 dan
# `is-active` menjawab aktif (proses baru saja dibuat); sesudahnya NR2 dan ACTIVE. Membaca penghitung pertama sesudah
# tidur, atau memeriksa is-active sebelum tidur, menggagalkan tes d/e.
STUB_SYSTEMCTL = r"""#!/bin/bash
echo "systemctl $*" >> "$LOG"
case "$1" in
  restart) [ "$RESTART_FAIL" = 1 ] && exit 1; exit 0 ;;
  disable) [ "$DISABLE_FAIL" = 1 ] && exit 1; exit 0 ;;
  daemon-reload) [ "$RELOAD_FAIL" = 1 ] && exit 1; exit 0 ;;
  is-enabled) [ "$ENABLED" = 1 ]; exit $? ;;
  is-active)
    [ -f "$STATE/tidur" ] || exit 0
    [ "$ACTIVE" = 1 ]; exit $? ;;
  show)
    if [ -f "$STATE/tidur" ]; then echo -n "$NR2"; else echo -n "$NR1"; fi
    [ -n "$NR1$NR2" ] && echo
    exit 0 ;;
esac
exit 0
"""


@unittest.skipUnless(shutil.which("bash"), "bash tidak tersedia")
class DeployWorkerPerilakuTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.bin = self.tmp / "bin"
        self.bin.mkdir()
        self.repo_unit = self.tmp / "repo.service"
        self.dest = self.tmp / "dest.service"
        self.repo_unit.write_text(UNIT.read_text())
        self.log = self.tmp / "log"
        self.log.write_text("")
        self.state = self.tmp / "state"
        self.state.mkdir()
        self._stub("sudo", '#!/bin/bash\nexec "$@"\n')
        self._stub("systemctl", STUB_SYSTEMCTL)
        self._stub("journalctl", '#!/bin/bash\necho "journalctl $*" >> "$LOG"\necho JURNAL-STUB\n')
        self._stub("sleep", '#!/bin/bash\necho "sleep $*" >> "$LOG"\ntouch "$STATE/tidur"\n')
        src = DEPLOY.read_text()
        blok = _bagian(src, "blok").replace(SRC_ASLI, str(self.repo_unit)).replace(DEST_ASLI, str(self.dest))
        assert str(self.dest) in blok
        skrip = (
            "set -e\nMIG_PENDING=\"${MIG_PENDING:-}\"\n" + blok
            + 'echo "LANJUT-LANGKAH-LAIN"\n' + _bagian(src, "pesan")
            + 'if [ -n "$MIG_PENDING" ]; then echo MIG-PESAN; exit 2; fi\n'
            + _bagian(src, "akhir")
        )
        self.script = self.tmp / "skrip.sh"
        self.script.write_text(skrip)

    def _stub(self, nama, isi):
        f = self.bin / nama
        f.write_text(isi)
        f.chmod(f.stat().st_mode | stat.S_IEXEC)

    def jalan(self, *, enabled=1, active=1, nr1="0", nr2="0", restart_fail=0, pasang_unit=True, mig="",
              disable_fail=0, reload_fail=0):
        if pasang_unit:
            self.dest.write_text(self.repo_unit.read_text())
        env = dict(os.environ, PATH=f"{self.bin}:{os.environ['PATH']}", LOG=str(self.log),
                   STATE=str(self.state), ENABLED=str(enabled), ACTIVE=str(active),
                   NR1=nr1, NR2=nr2, RESTART_FAIL=str(restart_fail), MIG_PENDING=mig,
                   DISABLE_FAIL=str(disable_fail), RELOAD_FAIL=str(reload_fail))
        r = subprocess.run(["bash", str(self.script)], capture_output=True, text=True, env=env, timeout=30)
        calls = self.log.read_text().splitlines()
        return r, calls

    def assertGagal(self, r, calls):
        self.assertNotEqual(r.returncode, 0, r.stdout)
        self.assertIn("LANJUT-LANGKAH-LAIN", r.stdout)
        self.assertIn("JURNAL-STUB", r.stdout)
        self.assertIn("journalctl -u jatahku-worker -n 40 --no-pager", calls)
        self.assertIn("journalctl -u jatahku-worker", r.stdout)
        self.assertNotIn("✅ Worker email laporan aktif", r.stdout)

    def test_a_pasang_pertama(self):
        r, calls = self.jalan(enabled=0, pasang_unit=False)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(self.dest.read_text(), self.repo_unit.read_text())
        for c in ["systemctl daemon-reload", "systemctl enable jatahku-worker",
                  "systemctl restart jatahku-worker"]:
            self.assertIn(c, calls)
        self.assertIn("✅ Worker email laporan aktif", r.stdout)
        self.assertIn("LANJUT-LANGKAH-LAIN", r.stdout)

    def test_b_unit_sama_dan_enabled(self):
        r, calls = self.jalan()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertNotIn("systemctl daemon-reload", calls)
        self.assertNotIn("systemctl enable jatahku-worker", calls)
        self.assertIn("systemctl restart jatahku-worker", calls)
        self.assertIn("sleep 10", calls)

    def test_c_sama_tapi_belum_enabled(self):
        r, calls = self.jalan(enabled=0)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("systemctl daemon-reload", calls)
        self.assertIn("systemctl enable jatahku-worker", calls)

    def test_d_tidak_aktif(self):
        self.assertGagal(*self.jalan(active=0))

    def test_e_penghitung_restart_naik(self):
        self.assertGagal(*self.jalan(nr1="0", nr2="2"))

    def test_f_penghitung_tak_terbaca(self):
        self.assertGagal(*self.jalan(nr1="", nr2=""))
        self.setUp()
        self.assertGagal(*self.jalan(nr1="0", nr2=""))

    def test_g_restart_gagal(self):
        r, calls = self.jalan(restart_fail=1)
        self.assertGagal(r, calls)

    def test_urutan_baca_penghitung_tidur_aktif(self):
        r, calls = self.jalan()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        urutan = [c for c in calls if c.startswith(("systemctl restart", "systemctl show", "sleep", "systemctl is-active"))]
        self.assertEqual(urutan, [
            "systemctl restart jatahku-worker", "systemctl show -p NRestarts --value jatahku-worker", "sleep 10",
            "systemctl show -p NRestarts --value jatahku-worker", "systemctl is-active --quiet jatahku-worker"])

    def test_h_sumber_unit_tidak_ada_worker_dihentikan(self):
        # F-2: deploy revert (pohon tanpa unit dan modul worker): worker dihentikan dan unitnya dilepas, deploy lanjut.
        self.dest.write_text(self.repo_unit.read_text())   # unit versi lama masih terpasang
        self.repo_unit.unlink()
        r, calls = self.jalan(pasang_unit=False)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("⚠️  Unit worker tidak ada di repo — worker email laporan dihentikan", r.stdout)
        self.assertIn("systemctl disable --now jatahku-worker", calls)
        self.assertFalse(self.dest.exists())
        self.assertIn("systemctl daemon-reload", calls)
        self.assertLess(calls.index("systemctl disable --now jatahku-worker"), calls.index("systemctl daemon-reload"))
        self.assertFalse(any(c.startswith(("systemctl restart", "systemctl enable", "systemctl show", "sleep"))
                             for c in calls), calls)
        self.assertIn("LANJUT-LANGKAH-LAIN", r.stdout)
        self.assertNotIn("Worker email laporan belum berjalan", r.stdout)

    def test_i_sumber_unit_tidak_ada_dan_tidak_terpasang(self):
        self.repo_unit.unlink()
        r, calls = self.jalan(pasang_unit=False, disable_fail=1, reload_fail=1)   # unit tak dikenal: disable gagal
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertFalse(self.dest.exists())
        self.assertIn("systemctl disable --now jatahku-worker", calls)
        self.assertNotIn("systemctl restart jatahku-worker", calls)
        self.assertIn("LANJUT-LANGKAH-LAIN", r.stdout)

    def test_gagal_bersama_mig_pending_keduanya_tercetak(self):
        r, calls = self.jalan(active=0, mig="1")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("Worker email laporan belum berjalan", r.stdout)
        self.assertIn("MIG-PESAN", r.stdout)


if __name__ == "__main__":
    unittest.main()
