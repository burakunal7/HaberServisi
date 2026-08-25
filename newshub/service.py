"""Servis çekirdeği: her ajans kendi thread'inde paralel döner, panelden yönetilir.

Yavaş bir ajans hızlıyı bekletmez; biri çökse diğerleri etkilenmez (hata panele
düşer, tur tekrar denenir). Config değişince reload() worker'ları tazeler.
"""
from __future__ import annotations

import datetime as _dt
import logging
import os
import threading
import time
from pathlib import Path

from .agencies import build_agency
from .runner import load_config, run_agency_cycle, setup_logging
from .state import SeenStore
from .status import RegistryLogHandler, StatusRegistry
from .web import create_app


def _now() -> str:
    return _dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


class AgencyWorker(threading.Thread):
    def __init__(self, agency, seen: SeenStore, registry: StatusRegistry, poll: int,
                 download_media: bool = True):
        super().__init__(daemon=True, name=f"worker-{agency.name}")
        self.agency = agency
        self.seen = seen
        self.registry = registry
        self.poll = poll
        self.download_media = download_media
        self._stop_ev = threading.Event()
        self._wake = threading.Event()

    def run(self) -> None:
        name = self.agency.name
        self.agency._abort = self._stop_ev.is_set
        while not self._stop_ev.is_set():
            got, is_watchdog = 0, False
            try:
                got, is_watchdog = self._run_once(name)
            except Exception as e:
                # Worker asla ölmesin: beklenmedik hatada bile logla ve devam et
                try:
                    self.registry.update(name, state="error", last_error=str(e),
                                         last_error_time=_now(), last_check=_now())
                except Exception:
                    pass
                try:
                    self.agency.log.error("worker beklenmedik hata: %s", e)
                except Exception:
                    pass
            # Çekiciler: yeni haber geldiyse hemen tekrar bak. Watchdog kurtarma
            # sonrası exe'ye süre tanımak için bekler.
            if not (got > 0 and not is_watchdog):
                self._wake.wait(timeout=self.poll)
                self._wake.clear()

    def _run_once(self, name: str):
        try:
            st = self.registry.get(name)
        except KeyError:
            return 0, False   # reload sırasında kayıt yenileniyor olabilir
        if not st.enabled:
            self.registry.update(name, state="disabled")
            return 0, False

        self.registry.update(name, state="running", last_run=_now())

        def on_progress(count, title, _n=name, _base=st.written_total):
            self.registry.update(_n, state="running", written_total=_base + count,
                                 last_title=title, last_check=_now(), last_success=_now())
        try:
            got = run_agency_cycle(self.agency, self.seen,
                                   download_media=self.download_media, on_item=on_progress)
        except Exception as e:
            self.registry.update(name, state="error", last_error=str(e),
                                 last_error_time=_now(), last_check=_now())
            self.agency.log.error("hata: %s", e)
            return 0, False

        ps = getattr(self.agency, "panel_state", None)
        if ps:  # watchdog: "bugün" = izlenen klasöre bugün düşen haber sayısı
            self.registry.update(
                name, written_last=got, written_total=ps.get("count", st.written_total),
                state=ps.get("state", "idle"),
                last_success=ps.get("last_success", st.last_success),
                last_error=ps.get("last_error"),
                last_title=ps.get("last_title", st.last_title), last_check=_now())
            return got, True
        self.registry.update(
            name, state="idle", written_last=got, written_total=st.written_total + got,
            last_success=(_now() if got else st.last_success),
            last_error=None, last_title=self.agency.last_title,
            seen_total=self.seen.count(name),
            failures=self.seen.failure_count(name), last_check=_now())
        return got, False

    def fetch_now(self) -> None:
        self._wake.set()

    def stop(self) -> None:
        self._stop_ev.set()
        self._wake.set()


def seed_seen(agencies, seen: SeenStore) -> dict[str, int]:
    """Hedef klasörlerdeki mevcut haberleri 'görüldü' işaretler (ilk kurulum)."""
    counts = {}
    for ag in agencies:
        ids = ag.existing_ids()
        for i in ids:
            seen.mark_seen(ag.name, i)
        counts[ag.name] = len(ids)
    return counts


def _delete_old(folder: Path, cutoff: float) -> tuple[int, int]:
    """folder içinde mtime<cutoff olan dosyaları siler (klasör yapısı korunur).
    (silinen, byte) döndürür."""
    deleted = 0
    freed = 0
    stack = [str(folder)]
    while stack:
        d = stack.pop()
        try:
            with os.scandir(d) as it:
                for e in it:
                    try:
                        if e.is_file(follow_symlinks=False):
                            stt = e.stat(follow_symlinks=False)
                            if stt.st_mtime < cutoff:
                                sz = stt.st_size
                                os.remove(e.path)
                                deleted += 1
                                freed += sz
                        elif e.is_dir(follow_symlinks=False):
                            stack.append(e.path)
                    except OSError:
                        pass
        except OSError:
            pass
    return deleted, freed


