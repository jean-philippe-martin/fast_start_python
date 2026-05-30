import os
import shutil
import sys
import unittest
from pathlib import Path

import cache

from harness import FIXTURES_DIR, MODULE_NAME, TESTS_DIR, ScriptSequenceHarness


class CacheSequenceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.work_dir = TESTS_DIR / "tmp" / self._testMethodName
        self.cache_dir = self.work_dir / "cache"
        self.harness = ScriptSequenceHarness(self.work_dir, self.cache_dir)
        cache.clear(self.cache_dir)

    def tearDown(self) -> None:
        cache.clear(self.cache_dir)
        sys.modules.pop(MODULE_NAME, None)
        sys.modules.pop("depmod", None)
        sys.path[:] = [entry for entry in sys.path if str(TESTS_DIR / "tmp") not in entry]
        os.environ.pop("FSPYTHON_CACHE_DIR", None)
        if self.work_dir.exists():
            shutil.rmtree(self.work_dir)

    def test_cache_hit_when_unrelated_code_appended_at_bottom(self) -> None:
        fixture_dir = FIXTURES_DIR / "append_only"

        mod = self.harness.run_version(fixture_dir / "v1_basic.py")
        self.assertEqual(mod.compute(3), 6)
        self.assertEqual(mod.CALLS, 1)

        self.assertEqual(mod.compute(3), 6)
        self.assertEqual(mod.CALLS, 1)

        mod = self.harness.run_version(fixture_dir / "v2_with_extra_at_bottom.py")
        self.assertEqual(mod.compute(3), 6)
        self.assertEqual(mod.CALLS, 0)

        self.assertEqual(mod.new_helper(), "added later")

        self.assertEqual(mod.compute(3), 6)
        self.assertEqual(mod.CALLS, 0)

        self.assertEqual(mod.compute(5), 10)
        self.assertEqual(mod.CALLS, 1)

        entry_dir = self.cache_dir / "data" / "script.compute"
        self.assertTrue(entry_dir.is_dir())
        self.assertGreaterEqual(len(list(entry_dir.glob("*.pkl"))), 2)

    def test_miss_when_same_folder_import_changes(self) -> None:
        fixture_dir = FIXTURES_DIR / "same_folder_import"
        script = fixture_dir / "script.py"

        mod = self.harness.prepare(
            script=script,
            deps={"depmod": fixture_dir / "v1_depmod.py"},
        )
        self.assertEqual(mod.compute(5), 15)
        self.assertEqual(mod.CALLS, 1)
        self.assertEqual(mod.compute(5), 15)
        self.assertEqual(mod.CALLS, 1)

        mod = self.harness.prepare(
            script=script,
            deps={"depmod": fixture_dir / "v2_depmod.py"},
        )
        self.assertEqual(mod.compute(5), 25)
        self.assertEqual(mod.CALLS, 1)

    def test_hit_when_late_imported_same_folder_file_changes(self) -> None:
        fixture_dir = FIXTURES_DIR / "import_after_call"
        script = fixture_dir / "script.py"
        kwargs = {"script": script, "deps": {"depmod": fixture_dir / "v1_depmod.py"}}

        mod = self.harness.prepare(**kwargs)
        result, label = mod.run()
        self.assertEqual(result, 10)
        self.assertEqual(label, "v1")
        self.assertEqual(mod.CALLS, 1)

        mod = self.harness.prepare(**kwargs)
        result, label = mod.run()
        self.assertEqual(result, 10)
        self.assertEqual(label, "v1")
        self.assertEqual(mod.CALLS, 0)

        mod = self.harness.prepare(
            script=script,
            deps={"depmod": fixture_dir / "v2_depmod.py"},
        )
        result, label = mod.run()
        self.assertEqual(result, 10)
        self.assertEqual(label, "v2")
        self.assertEqual(mod.CALLS, 0)

    def test_miss_when_decorated_function_changes(self) -> None:
        fixture_dir = FIXTURES_DIR / "decorated_changed"

        mod = self.harness.run_version(fixture_dir / "v1_script.py")
        self.assertEqual(mod.compute(3), 6)
        self.assertEqual(mod.CALLS, 1)

        mod = self.harness.run_version(fixture_dir / "v2_script.py")
        self.assertEqual(mod.compute(3), 9)
        self.assertEqual(mod.CALLS, 1)

    def test_miss_when_same_file_callee_changes(self) -> None:
        fixture_dir = FIXTURES_DIR / "callee_changed"

        mod = self.harness.run_version(fixture_dir / "v1_script.py")
        self.assertEqual(mod.compute(5), 15)
        self.assertEqual(mod.CALLS, 1)

        mod = self.harness.run_version(fixture_dir / "v2_script.py")
        self.assertEqual(mod.compute(5), 25)
        self.assertEqual(mod.CALLS, 1)

    def test_hit_when_unrelated_same_file_function_changes(self) -> None:
        fixture_dir = FIXTURES_DIR / "unrelated_callee"

        mod = self.harness.run_version(fixture_dir / "v1_script.py")
        self.assertEqual(mod.compute(3), 6)
        self.assertEqual(mod.CALLS, 1)

        mod = self.harness.run_version(fixture_dir / "v2_script.py")
        self.assertEqual(mod.compute(3), 6)
        self.assertEqual(mod.CALLS, 0)
        self.assertEqual(mod.other(), 999)


if __name__ == "__main__":
    unittest.main()
