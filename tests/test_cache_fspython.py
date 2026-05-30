import shutil
import unittest
from pathlib import Path

import cache

from harness import (
    FIXTURES_DIR,
    TESTS_DIR,
    SharedFspythonServerTest,
    ScriptSequenceHarness,
    parse_calls_output,
)


class CacheFspythonTests(SharedFspythonServerTest):
    def setUp(self) -> None:
        super().setUp()
        self.work_dir = TESTS_DIR / "tmp" / self._testMethodName
        self.cache_dir = self.work_dir / "cache"
        self.work_dir.mkdir(parents=True, exist_ok=True)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        cache.clear(self.cache_dir)

    def tearDown(self) -> None:
        cache.clear(self.cache_dir)
        if self.work_dir.exists():
            shutil.rmtree(self.work_dir)

    def _run_script(self, script_path: Path):
        result = self.server.run_script(script_path, cache_dir=self.cache_dir)
        self.assertEqual(result.returncode, 0, result.stderr)
        return parse_calls_output(result.stdout)

    def test_cache_hit_on_second_fspython_run(self) -> None:
        script_path = self.work_dir / "script.py"
        shutil.copy(FIXTURES_DIR / "fspython_basic" / "script.py", script_path)

        result, calls = self._run_script(script_path)
        self.assertEqual(result, 6)
        self.assertEqual(calls, 1)

        result, calls = self._run_script(script_path)
        self.assertEqual(result, 6)
        self.assertEqual(calls, 0)

    def test_cache_hit_after_unrelated_append_via_fspython(self) -> None:
        fixture_dir = FIXTURES_DIR / "append_only"
        harness = ScriptSequenceHarness(self.work_dir, self.cache_dir)

        harness.run_version(fixture_dir / "v1_basic.py")
        result, calls = self._run_script(harness.script_path)
        self.assertEqual(result, 6)
        self.assertEqual(calls, 1)

        result, calls = self._run_script(harness.script_path)
        self.assertEqual(result, 6)
        self.assertEqual(calls, 0)

        harness.run_version(fixture_dir / "v2_with_extra_at_bottom.py")
        result, calls = self._run_script(harness.script_path)
        self.assertEqual(result, 6)
        self.assertEqual(calls, 0)

    def test_cache_miss_when_decorated_function_changes_via_fspython(self) -> None:
        fixture_dir = FIXTURES_DIR / "decorated_changed"
        harness = ScriptSequenceHarness(self.work_dir, self.cache_dir)

        harness.run_version(fixture_dir / "v1_script.py")
        self._run_script(harness.script_path)

        harness.run_version(fixture_dir / "v2_script.py")
        result, calls = self._run_script(harness.script_path)
        self.assertEqual(result, 9)
        self.assertEqual(calls, 1)


if __name__ == "__main__":
    unittest.main()
