import json
from datetime import datetime
from .models import Discussion


class Storage:
    _data: dict = {}

    def save(self, d: Discussion):
        self._data[d.hid] = d

    def get(self, hid: str) -> Discussion | None:
        return self._data.get(hid)

    def list_all(self) -> list:
        return sorted(self._data.values(), key=lambda x: x.created_at, reverse=True)
