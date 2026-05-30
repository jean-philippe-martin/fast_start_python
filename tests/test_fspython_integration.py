import shutil
import subprocess
import textwrap
import time
import unittest
from pathlib import Path

from harness import TESTS_DIR, SharedFspythonServerTest, fspython_cmd


class FspythonIntegrationTests(SharedFspythonServerTest):
    def setUp(self) -> None:
        super().setUp()
        self.work_dir = TESTS_DIR / "tmp" / self._testMethodName
        self.work_dir.mkdir(parents=True, exist_ok=True)

    def tearDown(self) -> None:
        if self.work_dir.exists():
            shutil.rmtree(self.work_dir)

    def test_run_script_via_server(self) -> None:
        script_path = self.work_dir / "hello.py"
        script_path.write_text(
            textwrap.dedent(
                """
                print("hello from fspython")
                """
            ),
            encoding="utf-8",
        )

        result = self.server.run_script(script_path)
        self.assertEqual(result.returncode, 0)
        self.assertIn("hello from fspython", result.stdout)

    def test_status_reports_ready(self) -> None:
        status = self.server.status()
        self.assertTrue(status["ok"])
        self.assertEqual(status["state"], "ready")
        self.assertEqual(status["active_children"], 0)
        self.assertFalse(status["gui"])

    def test_drain_waits_for_active_run(self) -> None:
        slow_script = self.work_dir / "slow.py"
        slow_script.write_text(
            textwrap.dedent(
                """
                import time
                time.sleep(2)
                print("done")
                """
            ),
            encoding="utf-8",
        )

        run_proc = subprocess.Popen(
            fspython_cmd(
                "run",
                "--host",
                self.server.host,
                "--port",
                str(self.server.port),
                str(slow_script.resolve()),
            ),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        time.sleep(0.3)

        drain = self.server.drain()
        self.assertTrue(drain["ok"])
        self.assertEqual(drain["message"], "draining")

        status = self.server.status()
        self.assertEqual(status["state"], "draining")
        self.assertGreaterEqual(status["active_children"], 1)

        stdout, _stderr = run_proc.communicate(timeout=10)
        self.assertEqual(run_proc.returncode, 0)
        self.assertIn("done", stdout)

        self._wait_for_server_exit()
        self.assertIsNotNone(self.server.process)
        self.assertIsNotNone(self.server.process.poll())
        self.assertEqual(self.server.process.returncode, 0)
        self.server.process = None

    def _wait_for_server_exit(self) -> None:
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            if self.server.process is None or self.server.process.poll() is not None:
                return
            time.sleep(0.1)

    def test_run_rejected_while_draining(self) -> None:
        slow_script = self.work_dir / "slow.py"
        slow_script.write_text(
            textwrap.dedent(
                """
                import time
                time.sleep(2)
                print("done")
                """
            ),
            encoding="utf-8",
        )
        quick_script = self.work_dir / "quick.py"
        quick_script.write_text('print("ok")\n', encoding="utf-8")

        run_proc = subprocess.Popen(
            fspython_cmd(
                "run",
                "--host",
                self.server.host,
                "--port",
                str(self.server.port),
                str(slow_script.resolve()),
            ),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        time.sleep(0.3)

        self.server.drain()
        result = self.server.run_script(quick_script)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("draining", result.stderr)

        run_proc.communicate(timeout=10)
        self._wait_for_server_exit()
        self.server.process = None


if __name__ == "__main__":
    unittest.main()
