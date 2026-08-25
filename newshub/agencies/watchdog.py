"""Bekçi (watchdog) ajansı: API'si olmayan kaynaklar (DHA exe, Reuters servisi) için.

Kaynağın çıktı klasörünü izler; belirli süre yeni haber düşmezse recovery_command
çalıştırır (exe'yi yeniden başlat / servisi restart). Panelde yeşil=akıyor, kırmızı=durdu.
"""
from __future__ import annotations

import datetime as _dt
import os
import subprocess
import time
from pathlib import Path

from ..state import SeenStore
from .base import Agency


class WatchdogAgent(Agency):

    def __init__(self, cfg: dict):
        cfg.setdefault("output_dir", cfg.get("watch_dir", "."))
        super().__init__(cfg)
        self.watch_dir = Path(cfg.get("watch_dir", cfg.get("output_dir", ".")))
        self.stale_minutes = float(cfg.get("stale_minutes", 15))
        self.recovery_command = cfg.get("recovery_command", "") or ""
        self.recovery_cooldown = float(cfg.get("recovery_cooldown_minutes", 5))
        # Verilirse panelde exe'nin açık olup olmadığı da gösterilir, kapalıysa başlatılır
        self.process_name = cfg.get("process_name", "") or ""
        self._last_recovery_mono = -1e9
        self.recovery_count = 0
        self._prev_state = None  # log'u sadece durum değişince yaz

    def fetch_new(self, seen: SeenStore):
        return iter(())

    def save(self, item) -> Path:  # pragma: no cover
        raise NotImplementedError("watchdog save() kullanmaz")

    def _scan(self) -> tuple[float, int]:
        """(en yeni dosya zamanı, bugün düşen .xml sayısı). Klasör mtime'ı güvenilmez,
        gerçek dosya mtime'ları taranır."""
        if not self.watch_dir.exists():
            return 0.0, 0
        today0 = _dt.datetime.now().replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
        latest = 0.0
        news_today = 0
        stack = [str(self.watch_dir)]
        while stack:
            d = stack.pop()
            try:
                with os.scandir(d) as it:
                    for e in it:
                        try:
                            if e.is_file(follow_symlinks=False):
                                m = e.stat(follow_symlinks=False).st_mtime
                                if m > latest:
                                    latest = m
                                if m >= today0 and e.name.lower().endswith(".xml"):
                                    news_today += 1
                            elif e.is_dir(follow_symlinks=False):
                                stack.append(e.path)
                        except OSError:
                            pass
            except OSError:
                pass
        return latest, news_today

    def _process_running(self):
        """İzlenen exe açık mı? None=kontrol edilmiyor, True/False=durum."""
        if not self.process_name:
            return None
        try:
            out = subprocess.run(
                ["tasklist", "/FI", f"IMAGENAME eq {self.process_name}", "/NH"],
                capture_output=True, text=True, timeout=10,
            ).stdout or ""
            return self.process_name.lower() in out.lower()
        except Exception:
            return None

    def _run_recovery(self) -> None:
        self.recovery_count += 1
        self._last_recovery_mono = time.monotonic()
        if not self.recovery_command:
            self.log.warning("%s: kurtarma komutu tanımlı değil (recovery_command boş)", self.name)
            return
        try:
            subprocess.Popen(self.recovery_command, shell=True)
            self.log.warning("%s: KURTARMA çalıştırıldı -> %s", self.name, self.recovery_command)
        except Exception as e:
            self.log.error("%s: kurtarma komutu başarısız: %s", self.name, e)

    def cycle(self, seen: SeenStore, limit: int = 0, download_media: bool = True,
              on_item=None) -> int:
        running = self._process_running()
        newest, news_today = self._scan()
        newest_str = (_dt.datetime.fromtimestamp(newest).strftime("%Y-%m-%d %H:%M:%S")
                      if newest else None)

        # Süreç izleniyor ve kapalı -> yeniden başlat
        if running is False:
            cooled = (time.monotonic() - self._last_recovery_mono) > self.recovery_cooldown * 60
            did = 0
            if cooled:
                self.log.warning("⚠ %s uygulaması KAPALI — yeniden başlatılıyor", self.name)
                self._run_recovery()
                did = 1
            elif self._prev_state != "down":
                self.log.warning("⚠ %s uygulaması kapalı (kurtarma bekleme süresinde)", self.name)
            self._prev_state = "down"
            self.panel_state = {"state": "error", "last_success": newest_str, "count": news_today,
                                "last_error": "uygulama çalışmıyor"
                                              + (" — yeniden başlatıldı" if did else ""),
                                "last_title": "⚠ uygulama kapalı"}
            return did

        proc_note = " · uygulama açık" if running else ""

        # Klasör boş/yok
        if not newest:
            if self._prev_state != "empty":
                self.log.warning("⚠ izlenen klasör boş/yok: %s", self.watch_dir)
            self._prev_state = "empty"
            self.panel_state = {"state": "error", "last_success": None, "count": 0,
                                "last_error": f"Klasör yok/boş: {self.watch_dir}",
                                "last_title": "⚠ henüz haber yok" + proc_note}
            return 0

        age_min = (time.time() - newest) / 60.0

        # Taze -> akış normal
        if age_min <= self.stale_minutes:
            if self._prev_state != "ok":
                self.log.info("● akış normal — son haber %.0f dk önce", age_min)
            self._prev_state = "ok"
            self.panel_state = {"state": "idle", "last_success": newest_str, "last_error": None,
                                "count": news_today,
                                "last_title": f"akış normal — son haber {age_min:.0f} dk önce" + proc_note}
            return 0

        # Süreç açık ama akış durdu -> gerekirse yeniden başlat
        cooled = (time.monotonic() - self._last_recovery_mono) > self.recovery_cooldown * 60
        did_recover = 0
        if cooled:
            self.log.warning("⚠ AKIŞ DURDU — %.0f dk yeni haber yok (eşik %.0f dk), yeniden başlatılıyor",
                             age_min, self.stale_minutes)
            self._run_recovery()
            did_recover = 1
        elif self._prev_state != "stale":
            self.log.warning("⚠ akış durdu — %.0f dk haber yok (kurtarma bekleme süresinde)", age_min)
        self._prev_state = "stale"
        self.panel_state = {
            "state": "error", "last_success": newest_str, "count": news_today,
            "last_error": f"{age_min:.0f} dk haber yok" + (" — yeniden başlatıldı" if did_recover else ""),
            "last_title": "⚠ akış durdu",
        }
        return did_recover
