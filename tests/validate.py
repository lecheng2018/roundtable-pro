#!/usr/bin/env python3
"""Validate the roundtable-pro plugin structure and integrity.

Usage:
    python3 tests/validate.py          # auto-detect plugin dir
    python3 tests/validate.py /path/to/roundtable-pro  # explicit path
"""

import json
import os
import re
import sys
from pathlib import Path


def find_plugin_dir() -> Path:
    """Auto-detect plugin directory (walk up from tests/ or cwd)."""
    candidate = Path(__file__).resolve().parent.parent
    if (candidate / "plugin.json").exists():
        return candidate
    return Path.cwd()


def check(ok: bool, msg: str) -> bool:
    """Print check result and return ok."""
    prefix = "✅" if ok else "❌"
    print(f"  {prefix}  {msg}")
    return ok


def validate_plugin_json(plugin_dir: Path) -> bool:
    """Validate plugin.json manifest."""
    path = plugin_dir / "plugin.json"
    if not path.exists():
        return check(False, "plugin.json not found")

    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        return check(False, f"plugin.json invalid JSON: {e}")

    ok = True
    for field in ("id", "name", "version"):
        if field not in manifest or not manifest[field]:
            ok &= check(False, f"plugin.json missing/empty field: {field}")
        else:
            ok &= check(True, f"plugin.json: {field} = {manifest[field]}")

    # entry.backend
    entry = manifest.get("entry", {})
    be = entry.get("backend", "")
    if be:
        ok &= check((plugin_dir / be).exists(), f"entry.backend '{be}' exists")
    else:
        ok &= check(False, "entry.backend missing")
    
    fe = entry.get("frontend", "")
    if fe:
        ok &= check((plugin_dir / fe).exists(), f"entry.frontend '{fe}' exists")
    else:
        # frontend is optional for our plugin
        check(True, "entry.frontend not set (optional for us)")

    min_ver = manifest.get("min_version", "")
    if min_ver:
        check(True, f"min_version = {min_ver}")

    # Check .qwenpaw-plugin/plugin.json also exists
    qp_path = plugin_dir / ".qwenpaw-plugin" / "plugin.json"
    if qp_path.exists():
        check(True, ".qwenpaw-plugin/plugin.json exists")
    else:
        check(False, ".qwenpaw-plugin/plugin.json NOT found")

    return ok


def validate_backend(plugin_dir: Path) -> bool:
    """Validate main.py can be imported (syntax check)."""
    main_py = plugin_dir / "main.py"
    if not main_py.exists():
        return check(False, "main.py not found")

    try:
        compile(main_py.read_text(encoding="utf-8"), "main.py", "exec")
        check(True, "main.py compiles OK")
    except SyntaxError as e:
        return check(False, f"main.py syntax error: {e}")

    # Check all .py files
    ok = True
    for py_file in sorted(plugin_dir.glob("*.py")):
        try:
            compile(py_file.read_text(encoding="utf-8"), py_file.name, "exec")
        except SyntaxError as e:
            ok &= check(False, f"{py_file.name} syntax error: {e}")
    if ok:
        check(True, "All Python files compile OK")

    # Check required functions are defined
    source = main_py.read_text(encoding="utf-8")
    required = [
        ("_on_startup", "startup hook"),
        ("_on_uninstall", "uninstall hook"),
        ("class RoundTableProPlugin", "plugin entry class"),
        ("def register", "register method"),
    ]
    for func_name, desc in required:
        check(func_name in source, f"main.py defines '{func_name}' ({desc})")

    # Check hooks are registered
    for hook in ("register_startup_hook", "register_uninstall_hook", "register_http_router"):
        check(hook in source, f"main.py calls '{hook}'")

    return ok


def validate_frontend(plugin_dir: Path) -> bool:
    """Validate frontend files exist."""
    fe_dir = plugin_dir / "frontend"
    if not fe_dir.exists():
        return check(False, "frontend/ directory not found")

    ok = True
    html = fe_dir / "index.html"
    if html.exists():
        size = len(html.read_bytes())
        check(True, f"frontend/index.html ({size} bytes)")
        # Check critical functions exist
        content = html.read_text(encoding="utf-8")
        for func in ("startDiscussion", "loadProviders", "loadDebaters", "handleSSEEvent", "api"):
            if func in content:
                check(True, f"frontend defines '{func}'")
            else:
                ok &= check(False, f"frontend MISSING '{func}'")
    else:
        ok &= check(False, "frontend/index.html not found")

    js = fe_dir / "entry.js"
    if js.exists():
        check(True, f"frontend/entry.js ({len(js.read_bytes())} bytes)")
    
    return ok


