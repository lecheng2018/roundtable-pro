#!/usr/bin/env python3
"""Validate the roundtable-pro plugin structure and integrity.

Usage:
    python3 tests/validate.py          # auto-detect plugin dir
    python3 tests/validate.py /path    # explicit path
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
    prefix = "✅" if ok else "❌"
    print(f"  {prefix}  {msg}")
    return ok


def list_missing(expected: list, actual: list) -> str:
    missing = [x for x in expected if x not in actual]
    return ", ".join(missing) if missing else ""


def validate_manifest(plugin_dir: Path) -> bool:
    ok = True
    # Outer plugin.json
    outer = plugin_dir / "plugin.json"
    if outer.exists():
        ok &= check(True, "plugin.json (outer) exists")
        try:
            data = json.loads(outer.read_text(encoding="utf-8"))
            for field in ["id", "name", "version", "entry"]:
                ok &= check(field in data, f"plugin.json: contains '{field}'")
            if "entry" in data:
                entry = data["entry"]
                ok &= check("backend" in entry, "plugin.json: entry.backend")
                ok &= check("frontend" in entry, "plugin.json: entry.frontend")
        except json.JSONDecodeError as e:
            ok &= check(False, f"plugin.json: invalid JSON ({e})")
    else:
        ok &= check(False, "plugin.json NOT found")

    # Inner .qwenpaw-plugin/plugin.json
    inner = plugin_dir / ".qwenpaw-plugin" / "plugin.json"
    if inner.exists():
        ok &= check(True, ".qwenpaw-plugin/plugin.json (inner) exists")
        try:
            data = json.loads(inner.read_text(encoding="utf-8"))
            for field in ["id", "name", "version", "entry"]:
                ok &= check(field in data, f".qwenpaw-plugin/plugin.json: contains '{field}'")
            extras = ["description_i18n", "meta", "min_version"]
            found = [f for f in extras if f in data]
            ok &= check(
                len(found) >= 2,
                f".qwenpaw-plugin/plugin.json: advanced fields ({', '.join(found)})"
            )
        except json.JSONDecodeError as e:
            ok &= check(False, f".qwenpaw-plugin/plugin.json: invalid JSON ({e})")
    else:
        ok &= check(False, ".qwenpaw-plugin/plugin.json NOT found")

    return ok


def validate_entry_files(plugin_dir: Path, manifest: dict) -> bool:
    ok = True
    entry = manifest.get("entry", {})
    backend = entry.get("backend", "main.py")
    frontend = entry.get("frontend", "frontend/index.html")

    be_path = plugin_dir / backend
    ok &= check(be_path.exists(), f"entry.backend '{backend}' exists")

    fe_path = plugin_dir / frontend
    ok &= check(fe_path.exists(), f"entry.frontend '{frontend}' exists")

    return ok


def validate_backend(plugin_dir: Path) -> bool:
    ok = True
    main_py = plugin_dir / "main.py"
    if not main_py.exists():
        return check(False, "main.py not found")

    try:
        compile(main_py.read_text(encoding="utf-8"), "main.py", "exec")
        ok &= check(True, "main.py compiles OK")
    except SyntaxError as e:
        ok &= check(False, f"main.py syntax error: {e}")

    # All Python files compile
    py_files = list(plugin_dir.glob("*.py")) + list(plugin_dir.glob("tests/*.py"))
    py_files = [f for f in py_files if f.name != "__init__.py" or not f.exists()]
    all_ok = True
    for f in sorted(py_files):
        try:
            compile(f.read_text(encoding="utf-8"), f.name, "exec")
        except SyntaxError as e:
            check(False, f"{f.name} syntax error: {e}")
            all_ok = False
    ok &= check(all_ok, f"All {len(py_files)} Python files compile OK")

    # Check required entry points
    main_text = main_py.read_text(encoding="utf-8")
    required = [
        ("_on_startup", "startup hook"),
        ("_on_uninstall", "uninstall hook"),
        ("RoundTableProPlugin", "plugin entry class"),
        ("def register", "register method"),
    ]
    for symbol, desc in required:
        ok &= check(symbol in main_text, f"main.py defines '{symbol}' ({desc})")

    # Check hook registration calls
    hooks = ["register_startup_hook", "register_uninstall_hook", "register_http_router"]
    for hook in hooks:
        ok &= check(hook in main_text, f"main.py calls '{hook}'")

    return ok


def validate_frontend(plugin_dir: Path) -> bool:
    ok = True
    index = plugin_dir / "frontend" / "index.html"
    if not index.exists():
        return check(False, "frontend/index.html NOT found")

    size = os.path.getsize(str(index))
    ok &= check(size > 1000, f"frontend/index.html ({size} bytes)")
    html = index.read_text(encoding="utf-8")

    # Required JS function definitions
    required_functions = [
        "startDiscussion", "loadProviders", "loadDebaters",
        "populateProviderSelects", "populateJudgeProvider",
    ]
    for fn in required_functions:
        ok &= check(f"function {fn}" in html or f"async function {fn}" in html,
                     f"frontend defines '{fn}'")

    # Entry.js (second frontend entry)
    entry_js = plugin_dir / "frontend" / "entry.js"
    if entry_js.exists():
        ok &= check(True, "frontend/entry.js exists")
    else:
        ok &= check(False, "frontend/entry.js NOT found (may be optional)")

    return ok


def validate_personas(plugin_dir: Path) -> bool:
    ok = True
    personas_dir = plugin_dir / "personas"
    if not personas_dir.exists():
        return check(False, "personas/ directory NOT found")

    json_files = sorted(personas_dir.glob("*.json"))
    ok &= check(len(json_files) >= 1, f"personas/: {len(json_files)} JSON files")

    all_valid = True
    for f in json_files:
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            checks = []
            for field in ["id", "name", "description", "suggested_provider", "suggested_model"]:
                checks.append(field in data)
            is_valid = all(checks)
            if not is_valid:
                missing = [field for field in ["id", "name", "description", "suggested_provider", "suggested_model"]
                          if field not in data]
                check(False, f"{f.name}: missing fields: {', '.join(missing)}")
                all_valid = False
        except json.JSONDecodeError as e:
            check(False, f"{f.name}: invalid JSON ({e})")
            all_valid = False
    ok &= check(all_valid, f"All {len(json_files)} persona JSONs valid")

    return ok


def validate_data_dir(plugin_dir: Path) -> bool:
    """Check data directory exists (optional, created at startup)."""
    data_dir = plugin_dir / "data"
    if data_dir.exists():
        return check(True, "data/ directory exists")
    else:
        return check(True, "data/ directory auto-created at startup")


def validate_state_file(plugin_dir: Path) -> bool:
    state = plugin_dir / ".qwenpaw-roundtable-pro-state.json"
    if state.exists():
        return check(True, ".qwenpaw-roundtable-pro-state.json exists")
    else:
        return check(True, "state file auto-created on first startup")


def validate_readme(plugin_dir: Path) -> bool:
    readme = plugin_dir / "README.md"
    if readme.exists():
        size = os.path.getsize(str(readme))
        return check(size > 100, f"README.md ({size} bytes)")
    return check(False, "README.md NOT found")


def main():
    if len(sys.argv) > 1:
        plugin_dir = Path(sys.argv[1]).resolve()
    else:
        plugin_dir = find_plugin_dir()

    if not (plugin_dir / "main.py").exists():
        print(f"❌  Not a roundtable-pro plugin directory: {plugin_dir}")
        sys.exit(1)

    print(f"🔍  Validating roundtable-pro plugin")
    print(f"   📁  {plugin_dir}")
    print(f"   ⏱  {__import__('datetime').datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print()

    all_ok = True

    print(" ── 📋  Plugin manifest ────────────────────────────────")
    all_ok &= validate_manifest(plugin_dir)
    print()

    print(" ── ⚙️   Backend ──────────────────────────────────────")
    all_ok &= validate_backend(plugin_dir)
    print()

    print(" ── 🎨  Frontend ───────────────────────────────────────")
    all_ok &= validate_frontend(plugin_dir)
    print()

    print(" ── 👤  Personas ───────────────────────────────────────")
    all_ok &= validate_personas(plugin_dir)
    print()

    print(" ── 📂  Data & State ───────────────────────────────────")
    all_ok &= validate_data_dir(plugin_dir)
    all_ok &= validate_state_file(plugin_dir)
    print()

    print(" ── 📖  Documentation ──────────────────────────────────")
    all_ok &= validate_readme(plugin_dir)
    print()

    if all_ok:
        print(" ✅  All checks passed!")
    else:
        print(" ❌  Some checks failed. See above.")
        sys.exit(1)


if __name__ == "__main__":
    main()
