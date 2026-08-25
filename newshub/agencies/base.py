"""Ajans adaptörlerinin ortak tabanı: oturum, hız sınırı, atomik indirme, retry."""
from __future__ import annotations

import logging
import threading
import time
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Iterator

import requests

from ..http import make_session
from ..state import SeenStore


class Agency(ABC):
    """Bir haber ajansı için çekici + kaydedici.

    Alt sınıf fetch_new() ile görülmemiş haberleri üretir, save() ile ajansın
    formatında diske yazar. Ortak işler (oturum, throttle, indirme, retry) burada.
    """

    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.name: str = cfg["name"]
        self.output_dir = Path(cfg["output_dir"])
        self.path_prefix: str = cfg.get("path_prefix", str(self.output_dir))
        # İki istek arası minimum süre (AA 500ms zorunlu kılıyor). 0 = sınır yok.
        self.min_request_interval = float(cfg.get("min_request_interval", 0) or 0)
        self.fetch_media = True
        self.panel_state: dict | None = None
        self.last_title = ""
        self.log = logging.getLogger(self.name)
        self.session: requests.Session = make_session()
        # Bazı ajansların medya sunucusu sertifikası doğrulanamayabilir (verify_ssl: false)
        self.session.verify = bool(cfg.get("verify_ssl", True))
        if not self.session.verify:
            import urllib3
            urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        self._req_lock = threading.Lock()
        self._last_req = 0.0
        # Worker durunca (reload/kapanış) uzun turu erken kesmek için (callable|None)
        self._abort = None

    def aborted(self) -> bool:
        try:
            return bool(self._abort and self._abort())
        except Exception:
            return False

    @abstractmethod
    def fetch_new(self, seen: SeenStore) -> Iterator:
        """Görülmemiş haberleri (eskiden yeniye) üretir. Her nesnenin .news_id'si olmalı."""
        raise NotImplementedError

    @abstractmethod
    def save(self, item) -> Path:
        """Haberi ajansın formatında yazar; ana yazılan dosyanın yolunu döndürür."""
        raise NotImplementedError

    def existing_ids(self) -> set[str]:
        """Hedef klasörde zaten bulunan haberlerin id'leri (ön-tohumlama için)."""
        return set()

    def save_text_only(self, item) -> None:
        """Medya olmadan sadece metni/XML'i yazar (kalıcı medya arızasında metin kaybolmasın)."""
        prev = self.fetch_media
        self.fetch_media = False
        try:
            self.save(item)
        finally:
            self.fetch_media = prev

    def cycle(self, seen: SeenStore, limit: int = 0, download_media: bool = True,
              on_item=None) -> int:
        """Bir tur: görülmemiş haberleri çekip yaz. Yazılan yeni haber sayısını döndürür.

        Medya inmezse max_media_retries kez tekrar dener; hâlâ inmezse metni yine de
        kaydeder ve arızayı işaretler (ne sessiz kayıp ne de sonsuz tıkanma).
        on_item(written, title) her haberden sonra çağrılır (panel anlık güncellenir).
        """
        self.fetch_media = download_media
        max_retries = int(self.cfg.get("max_media_retries", 5))
        written = 0
        for item in self.fetch_new(seen):
            nid = getattr(item, "news_id", "?")
            title = (getattr(item, "headline", "") or getattr(item, "title", "") or nid)
            try:
                self.save(item)
                seen.mark_seen(self.name, nid)
                seen.clear_pending(self.name, nid)
                written += 1
                self.last_title = title
                self.log.info("✓ yeni haber — %s", str(title)[:70])
            except Exception as e:
                attempts = seen.bump_attempt(self.name, nid)
                if attempts >= max_retries:
                    try:
                        self.save_text_only(item)
                        saved = "metin kaydedildi"
                    except Exception:
                        saved = "metin de alınamadı"
                    seen.mark_seen(self.name, nid)
                    seen.clear_pending(self.name, nid)
                    seen.record_failure(self.name, nid, str(title)[:120], f"medya inmedi: {e}")
                    self.last_title = title
                    self.log.error("⚠ %d denemede medya inmedi (%s), arıza işaretlendi — %s",
                                   attempts, saved, str(title)[:55])
                else:
                    self.log.warning("↺ tekrar denenecek (%d/%d) — %s", attempts, max_retries,
                                     str(title)[:55])
            if on_item:
                on_item(written, self.last_title)
            if limit and written >= limit:
                break
            if self.aborted():
                break
        return written

    def _throttle(self) -> None:
        if self.min_request_interval <= 0:
            return
        with self._req_lock:
            wait = self._last_req + self.min_request_interval - time.monotonic()
            if wait > 0:
                time.sleep(wait)
            self._last_req = time.monotonic()

    def get(self, url: str, **kw) -> requests.Response:
        self._throttle()
        return self.session.get(url, **kw)

    def post(self, url: str, **kw) -> requests.Response:
        self._throttle()
        return self.session.post(url, **kw)

    def download_to(self, url: str, target: Path, **kw) -> Path:
        """Bir URL'i atomik olarak target'a indirir (stream, hız sınırlı)."""
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists() and target.stat().st_size > 0:
            return target  # zaten indirilmiş
        self._throttle()
        tmp = target.with_suffix(target.suffix + ".part")
        try:
            with self.session.get(url, stream=True, timeout=180, **kw) as r:
                r.raise_for_status()
                with open(tmp, "wb") as f:
                    for chunk in r.iter_content(chunk_size=1 << 16):
                        if chunk:
                            f.write(chunk)
                tmp.replace(target)  # atomik: yarım dosya asla görünmez
        except Exception:
            try:
                if tmp.exists():
                    tmp.unlink()
            except OSError:
                pass
            raise
        return target

    def write_bytes_atomic(self, target: Path, data: bytes) -> Path:
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_suffix(target.suffix + ".part")
        try:
            tmp.write_bytes(data)
            tmp.replace(target)
        except Exception:
            try:
                if tmp.exists():
                    tmp.unlink()
            except OSError:
                pass
            raise
        return target

    def proxy_path(self, news_id: str, ext: str) -> str:
        prefix = self.path_prefix.rstrip("/\\")
        sep = "\\" if "\\" in self.path_prefix else "/"
        return f"{prefix}{sep}{news_id}.{ext}"