def cleanup_once(cfg: dict, log: logging.Logger) -> dict[str, int]:
    """Her ajans klasöründe retention_days'ten eski dosyaları sil.

    retention_days < 1 ise atlanır (taze silinmez); sürücü kökü/çok kısa yol reddedilir.
    """
    g = cfg.get("global", {})
    default_days = float(g.get("retention_days", 0) or 0)
    now = time.time()
    results = {}
    for a_cfg in cfg.get("agencies", []):
        name = a_cfg.get("name", "?")
        days = float(a_cfg.get("retention_days", default_days) or 0)
        if days < 1:
            continue
        folder_str = a_cfg.get("output_dir") or a_cfg.get("watch_dir")
        if not folder_str:
            continue
        folder = Path(folder_str)
        if len(folder.parts) < 2:            # sürücü kökü (D:\) reddedilir
            log.warning("🧹 %s: güvenlik — kök/kısa yol temizlenmez: %s", name, folder)
            continue
        if not folder.exists():
            continue
        cutoff = now - days * 86400
        deleted, freed = _delete_old(folder, cutoff)
        results[name] = deleted
        if deleted:
            log.info("🧹 %s: %d dosya silindi (%.0f günden eski, %.1f MB boşaldı)",
                     name, deleted, days, freed / 1048576)
    return results


class Service:
    """Kayıt + worker'lar + web. Config değişince reload() web'i kapatmadan tazeler."""

    def __init__(self, config_path: str):
        self.config_path = config_path
        self.registry = StatusRegistry()
        self.seen: SeenStore | None = None
        self.workers: dict[str, AgencyWorker] = {}
        self._lock = threading.Lock()
        self.log = logging.getLogger("service")
        self._cleanup_stop = threading.Event()
        # Panel girişi (config'de web_user/web_password varsa zorunlu). Boş = giriş yok.
        self.web_user = ""
        self.web_password = ""

    def _cleanup_loop(self) -> None:
        """Günlük retention: her gün cleanup_hour saatinde bir kez temizler."""
        while not self._cleanup_stop.is_set():
            try:
                cfg = load_config(self.config_path)
                g = cfg.get("global", {})
                hour = int(g.get("cleanup_hour", 4))
                today = _dt.date.today().isoformat()
                last = self.seen.get_checkpoint("_system", "last_cleanup_date") if self.seen else None
                if last != today and _dt.datetime.now().hour >= hour:
                    cleanup_once(cfg, self.log)
                    if self.seen:
                        self.seen.set_checkpoint("_system", "last_cleanup_date", today)
            except Exception as e:
                self.log.warning("temizlik döngüsü hatası: %s", e)
            self._cleanup_stop.wait(timeout=1800)

    def _load_auth(self, g: dict) -> None:
        self.web_user = str(g.get("web_user", "") or "")
        self.web_password = str(g.get("web_password", "") or "")

    def _spawn_workers(self, cfg: dict) -> None:
        g = cfg.get("global", {})
        default_poll = int(g.get("poll_interval_seconds", 60))
        media = bool(g.get("download_media", True))
        for a_cfg in cfg.get("agencies", []):
            try:
                agency = build_agency(a_cfg)
            except Exception as e:
                self.log.error("Ajans kurulamadı (%s): %s", a_cfg.get("name"), e)
                continue
            enabled = bool(a_cfg.get("enabled", True))
            kind = "Bekçi" if a_cfg.get("type") == "watchdog" else "Çekici"
            self.registry.register(agency.name, enabled=enabled,
                                   output_dir=str(agency.output_dir), kind=kind)
            poll = int(a_cfg.get("poll_interval_seconds", default_poll))
            worker = AgencyWorker(agency, self.seen, self.registry, poll, download_media=media)
            self.workers[agency.name] = worker
            worker.start()

    def start(self) -> None:
        cfg = load_config(self.config_path)
        g = cfg.get("global", {})
        setup_logging(g.get("log_dir", "logs"), extra_handler=RegistryLogHandler(self.registry))
        self._load_auth(g)
        self.seen = SeenStore(g.get("state_db", "state.sqlite3"))
        try:  # çok eski 'görüldü' kayıtlarını temizle (DB sınırsız şişmesin)
            pruned = self.seen.prune_old(int(g.get("seen_retention_days", 30)))
            if pruned:
                self.log.info("DB bakımı: %d eski kayıt temizlendi", pruned)
        except Exception as e:
            self.log.warning("DB bakımı atlandı: %s", e)
        self._spawn_workers(cfg)
        threading.Thread(target=self._cleanup_loop, daemon=True, name="cleanup").start()
        if self.web_user:
            self.log.info("Panel girişi AÇIK (kullanıcı: %s)", self.web_user)

        host = g.get("web_host", "0.0.0.0")
        port = int(g.get("web_port", 8770))
        self.log.info("─" * 46)
        self.log.info("Haber Toplama Servisi başladı")
        self.log.info("Ajanslar: %s", ", ".join(self.workers))
        self.log.info("Kumanda paneli → http://localhost:%d", port)
        self.log.info("─" * 46)

        app = create_app(self)
        try:
            from waitress import serve  # üretim WSGI sunucusu
            serve(app, host=host, port=port, threads=8, _quiet=True)
        except ImportError:
            app.run(host=host, port=port, threaded=True, use_reloader=False)

    def reload(self) -> None:
        """Config değişti — worker'ları durdurup yeniden kur (web ayakta kalır)."""
        with self._lock:
            self.log.info("⟳ Config değişti — ajanslar yeniden yükleniyor…")
            for w in self.workers.values():
                w.stop()
            for w in self.workers.values():
                w.join(timeout=5)
            self.workers.clear()
            self.registry.reset_agencies()
            cfg = load_config(self.config_path)
            self._load_auth(cfg.get("global", {}))
            self._spawn_workers(cfg)
            self.log.info("✓ Yeniden yükleme tamam. Ajanslar: %s", ", ".join(self.workers))


def run_service(config_path: str) -> None:
    Service(config_path).start()
