"""Config yükleme, loglama ve tek-tur (bakım/test) çalıştırma."""
from __future__ import annotations

import logging
import logging.handlers
from pathlib import Path

import yaml

from .agencies import build_agency
from .state import SeenStore


def load_config(path: str) -> dict:
    return yaml.safe_load(Path(path).read_text(encoding="utf-8"))


def setup_logging(log_dir: str, extra_handler: logging.Handler | None = None) -> None:
    Path(log_dir).mkdir(parents=True, exist_ok=True)
    fmt = logging.Formatter("%(asctime)s │ %(name)-8s │ %(message)s", datefmt="%H:%M:%S")

    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.handlers.clear()

    console = logging.StreamHandler()
    console.setFormatter(fmt)
    root.addHandler(console)

    fileh = logging.handlers.TimedRotatingFileHandler(
        Path(log_dir) / "service.log", when="midnight", backupCount=14, encoding="utf-8"
    )
    fileh.setFormatter(fmt)
    root.addHandler(fileh)

    if extra_handler is not None:
        extra_handler.setFormatter(fmt)
        root.addHandler(extra_handler)

    for noisy in ("werkzeug", "waitress", "waitress.queue", "urllib3"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def build_enabled_agencies(cfg: dict, agency_filter: str = "") -> list:
    agencies = [build_agency(a) for a in cfg.get("agencies", []) if a.get("enabled", True)]
    if agency_filter:
        agencies = [a for a in agencies if a.name.lower() == agency_filter.lower()]
    return agencies


def run_agency_cycle(agency, seen: SeenStore, limit: int = 0,
                     download_media: bool = True, on_item=None) -> int:
    return agency.cycle(seen, limit=limit, download_media=download_media, on_item=on_item)


def run_once(config: str, agency_filter: str, limit: int, no_media: bool) -> None:
    cfg = load_config(config)
    g = cfg.get("global", {})
    setup_logging(g.get("log_dir", "logs"))
    log = logging.getLogger("runner")

    seen = SeenStore(g.get("state_db", "state.sqlite3"))
    agencies = build_enabled_agencies(cfg, agency_filter)
    log.info("Tek tur. Ajanslar: %s", [a.name for a in agencies])
    for agency in agencies:
        try:
            n = run_agency_cycle(agency, seen, limit=limit, download_media=not no_media)
            log.info("%s: %d yeni haber (toplam görülen: %d)", agency.name, n, seen.count(agency.name))
        except Exception as e:
            log.error("%s turu başarısız: %s", agency.name, e)
