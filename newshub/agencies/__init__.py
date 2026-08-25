"""Ajans adaptörleri."""
from __future__ import annotations

from .base import Agency
from .anka import AnkaAgency
from .aa import AaAgency
from .watchdog import WatchdogAgent

REGISTRY: dict[str, type[Agency]] = {
    "ankahaber": AnkaAgency,
    "aa": AaAgency,
    "watchdog": WatchdogAgent,
}


def build_agency(cfg: dict) -> Agency:
    kind = cfg.get("type")
    if kind not in REGISTRY:
        raise ValueError(
            f"Bilinmeyen ajans tipi: {kind!r}. Tanımlı olanlar: {list(REGISTRY)}"
        )
    return REGISTRY[kind](cfg)
