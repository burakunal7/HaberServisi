"""Ajans durum kayıt merkezi + panel log tamponu (thread-güvenli)."""
from __future__ import annotations

import collections
import datetime as _dt
import logging
import threading
from dataclasses import dataclass, field, asdict
from typing import Optional


def _now() -> str:
    return _dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


@dataclass
class AgencyStatus:
    name: str
    enabled: bool = True
    kind: str = "Çekici"
    state: str = "idle"                 # idle | running | error | disabled
    output_dir: str = ""
    last_title: str = ""
    last_check: Optional[str] = None
    last_run: Optional[str] = None
    last_success: Optional[str] = None
    last_error: Optional[str] = None
    last_error_time: Optional[str] = None
    written_total: int = 0
    written_last: int = 0
    seen_total: int = 0
    failures: int = 0
    next_run: Optional[str] = None


class StatusRegistry:
    def __init__(self):
        self._lock = threading.RLock()
        self._agencies: dict[str, AgencyStatus] = {}
        self.logs: collections.deque = collections.deque(maxlen=400)

    def register(self, name: str, enabled: bool, output_dir: str, kind: str = "Çekici") -> None:
        with self._lock:
            self._agencies[name] = AgencyStatus(name=name, enabled=enabled, kind=kind,
                                                output_dir=output_dir,
                                                state="idle" if enabled else "disabled")

    def reset_agencies(self) -> None:
        with self._lock:
            self._agencies.clear()

    def get(self, name: str) -> AgencyStatus:
        with self._lock:
            return self._agencies[name]

    def update(self, name: str, **kw) -> None:
        with self._lock:
            st = self._agencies[name]
            for k, v in kw.items():
                setattr(st, k, v)

    def snapshot(self) -> list[dict]:
        with self._lock:
            return [asdict(st) for st in self._agencies.values()]

    def add_log(self, line: str) -> None:
        with self._lock:
            self.logs.append(line)

    def recent_logs(self, n: int = 200) -> list[str]:
        with self._lock:
            return list(self.logs)[-n:]


class RegistryLogHandler(logging.Handler):
    def __init__(self, registry: StatusRegistry):
        super().__init__()
        self.registry = registry

    def emit(self, record: logging.LogRecord) -> None:
        try:
            self.registry.add_log(self.format(record))
        except Exception:
            pass
