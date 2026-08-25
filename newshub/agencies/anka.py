"""ANKA Haber Ajansı adaptörü.

API: /users/login/ (session_id -> ANKA cookie), /news/list/?sayfa=N, /news/get/{id}/.
Çıktı: .xml uzantılı ama içi boşluksuz JSON — alan sırası sabit (alt sistem böyle okur).
"""
from __future__ import annotations

import datetime as _dt
import json
from pathlib import Path
from typing import Iterator, Optional

from ..model import MediaAsset, NewsItem
from ..state import SeenStore
from ..util import tr_title
from .base import Agency


class AnkaAgency(Agency):

    def __init__(self, cfg: dict):
        super().__init__(cfg)
        self._authed = False
        self.catchup_days = float(cfg.get("catchup_days", 1))

    def login(self) -> None:
        url = f"{self.cfg['base_url']}/users/login/"
        r = self.post(
            url,
            data={"username": self.cfg["username"], "password": self.cfg["password"]},
            timeout=30,
        )
        r.raise_for_status()
        j = r.json()
        if not j.get("success"):
            raise RuntimeError(f"ANKA giriş başarısız: {j.get('message')}")
        sid = j["data"]["session_id"]
        # Ham Cookie header 403'leniyor; çerez jar üzerinden gitmeli
        self.session.cookies.set("ANKA", sid, domain="abone-api.ankahaber.net")
        self._authed = True
        self.log.info("ANKA oturum açıldı (canlı takip başladı).")

    def _get(self, url: str):
        r = self.get(url, timeout=30)
        if r.status_code in (401, 403):   # oturum düştü -> bir kez yeniden login
            self._authed = False
            self.login()
            r = self.get(url, timeout=30)
        r.raise_for_status()
        return r

    def _list_page(self, page: int) -> list[dict]:
        url = f"{self.cfg['base_url']}/news/list/?sayfa={page}"
        data = self._get(url).json().get("data") or {}
        return data.get("news") or []

    def _detail(self, news_id: str) -> dict:
        url = f"{self.cfg['base_url']}/news/get/{news_id}/"
        return self._get(url).json().get("data") or {}

    def fetch_new(self, seen: SeenStore) -> Iterator[NewsItem]:
        if not self._authed:
            self.login()
        # Görülen habere ulaşana kadar sayfa gez (kesinti sonrası aradaki tüm haberler
        # alınır); max_catchup_pages çok uzun kesintide sonsuz gezmeyi keser.
        max_pages = int(self.cfg.get("max_catchup_pages", 30))

        cutoff = _dt.datetime.now() - _dt.timedelta(days=self.catchup_days)
        fresh: list[dict] = []
        caught_up = False
        for page in range(1, max_pages + 1):
            if self.aborted():
                return
            items = self._list_page(page)
            if not items:
                caught_up = True
                break
            page_new = []
            reached_old = False
            for it in items:
                if seen.is_seen(self.name, it.get("id", "")):
                    continue
                dt_str = (it.get("created_at") or "")[:19]
                if dt_str:
                    try:
                        if _dt.datetime.strptime(dt_str, "%Y-%m-%d %H:%M:%S") < cutoff:
                            reached_old = True   # catchup_days'ten eski -> dur
                            break
                    except ValueError:
                        pass
                page_new.append(it)
            fresh.extend(page_new)
            if reached_old or not page_new:
                caught_up = True
                break
        if not caught_up:
            self.log.warning("⚠ %d sayfa tarandı, hâlâ yeni haber var — çok uzun kesinti "
                             "olabilir, daha eskiler kaçmış olabilir (max_catchup_pages arttır)",
                             max_pages)

        # Eskiden yeniye işle: yarıda kesilirse eski haberler yazılmış olur
        for list_item in reversed(fresh):
            try:
                detail = self._detail(list_item["id"])
                yield self._to_item(list_item, detail)
            except Exception as e:
                self.log.warning("Haber detayı alınamadı (%s): %s", list_item.get("id"), e)

    def _to_item(self, list_item: dict, detail: dict) -> NewsItem:
        news_id = detail.get("id") or list_item.get("id")

        # Şehir: city_array[0] -> cities tablosundan isim -> Türkçe düzelt
        city = ""
        city_array = detail.get("city_array") or []
        if city_array:
            cmap = {c["id"]: c["name"] for c in (detail.get("cities") or [])}
            city = tr_title(cmap.get(city_array[0], ""))

        # Video + fotoğrafların TAMAMI (bir haberde ikisi birden olabilir)
        media: list[MediaAsset] = []

        videos_raw = detail.get("videos")
        if isinstance(videos_raw, dict):          # API bazen tek dict döner
            videos_raw = [videos_raw]
        for v in (videos_raw or []):
            vurl = v.get("hd_url") or v.get("url")
            if vurl:
                media.append(MediaAsset(url=vurl, kind="video", ext="mp4"))
        if not media:
            fallback_video = list_item.get("video") or None
            if fallback_video:
                media.append(MediaAsset(url=fallback_video, kind="video", ext="mp4"))

        for img in (detail.get("images") or []):
            iurl = img.get("url") if isinstance(img, dict) else img
            if iurl and "placeholder" not in str(iurl).lower():
                media.append(MediaAsset(url=iurl, kind="image", ext="jpg"))
        if not any(m.kind == "image" for m in media):
            image_url = list_item.get("image") or None
            if image_url and "placeholder" not in image_url.lower():
                media.append(MediaAsset(url=image_url, kind="image", ext="jpg"))

        primary = media[0] if media else None
        return NewsItem(
            news_id=news_id,
            headline=detail.get("title", ""),
            body=detail.get("body", ""),
            category=detail.get("category", ""),
            city=city,
            news_date=detail.get("created_at", ""),
            primary_media=primary,
            media=media,
            raw=detail,
        )

    def existing_ids(self) -> set[str]:
        if not self.output_dir.exists():
            return set()
        return {p.stem for p in self.output_dir.glob("*.xml")}

    def save(self, item: NewsItem) -> Path:
        # Önce tüm medyalar (video + fotoğraflar), sonra .xml
        if self.fetch_media:
            img_idx = 0
            for asset in item.media:
                if asset.kind == "video":
                    target = self.output_dir / f"{item.news_id}.{asset.ext}"
                else:
                    # İlk foto: <id>.jpg, sonrakiler: <id>_2.jpg, <id>_3.jpg, ...
                    img_idx += 1
                    suffix = "" if img_idx == 1 else f"_{img_idx}"
                    target = self.output_dir / f"{item.news_id}{suffix}.{asset.ext}"
                self.download_to(asset.url, target)
        return self._write_xml(item)

    def _write_xml(self, item: NewsItem) -> Path:
        ext = item.primary_media.ext if item.primary_media else ""
        proxy = self.proxy_path(item.news_id, ext) if ext else ""

        record = {
            "news_number": item.news_id,
            "headline": item.headline,
            "city": item.city,
            "category": item.category,
            "news_date": item.news_date,
            "story": item.body,
            "file_proxy": proxy,
            "file_original": proxy,
        }

        images = [m for m in item.media if m.kind == "image"]
        if images:
            img_paths = []
            for i, img in enumerate(images, 1):
                suffix = "" if i == 1 else f"_{i}"
                img_paths.append(self.proxy_path(f"{item.news_id}{suffix}", img.ext))
            record["images"] = img_paths
        target = self.output_dir / f"{item.news_id}.xml"
        payload = json.dumps(record, ensure_ascii=False, separators=(",", ":"))
        return self.write_bytes_atomic(target, payload.encode("utf-8"))
