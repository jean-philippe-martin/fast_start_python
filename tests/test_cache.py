import shutil
import sys
import textwrap
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import cache

from harness import TESTS_DIR, load_module_from_source

_load_module = load_module_from_source


class CacheMemoizeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.cache_dir = TESTS_DIR / "tmp" / self._testMethodName
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        cache.clear(self.cache_dir)

    def tearDown(self) -> None:
        cache.clear(self.cache_dir)
        if self.cache_dir.exists():
            shutil.rmtree(self.cache_dir)
        sys.path[:] = [entry for entry in sys.path if str(TESTS_DIR / "tmp") not in entry]
        for name in ("depmod", "extmod", "consumer_testmod"):
            sys.modules.pop(name, None)

    def test_cache_hit_on_second_call(self) -> None:
        module_path = self.cache_dir / "sample.py"
        mod = _load_module(
            """
            import cache

            CALLS = 0

            @cache.memoize(cache_dir={cache_dir})
            def compute(x):
                global CALLS
                CALLS += 1
                return x * 2
            """,
            module_path,
            self.cache_dir,
        )

        self.assertEqual(mod.compute(3), 6)
        self.assertEqual(mod.compute(3), 6)
        self.assertEqual(mod.CALLS, 1)

    def test_miss_when_args_change(self) -> None:
        module_path = self.cache_dir / "args.py"
        mod = _load_module(
            """
            import cache

            CALLS = 0

            @cache.memoize(cache_dir={cache_dir})
            def compute(x):
                global CALLS
                CALLS += 1
                return x
            """,
            module_path,
            self.cache_dir,
        )

        mod.compute(1)
        mod.compute(2)
        self.assertEqual(mod.CALLS, 2)

    def test_miss_when_decorated_function_changes(self) -> None:
        module_path = self.cache_dir / "decorated.py"
        source_v1 = """
            import cache

            CALLS = 0

            @cache.memoize(cache_dir={cache_dir})
            def compute(x):
                global CALLS
                CALLS += 1
                return x + 1
        """
        mod = _load_module(source_v1, module_path, self.cache_dir)
        mod.compute(5)
        self.assertEqual(mod.CALLS, 1)

        source_v2 = source_v1.replace("return x + 1", "return x + 2")
        mod = _load_module(source_v2, module_path, self.cache_dir)
        result = mod.compute(5)
        self.assertEqual(result, 7)
        self.assertEqual(mod.CALLS, 1)

    def test_miss_when_helper_changes(self) -> None:
        module_path = self.cache_dir / "helper.py"
        source_v1 = """
            import cache

            CALLS = 0

            def helper(x):
                return x + 10

            @cache.memoize(cache_dir={cache_dir})
            def compute(x):
                global CALLS
                CALLS += 1
                return helper(x)
        """
        mod = _load_module(source_v1, module_path, self.cache_dir)
        self.assertEqual(mod.compute(5), 15)
        self.assertEqual(mod.CALLS, 1)
        self.assertEqual(mod.compute(5), 15)
        self.assertEqual(mod.CALLS, 1)

        source_v2 = source_v1.replace("return x + 10", "return x + 20")
        mod = _load_module(source_v2, module_path, self.cache_dir)
        self.assertEqual(mod.compute(5), 25)
        self.assertEqual(mod.CALLS, 1)

    def test_hit_when_unrelated_function_changes(self) -> None:
        module_path = self.cache_dir / "unrelated.py"
        source_v1 = """
            import cache

            CALLS = 0

            def helper(x):
                return x + 1

            def other():
                return 0

            @cache.memoize(cache_dir={cache_dir})
            def compute(x):
                global CALLS
                CALLS += 1
                return helper(x)
        """
        mod = _load_module(source_v1, module_path, self.cache_dir)
        mod.compute(1)
        self.assertEqual(mod.CALLS, 1)

        source_v2 = source_v1.replace("def other():\n                return 0", "def other():\n                return 99")
        mod = _load_module(source_v2, module_path, self.cache_dir)
        result = mod.compute(1)
        self.assertEqual(result, 2)
        self.assertEqual(mod.CALLS, 0)

    def test_persists_across_reload(self) -> None:
        module_path = self.cache_dir / "persist.py"
        source = """
            import cache

            CALLS = 0

            @cache.memoize(cache_dir={cache_dir})
            def compute(x):
                global CALLS
                CALLS += 1
                return x
        """
        mod = _load_module(source, module_path, self.cache_dir)
        mod.compute(7)
        self.assertEqual(mod.CALLS, 1)

        mod = _load_module(source, module_path, self.cache_dir)
        mod.compute(7)
        self.assertEqual(mod.CALLS, 0)

    def test_clear_function(self) -> None:
        module_path = self.cache_dir / "clear.py"
        mod = _load_module(
            """
            import cache

            CALLS = 0

            @cache.memoize(cache_dir={cache_dir})
            def compute(x):
                global CALLS
                CALLS += 1
                return x
            """,
            module_path,
            self.cache_dir,
        )
        mod.compute(1)
        cache.clear_function(mod.compute, self.cache_dir)
        mod.compute(1)
        self.assertEqual(mod.CALLS, 2)

    def test_miss_when_imported_module_changes(self) -> None:
        work_dir = self.cache_dir / "pkg"
        dependency_path = work_dir / "depmod.py"
        consumer_path = work_dir / "consumer.py"

        dependency_path.parent.mkdir(parents=True, exist_ok=True)
        dependency_path.write_text(
            textwrap.dedent(
                """
                def helper(x):
                    return x + 10
                """
            ),
            encoding="utf-8",
        )

        consumer_source = """
            import cache
            from depmod import helper

            CALLS = 0

            @cache.memoize(cache_dir={cache_dir})
            def compute(x):
                global CALLS
                CALLS += 1
                return helper(x)
        """
        mod = _load_module(consumer_source, consumer_path, self.cache_dir)
        self.assertEqual(mod.compute(5), 15)
        self.assertEqual(mod.CALLS, 1)
        self.assertEqual(mod.compute(5), 15)
        self.assertEqual(mod.CALLS, 1)

        dependency_path.write_text(
            textwrap.dedent(
                """
                def helper(x):
                    return x + 20
                """
            ),
            encoding="utf-8",
        )
        sys.modules.pop("depmod", None)
        sys.modules.pop("consumer_testmod", None)
        mod = _load_module(consumer_source, consumer_path, self.cache_dir)
        self.assertEqual(mod.compute(5), 25)
        self.assertEqual(mod.CALLS, 1)

    def test_miss_when_runtime_import_in_same_folder_changes(self) -> None:
        work_dir = self.cache_dir / "runtime_pkg"
        work_dir.mkdir(parents=True, exist_ok=True)
        dependency_path = work_dir / "depmod.py"
        consumer_path = work_dir / "consumer.py"

        dependency_path.write_text(
            "def helper(x):\n    return x + 1\n",
            encoding="utf-8",
        )

        consumer_source = """
            import cache
            import sys

            CALLS = 0

            @cache.memoize(cache_dir={cache_dir})
            def compute(x):
                global CALLS
                CALLS += 1
                return sys.modules["depmod"].helper(x)

            def run():
                import depmod
                return compute(5)
        """
        mod = _load_module(consumer_source, consumer_path, self.cache_dir)
        self.assertEqual(mod.run(), 6)
        self.assertEqual(mod.CALLS, 1)
        self.assertEqual(mod.run(), 6)
        self.assertEqual(mod.CALLS, 1)

        dependency_path.write_text(
            "def helper(x):\n    return x + 9\n",
            encoding="utf-8",
        )
        sys.modules.pop("depmod", None)
        sys.modules.pop("consumer_testmod", None)
        mod = _load_module(consumer_source, consumer_path, self.cache_dir)
        self.assertEqual(mod.run(), 14)
        self.assertEqual(mod.CALLS, 1)

    def test_miss_when_entry_expires(self) -> None:
        module_path = self.cache_dir / "ttl.py"
        mod = _load_module(
            """
            import cache

            CALLS = 0

            @cache.memoize(cache_dir={cache_dir})
            def compute(x):
                global CALLS
                CALLS += 1
                return x
            """,
            module_path,
            self.cache_dir,
        )

        mod.compute(1)
        self.assertEqual(mod.CALLS, 1)

        expired_now = datetime.now(timezone.utc) + cache.DEFAULT_TTL + timedelta(seconds=1)
        with patch("cache._utcnow", return_value=expired_now):
            mod.compute(1)
        self.assertEqual(mod.CALLS, 2)

    def test_hit_when_entry_within_ttl(self) -> None:
        module_path = self.cache_dir / "ttl_hit.py"
        mod = _load_module(
            """
            import cache

            CALLS = 0

            @cache.memoize(cache_dir={cache_dir})
            def compute(x):
                global CALLS
                CALLS += 1
                return x
            """,
            module_path,
            self.cache_dir,
        )

        mod.compute(1)
        self.assertEqual(mod.CALLS, 1)

        still_valid = datetime.now(timezone.utc) + cache.DEFAULT_TTL - timedelta(seconds=1)
        with patch("cache._utcnow", return_value=still_valid):
            mod.compute(1)
        self.assertEqual(mod.CALLS, 1)

    def test_hit_when_import_outside_script_folder_changes(self) -> None:
        script_dir = self.cache_dir / "script_dir"
        outside_dir = self.cache_dir / "outside"
        script_dir.mkdir(parents=True, exist_ok=True)
        outside_dir.mkdir(parents=True, exist_ok=True)

        external_path = outside_dir / "extmod.py"
        consumer_path = script_dir / "consumer.py"
        external_path.write_text("VALUE = 1\n", encoding="utf-8")

        consumer_source = """
            import cache
            import extmod

            CALLS = 0

            @cache.memoize(cache_dir={cache_dir})
            def compute(x):
                global CALLS
                CALLS += 1
                return x + extmod.VALUE
        """
        path_backup = list(sys.path)
        sys.path.insert(0, str(outside_dir.resolve()))
        sys.path.insert(0, str(script_dir.resolve()))
        try:
            mod = _load_module(consumer_source, consumer_path, self.cache_dir)
            self.assertEqual(mod.compute(1), 2)
            self.assertEqual(mod.CALLS, 1)

            external_path.write_text("VALUE = 999\n", encoding="utf-8")
            sys.modules.pop("extmod", None)
            sys.modules.pop("consumer_testmod", None)
            mod = _load_module(consumer_source, consumer_path, self.cache_dir)
            self.assertEqual(mod.compute(1), 2)
            self.assertEqual(mod.CALLS, 0)
        finally:
            sys.path[:] = path_backup


if __name__ == "__main__":
    unittest.main()
