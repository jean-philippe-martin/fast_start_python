"""Disk-backed memoization with AST-based dependency tracking.

Basic usage: just add @cache.memoize above the function you want to cache.

@cache.memoize
def fetch_sales(region: str) -> dict:
    pass # todo: fetch from database

Now the result of fetch_sales will be cached on disk, and subsequent calls will return the cached result.

Cache invalidation is triggered by:
- different arguments
- changes to the function's source code
- changes to same-file functions the function calls
- changes to same-folder modules imported before the function is called
- entries older than 30 minutes
"""

from __future__ import annotations

import ast
import fcntl
import hashlib
import inspect
import json
import os
import pickle
import sys
from datetime import datetime, timedelta, timezone
from functools import wraps
from pathlib import Path
from typing import Any, Callable, TypeVar

F = TypeVar("F", bound=Callable[..., Any])

DEFAULT_CACHE_DIR = Path(".fspython_cache")
DEFAULT_TTL = timedelta(minutes=30)
_CACHE_DIR_OVERRIDE: Path | None = None


def set_cache_dir(path: Path | str) -> None:
    """Set the default cache directory for subsequent memoize calls."""
    global _CACHE_DIR_OVERRIDE
    _CACHE_DIR_OVERRIDE = Path(path)


def default_cache_dir() -> Path:
    """Return the configured cache root directory."""
    if _CACHE_DIR_OVERRIDE is not None:
        return _CACHE_DIR_OVERRIDE
    env = os.environ.get("FSPYTHON_CACHE_DIR")
    if env:
        return Path(env)
    return DEFAULT_CACHE_DIR


def clear(cache_dir: Path | str | None = None) -> None:
    """Remove all cached data under the cache root."""
    root = Path(cache_dir) if cache_dir is not None else default_cache_dir()
    if not root.exists():
        return
    for child in root.iterdir():
        if child.is_dir():
            _rmtree(child)
        else:
            child.unlink()


def clear_function(func: Callable[..., Any], cache_dir: Path | str | None = None) -> None:
    """Remove cached entries and metadata for a single memoized function."""
    root = Path(cache_dir) if cache_dir is not None else default_cache_dir()
    key = _function_key(inspect.unwrap(func))
    for subdir in ("meta", "data"):
        target = root / subdir / _safe_filename(key)
        if target.is_dir():
            _rmtree(target)
        elif target.exists():
            target.unlink()


def memoize(
    func: F | None = None,
    *,
    cache_dir: Path | str | None = None,
    enabled: bool = True,
) -> F | Callable[[F], F]:
    """Memoize a function on disk; invalidate when args or code dependencies change."""

    def decorate(target: F) -> F:
        root = Path(cache_dir) if cache_dir is not None else default_cache_dir()

        @wraps(target)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            if not enabled:
                return target(*args, **kwargs)

            func_key = _function_key(target)
            version_hash = _version_hash(target)
            args_hash = _args_hash(args, kwargs)

            meta_path = _meta_path(root, func_key)
            entry_path = _entry_path(root, func_key, args_hash)

            _ensure_version(root, func_key, meta_path, version_hash)

            cached = _load_entry(entry_path, version_hash, args_hash)
            if cached is not None:
                return cached

            result = target(*args, **kwargs)
            _save_entry(entry_path, result, version_hash, args_hash)
            return result

        wrapper.__memoize_cache_dir__ = root  # type: ignore[attr-defined]
        return wrapper  # type: ignore[return-value]

    if func is not None:
        return decorate(func)
    return decorate


def _rmtree(path: Path) -> None:
    for child in path.iterdir():
        if child.is_dir():
            _rmtree(child)
        else:
            child.unlink()
    path.rmdir()


def _safe_filename(key: str) -> str:
    return key.replace("/", "_").replace("\\", "_")


def _function_key(func: Callable[..., Any]) -> str:
    qualname = func.__qualname__
    filename = func.__code__.co_filename
    path = Path(filename)
    if func.__module__ == "__main__" or path.suffix == ".py":
        return f"{path.resolve().stem}.{qualname}"
    return f"{func.__module__}.{qualname}"


def _normalize_source(source: str) -> str:
    return "\n".join(line.rstrip() for line in source.splitlines())


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def _function_source(func: Callable[..., Any]) -> str:
    try:
        return _normalize_source(inspect.getsource(func))
    except OSError as exc:
        raise TypeError(f"Cannot cache {func.__qualname__}: unable to read source") from exc


def _module_path(func: Callable[..., Any]) -> Path:
    path = Path(func.__code__.co_filename)
    if not path.exists():
        raise TypeError(f"Cannot cache {func.__qualname__}: source file {path} not found")
    return path.resolve()


