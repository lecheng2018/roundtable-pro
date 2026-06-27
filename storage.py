import json
import os
import threading
from datetime import datetime
from pathlib import Path
from .models import Discussion


class Storage:
    """Persistent storage for discussion history backed by a JSON file."""

    def __init__(self, data_dir: str = ""):
        if data_dir:
            self._data_dir = Path(data_dir)
        else:
            self._data_dir = Path(__file__).resolve().parent / "data"
        self._data_dir.mkdir(parents=True, exist_ok=True)
        self._file = self._data_dir / "discussions.json"
        self._lock = threading.Lock()
        self._data: dict[str, dict] = {}
        self._load()

    # ── File I/O ─────────────────────────────────────────────────

    def _load(self):
        """Load discussions from JSON file."""
        if self._file.exists():
            try:
                with open(self._file, "r", encoding="utf-8") as f:
                    raw = json.load(f)
                self._data = raw.get("discussions", {})
            except (json.JSONDecodeError, KeyError):
                self._data = {}
        else:
            self._data = {}

    def _save(self):
        """Persist discussions to JSON file."""
        with self._lock:
            with open(self._file, "w", encoding="utf-8") as f:
                json.dump({"discussions": self._data}, f, ensure_ascii=False, indent=2, default=str)

    # ── CRUD ─────────────────────────────────────────────────────

    def save(self, d: Discussion):
        """Save or update a discussion."""
        self._data[d.hid] = d.model_dump()
        self._save()

    def get(self, hid: str) -> Discussion | None:
        """Retrieve a discussion by HID."""
        raw = self._data.get(hid)
        if raw is None:
            return None
        return Discussion(**raw)

    def list_all(self) -> list:
        """Return all discussions sorted by created_at descending."""
        items = []
        for raw in self._data.values():
            try:
                items.append(Discussion(**raw))
            except Exception:
                continue
        return sorted(items, key=lambda x: x.created_at, reverse=True)

    def delete(self, hid: str):
        """Delete a discussion by HID."""
        self._data.pop(hid, None)
        self._save()
