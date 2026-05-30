import importlib.util
import os
import shutil
import sys
import unittest
from pathlib import Path

import cache

TESTS_DIR = Path(__file__).resolve().parent
FIXTURES_DIR = TESTS_DIR / "cache_fixtures"
SCRIPT_NAME = "script.py"
MODULE_NAME = "script_testmod"


def _clear_pycache(directory: Path) -> None:
    for pycache in directory.rglob("__pycache__"):
        shutil.rmtree(pycache)


class ScriptSequenceHarness:
    """Copy fixture versions onto one script path and reload like a rerun."""

    def __init__(self, work_dir: Path, cache_dir: Path) -> None:
        self.work_dir = work_dir
        self.cache_dir = cache_dir
        self.script_path = work_dir / SCRIPT_NAME
        self.work_dir.mkdir(parents=True, exist_ok=True)
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def install_script(self, fixture_path: Path) -> None:
        """Copy a fixture file onto the fixed script path."""
        shutil.copy(fixture_path, self.script_path)
        _clear_pycache(self.work_dir)
        importlib.invalidate_caches()

    def install_dependency(self, name: str, fixture_path: Path) -> None:
        """Copy a same-folder dependency module into the workspace."""
        shutil.copy(fixture_path, self.work_dir / f"{name}.py")
        _clear_pycache(self.work_dir)
        importlib.invalidate_caches()
        sys.modules.pop(name, None)

    def reload(self):
        """Load script.py fresh, as if the process reran after an edit."""
        work_dir = str(self.work_dir.resolve())
        if work_dir not in sys.path:
            sys.path.insert(0, work_dir)

        os.environ["FSPYTHON_CACHE_DIR"] = str(self.cache_dir.resolve())
        sys.modules.pop(MODULE_NAME, None)

        spec = importlib.util.spec_from_file_location(MODULE_NAME, self.script_path)
        assert spec and spec.loader
        module = importlib.util.module_from_spec(spec)
        sys.modules[MODULE_NAME] = module
        spec.loader.exec_module(module)
        return module

    def prepare(
        self,
        *,
        script: Path | None = None,
        deps: dict[str, Path] | None = None,
    ):
        """Install script and dependency fixtures, then reload."""
        if script is not None:
            self.install_script(script)
        if deps:
            for name, fixture_path in deps.items():
                self.install_dependency(name, fixture_path)
        return self.reload()

    def run_version(self, fixture_path: Path):
        """Install a script fixture version and reload."""
        self.install_script(fixture_path)
        return self.reload()


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
