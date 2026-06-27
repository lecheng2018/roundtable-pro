import json


class EventStream:
    def __init__(self):
        self._closed = False

    async def emit(self, event: str, data: dict):
        if self._closed:
            return
        yield f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"

    def close(self):
        self._closed = True