def _parse_module(path: Path) -> tuple[str, ast.Module]:
    source = path.read_text(encoding="utf-8")
    return source, ast.parse(source, filename=str(path))


def _index_module_functions(module: ast.Module, module_source: str) -> dict[str, str]:
    """Map 'func' and 'Class.method' to normalized source text."""
    functions: dict[str, str] = {}

    for node in module.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            segment = ast.get_source_segment(module_source, node)
            if segment is not None:
                functions[node.name] = _normalize_source(segment)
        elif isinstance(node, ast.ClassDef):
            for item in node.body:
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    segment = ast.get_source_segment(module_source, item)
                    if segment is not None:
                        functions[f"{node.name}.{item.name}"] = _normalize_source(segment)

    return functions


def _find_function_node(module: ast.Module, qualname: str) -> ast.FunctionDef | ast.AsyncFunctionDef:
    parts = qualname.split(".")
    if len(parts) == 1:
        for node in module.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == parts[0]:
                return node
        raise TypeError(f"Cannot find function node for {qualname}")

    if len(parts) == 2:
        class_name, func_name = parts
        for node in module.body:
            if isinstance(node, ast.ClassDef) and node.name == class_name:
                for item in node.body:
                    if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)) and item.name == func_name:
                        return item
        raise TypeError(f"Cannot find method node for {qualname}")

    raise TypeError(f"Nested qualnames are not supported for caching: {qualname}")


def _extract_call_names(node: ast.AST) -> set[str]:
    """Extract simple names invoked by a Call's func node."""
    if isinstance(node, ast.Name):
        return {node.id}
    if isinstance(node, ast.Attribute):
        names = {node.attr}
        if isinstance(node.value, ast.Name):
            names.add(node.value.id)
        return names
    return set()


def _collect_callee_names(func_node: ast.FunctionDef | ast.AsyncFunctionDef) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(func_node):
        if isinstance(node, ast.Call):
            names.update(_extract_call_names(node.func))
    return names


def _resolve_callees(
    callee_names: set[str],
    module_functions: dict[str, str],
    qualname: str,
) -> dict[str, str]:
    """Resolve callee names to source from the same module."""
    resolved: dict[str, str] = {}
    class_prefix = qualname.rsplit(".", 1)[0] if "." in qualname else None

    for name in sorted(callee_names):
        if name in {"self", "cls"}:
            continue
        if name in module_functions:
            resolved[name] = module_functions[name]
            continue
        if class_prefix and f"{class_prefix}.{name}" in module_functions:
            resolved[f"{class_prefix}.{name}"] = module_functions[f"{class_prefix}.{name}"]

    return resolved


def _script_dir(func: Callable[..., Any]) -> Path:
    """Return the directory containing the script that defines func."""
    return _module_path(func).parent.resolve()


def _is_trackable_import(path: Path, script_dir: Path) -> bool:
    """Return True if a loaded module file should affect cache invalidation."""
    path = path.resolve()
    parts = path.parts
    if "site-packages" in parts or "dist-packages" in parts:
        return False
    if path.suffix != ".py":
        return False
    return path.parent == script_dir


def _collect_runtime_import_paths(script_dir: Path) -> set[Path]:
    """Collect .py files for modules loaded from the same folder as the script."""
    paths: set[Path] = set()

    for module in sys.modules.values():
        file = getattr(module, "__file__", None)
        if not file or not str(file).endswith(".py"):
            continue
        path = Path(file).resolve()
        if not path.exists():
            continue
        if _is_trackable_import(path, script_dir):
            paths.add(path)

    return paths


