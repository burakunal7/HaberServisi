"""Ajanstan bağımsız ortak haber modeli."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class MediaAsset:
    url: str
    kind: str                # "image" | "video"
    ext: str                 # "jpg" | "mp4"


@dataclass
class NewsItem:
    news_id: str
    headline: str
    body: str
    category: str = ""
    city: str = ""
    news_date: str = ""
    primary_media: Optional[MediaAsset] = None
    media: list[MediaAsset] = field(default_factory=list)
    raw: dict = field(default_factory=dict)
