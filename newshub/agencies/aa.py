r"""Anadolu Ajansı (AA) adaptörü.

API: https://api.aa.com.tr (HTTP Basic Auth). İki istek arası en az 500ms olmalı
(yoksa foto'lar kırık iner). search -> liste, document -> içerik indirme.

Çıktı (mevcut klasörle birebir): aa_text/aa_photo/aa_video alt klasörleri; metadata
newsml12, fiziksel medya adı NewsML <ContentItem Href> değerinden.
"""
from __future__ import annotations

import datetime as _dt
import json
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator
from xml.etree import ElementTree as ET

from ..state import SeenStore
from .base import Agency


@dataclass
class AaItem:
    news_id: str          # örn. aa:text:20260703:41867456
    date: str = ""        # search'ten gelen yayın tarihi (UTC)
    title: str = ""
    group_id: str = ""

    @property
    def type(self) -> str:
        p = self.news_id.split(":")
        return p[1] if len(p) >= 2 else ""

    @property
    def yyyymmdd(self) -> str:
        p = self.news_id.split(":")
        return p[2] if len(p) >= 3 else ""

    @property
    def num(self) -> str:
        p = self.news_id.split(":")
        return p[3] if len(p) >= 4 else ""


class AaAgency(Agency):

    SUBDIRS = {"text": "aa_text", "picture": "aa_photo", "video": "aa_video",
               "graph": "aa_graph", "file": "aa_file"}
    # document endpoint boyutu -> NewsML Href'indeki boyut etiketi
    SIZE_TOKEN = {"print": "High", "web": "Web", "sd": "SD"}
    MEDIA_EXT = {"picture": "jpg", "video": "mp4"}

    def __init__(self, cfg: dict):
        cfg.setdefault("min_request_interval", 0.5)  # AA zorunlu 500ms
        super().__init__(cfg)
        self.base = cfg["base_url"].rstrip("/")
        self.session.auth = (cfg["username"], cfg["password"])
        self.catchup_days = float(cfg.get("catchup_days", 1))
        self.overlap_minutes = float(cfg.get("overlap_minutes", 5))
        self.page_limit = int(cfg.get("page_limit", 100))
        self.photo_size = cfg.get("photo_size", "print")  # print(High) | web(Web)
        self.video_size = cfg.get("video_size", "sd")     # sd(SD)      | web(Web)
        self.search_filters = cfg.get("search_filters", {}) or {}

    FMT = "%Y-%m-%dT%H:%M:%SZ"

    def _resume_start(self, seen: SeenStore) -> str:
        """Kaldığı yerden devam ama en fazla catchup_days geriye (AA çok geçmişi
        birden çekmesin). Checkpoint yoksa yine son catchup_days çekilir."""
        now = _dt.datetime.now(_dt.timezone.utc)
        floor = now - _dt.timedelta(days=self.catchup_days)
        cp = seen.get_checkpoint(self.name, "last_fetch_utc")
        if cp:
            try:
                cp_dt = _dt.datetime.strptime(cp, self.FMT).replace(tzinfo=_dt.timezone.utc)
                start_dt = max(cp_dt, floor)
            except Exception:
                start_dt = floor
        else:
            start_dt = floor
        return start_dt.strftime(self.FMT)

    def _search_page(self, start_date: str, offset: int) -> dict:
        body = {"start_date": start_date, "end_date": "NOW",
                "offset": offset, "limit": self.page_limit}
        body.update(self.search_filters)
        r = self.post(f"{self.base}/abone/search/", data=body, timeout=30)
        r.raise_for_status()
        return r.json().get("data") or {}

    def fetch_new(self, seen: SeenStore) -> Iterator[AaItem]:
        now_utc = _dt.datetime.now(_dt.timezone.utc)
        start_date = self._resume_start(seen)
        fresh: list[AaItem] = []
        offset = 0
        while True:
            if self.aborted():
                return
            data = self._search_page(start_date, offset)
            results = data.get("result") or []
            if not results:
                break
            for it in results:
                nid = it.get("id")
                if nid and not seen.is_seen(self.name, nid):
                    fresh.append(AaItem(
                        news_id=nid,
                        date=it.get("date", ""),
                        title=it.get("title", ""),
                        group_id=str(it.get("group_id", "") or ""),
                    ))
            total = int(data.get("total") or 0)
            offset += self.page_limit
            if offset >= total:
                break

        # Tipleri round-robin harmanla: foto seli text/video'yu bekletmesin
        # (her tip kendi içinde eskiden yeniye işlenir).
        groups: dict[str, deque] = {}
        for item in reversed(fresh):
            groups.setdefault(item.type, deque()).append(item)
        order = ["text", "picture", "video", "graph", "file"]
        for t in groups:
            if t not in order:
                order.append(t)
        while any(groups.values()):
            for t in order:
                q = groups.get(t)
                if q:
                    yield q.popleft()

        # Checkpoint tüm haberler yazıldıktan SONRA ilerler (çökmede boşluk kalmaz)
        cp = (now_utc - _dt.timedelta(minutes=self.overlap_minutes)).strftime(self.FMT)
        seen.set_checkpoint(self.name, "last_fetch_utc", cp)

    def _document(self, news_id: str, fmt: str) -> bytes:
        url = f"{self.base}/abone/document/{news_id}/{fmt}"
        r = self.get(url, timeout=60)
        r.raise_for_status()
        return r.content

    @staticmethod
    def _extract_newsml(content: bytes) -> bytes:
        """newsml12 ham XML döndürür; JSON'a sarılıysa içindeki XML'i çıkarır."""
        head = content.lstrip()[:5]
        if head[:1] == b"<":
            return content
        try:
            j = json.loads(content)
            inner = j.get("data") if isinstance(j, dict) else None
            if isinstance(inner, str):
                return inner.encode("utf-8")
        except Exception:
            pass
        return content

    def _media_hrefs(self, newsml: bytes) -> list[str]:
        try:
            root = ET.fromstring(newsml)
        except ET.ParseError:
            return []
        hrefs = []
        for ci in root.iter("ContentItem"):
            href = ci.get("Href")
            if href:
                hrefs.append(href)
        return hrefs

    def save(self, item: AaItem) -> Path:
        subdir = self.output_dir / self.SUBDIRS.get(item.type, "aa_other")

        raw = self._document(item.news_id, "newsml12")
        newsml = self._extract_newsml(raw)
        meta_name = f"aa_{item.type}_{item.yyyymmdd}_{item.num}.xml"
        meta_path = self.write_bytes_atomic(subdir / meta_name, newsml)

        # Foto/video: fiziksel medyayı abone boyutundan indir, adını Href'ten al
        if self.fetch_media and item.type in self.MEDIA_EXT:
            size = self.photo_size if item.type == "picture" else self.video_size
            ext = self.MEDIA_EXT[item.type]
            hrefs = [h for h in self._media_hrefs(newsml) if h.lower().endswith("." + ext)]
            if not hrefs:
                self.log.warning("%s: NewsML içinde .%s medya Href yok", item.news_id, ext)
            else:
                chosen = self._pick_href(hrefs, size)
                url = f"{self.base}/abone/document/{item.news_id}/{size}"
                self.download_to(url, subdir / chosen)

        return meta_path

    def existing_ids(self) -> set[str]:
        # aa_photo/aa_picture_20260703_41866865.xml -> aa:picture:20260703:41866865
        ids: set[str] = set()
        for typ, sub in self.SUBDIRS.items():
            d = self.output_dir / sub
            if not d.exists():
                continue
            for p in d.glob(f"aa_{typ}_*.xml"):
                parts = p.stem.split("_")
                if len(parts) >= 4:
                    ids.add(f"aa:{parts[1]}:{parts[2]}:{parts[3]}")
        return ids

    def _pick_href(self, hrefs: list[str], size: str) -> str:
        """Tek Href varsa onu; birden çoksa abone boyutuna (High/Web/SD) uyanı seç."""
        if len(hrefs) == 1:
            return hrefs[0]
        token = self.SIZE_TOKEN.get(size, "")
        if token:
            for h in hrefs:
                if f"_{token}.".lower() in h.lower():
                    return h
        return hrefs[0]