def _file_content_hash(path: Path) -> str:
    """Return a stable hash of a file's contents."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _collect_import_file_hashes(func: Callable[..., Any]) -> dict[str, str]:
    """Hash same-folder modules that are already loaded in sys.modules."""
    script_dir = _script_dir(func)
    own_file = _module_path(func)

    import_paths = _collect_runtime_import_paths(script_dir)
    import_paths.discard(own_file)

    return {
        str(import_path): _file_content_hash(import_path)
        for import_path in sorted(import_paths)
        if import_path.exists()
    }


def _version_hash(func: Callable[..., Any]) -> str:
    """Hash decorated function source, callees, and same-folder imports in sys.modules."""
    path = _module_path(func)
    module_source, module_tree = _parse_module(path)
    module_functions = _index_module_functions(module_tree, module_source)
    func_node = _find_function_node(module_tree, func.__qualname__)
    func_source = module_functions.get(func.__qualname__)
    if func_source is None:
        func_source = _function_source(func)
    callee_names = _collect_callee_names(func_node)
    callees = _resolve_callees(callee_names, module_functions, func.__qualname__)
    import_hashes = _collect_import_file_hashes(func)

    parts = [f"def:{func_source}"]
    for name in sorted(callees):
        parts.append(f"callee:{name}\n{callees[name]}")
    for import_path in sorted(import_hashes):
        parts.append(f"import:{import_path}\n{import_hashes[import_path]}")
    return _sha256("\n---\n".join(parts))


def _serialize_args(args: tuple[Any, ...], kwargs: dict[str, Any]) -> bytes:
    payload = {"args": args, "kwargs": kwargs}
    try:
        return json.dumps(payload, sort_keys=True, default=_json_default).encode()
    except TypeError:
        pass
    try:
        return pickle.dumps(payload, protocol=pickle.HIGHEST_PROTOCOL)
    except pickle.PicklingError as exc:
        raise TypeError(
            "Cannot cache call: arguments are not JSON- or pickle-serializable"
        ) from exc


def _json_default(obj: Any) -> Any:
    if isinstance(obj, Path):
        return str(obj)
    raise TypeError(f"Object of type {type(obj).__name__} is not JSON serializable")


def _args_hash(args: tuple[Any, ...], kwargs: dict[str, Any]) -> str:
    return hashlib.sha256(_serialize_args(args, kwargs)).hexdigest()


def _meta_path(root: Path, func_key: str) -> Path:
    return root / "meta" / f"{_safe_filename(func_key)}.json"


def _data_dir(root: Path, func_key: str) -> Path:
    return root / "data" / _safe_filename(func_key)


def _entry_path(root: Path, func_key: str, args_hash: str) -> Path:
    return _data_dir(root, func_key) / f"{args_hash}.pkl"


def _lock_file(path: Path) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_CREAT | os.O_RDWR)
    fcntl.flock(fd, fcntl.LOCK_EX)
    return fd


def _unlock_file(fd: int) -> None:
    fcntl.flock(fd, fcntl.LOCK_UN)
    os.close(fd)


def _ensure_version(root: Path, func_key: str, meta_path: Path, version_hash: str) -> None:
    lock_path = root / "locks" / f"{_safe_filename(func_key)}.lock"
    fd = _lock_file(lock_path)
    try:
        meta = _read_meta(meta_path)
        if meta.get("version_hash") == version_hash:
            return

        data_dir = _data_dir(root, func_key)
        if data_dir.exists():
            _rmtree(data_dir)

        meta_path.parent.mkdir(parents=True, exist_ok=True)
        _write_meta(
            meta_path,
            {
                "qualified_name": func_key,
                "version_hash": version_hash,
                "updated_at": _utcnow().isoformat(),
            },
        )
    finally:
        _unlock_file(fd)


def _read_meta(meta_path: Path) -> dict[str, Any]:
    if not meta_path.exists():
        return {}
    return json.loads(meta_path.read_text(encoding="utf-8"))


def _write_meta(meta_path: Path, payload: dict[str, Any]) -> None:
    _atomic_write(meta_path, json.dumps(payload, indent=2).encode("utf-8"))


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _parse_timestamp(value: str) -> datetime:
    return datetime.fromisoformat(value)


def _entry_expired(created_at: str | None, ttl: timedelta = DEFAULT_TTL) -> bool:
    if not created_at:
        return True
    return _utcnow() - _parse_timestamp(created_at) >= ttl


def _load_entry(entry_path: Path, version_hash: str, args_hash: str) -> Any | None:
    if not entry_path.exists():
        return None

    with entry_path.open("rb") as handle:
        payload = pickle.load(handle)

    if payload.get("version_hash") != version_hash or payload.get("args_hash") != args_hash:
        return None
    if _entry_expired(payload.get("created_at")):
        entry_path.unlink(missing_ok=True)
        return None
    return payload.get("value")


def _save_entry(entry_path: Path, value: Any, version_hash: str, args_hash: str) -> None:
    payload = {
        "value": value,
        "version_hash": version_hash,
        "args_hash": args_hash,
        "created_at": _utcnow().isoformat(),
    }
    try:
        data = pickle.dumps(payload, protocol=pickle.HIGHEST_PROTOCOL)
    except pickle.PicklingError as exc:
        raise TypeError("Cannot cache return value: not pickle-serializable") from exc

    entry_path.parent.mkdir(parents=True, exist_ok=True)
    _atomic_write(entry_path, data)


def _atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    tmp_path.write_bytes(data)
    os.replace(tmp_path, path)