def validate_personas(plugin_dir: Path) -> bool:
    """Validate all persona templates."""
    personas_dir = plugin_dir / "personas"
    if not personas_dir.exists():
        return check(False, "personas/ directory not found")

    json_files = sorted(personas_dir.glob("*.json"))
    if not json_files:
        return check(False, "No persona JSON files found")

    ok = True
    for f in json_files:
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            required = ("name", "description", "suggested_provider", "suggested_model")
            missing = [r for r in required if r not in data or not data[r]]
            if missing:
                ok &= check(False, f"{f.name}: missing fields {missing}")
            else:
                check(True, f"{f.name}: {data.get('name', '?')}")
        except json.JSONDecodeError as e:
            ok &= check(False, f"{f.name}: invalid JSON: {e}")

    # Check readme exists
    readme = personas_dir / "readme.md"
    if readme.exists():
        check(True, "personas/readme.md exists")
    else:
        ok &= check(False, "personas/readme.md MISSING")

    check(True, f"{len(json_files)} persona templates")
    return ok


def validate_models(plugin_dir: Path) -> bool:
    """Validate models.py data models."""
    models_py = plugin_dir / "models.py"
    if not models_py.exists():
        return check(False, "models.py not found")

    source = models_py.read_text(encoding="utf-8")
    expected_classes = [
        "AgentConfig", "DiscussRequest", "DebaterCreateRequest",
        "DebaterAgent", "RoundConfig", "Discussion", "Message",
    ]
    ok = True
    for cls in expected_classes:
        if f"class {cls}" in source:
            check(True, f"models.py defines '{cls}'")
        else:
            ok &= check(False, f"models.py MISSING '{cls}'")
    return ok


def validate_discussion_engine(plugin_dir: Path) -> bool:
    """Validate discussion engine files."""
    engine_py = plugin_dir / "engine.py"
    if not engine_py.exists():
        return check(False, "engine.py not found")

    source = engine_py.read_text(encoding="utf-8")
    ok = True

    required_funcs = [
        ("_safe_parse_json", "JSON parsing with fallback"),
        ("call_model", "model invocation"),
        ("get_agent_response", "agent response"),
        ("host_config", "auto-config generation"),
        ("run_roundtable", "discussion loop"),
    ]
    for func, desc in required_funcs:
        if f"async def {func}" in source or f"def {func}" in source:
            check(True, f"engine.py defines '{func}' ({desc})")
        else:
            ok &= check(False, f"engine.py MISSING '{func}' ({desc})")

    # Check brainstorm.py
    bs_py = plugin_dir / "brainstorm.py"
    if bs_py.exists():
        source_bs = bs_py.read_text(encoding="utf-8")
        if "async def run_brainstorm" in source_bs:
            check(True, "brainstorm.py defines 'run_brainstorm'")
        else:
            ok &= check(False, "brainstorm.py MISSING 'run_brainstorm'")
    else:
        ok &= check(False, "brainstorm.py not found")

    return ok


def validate_data_dir(plugin_dir: Path) -> bool:
    """Validate data directory is writable."""
    data_dir = plugin_dir / "data"
    try:
        data_dir.mkdir(exist_ok=True)
        test_file = data_dir / ".write_test"
        test_file.write_text("ok")
        test_file.unlink()
        check(True, "data/ directory writable")
        return True
    except (OSError, PermissionError) as e:
        return check(False, f"data/ NOT writable: {e}")


def validate_storage(plugin_dir: Path) -> bool:
    """Validate storage module."""
    storage_py = plugin_dir / "storage.py"
    if not storage_py.exists():
        return check(False, "storage.py not found")

    source = storage_py.read_text(encoding="utf-8")
    ok = True
    for method in ("save", "get", "list", "delete"):
        if f"def {method}" in source:
            check(True, f"storage.py defines '{method}'")
        else:
            ok &= check(False, f"storage.py MISSING '{method}'")
    return ok


def run_all(plugin_dir: Path) -> int:
    """Run all validation checks. Returns exit code (0 = pass)."""
    print(f"\n🔍  Validating roundtable-pro plugin")
    print(f"   📁  {plugin_dir}")
    print(f"   ⏱  {__import__('datetime').datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print()

    checks = [
        ("📋  Plugin manifest", validate_plugin_json),
        ("⚙️   Backend", validate_backend),
        ("🎨  Frontend", validate_frontend),
        ("👤  Persona templates", validate_personas),
        ("📐  Data models", validate_models),
        ("🧠  Discussion engine", validate_discussion_engine),
        ("💾  Storage", validate_storage),
        ("📁  Data directory", validate_data_dir),
    ]

    total = passed = 0
    for label, func in checks:
        print(f"── {label} {'─' * max(0, 48 - len(label))}──")
        result = func(plugin_dir)
        total += 1
        if result:
            passed += 1
        print()

    print(f"{'─' * 56}")
    print(f"  {'✅' if passed == total else '❌'}  {passed}/{total} checks passed")
    print()
    return 0 if passed == total else 1


if __name__ == "__main__":
    plugin_dir = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else find_plugin_dir()
    if not (plugin_dir / "plugin.json").exists():
        print(f"❌ Not a plugin directory (no plugin.json): {plugin_dir}")
        sys.exit(1)
    sys.exit(run_all(plugin_dir))
