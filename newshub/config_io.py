"""config.yaml okuma/yazma — panelden düzenleme için (ruamel round-trip, yorumlar korunur)."""
from __future__ import annotations

import threading
from pathlib import Path

from ruamel.yaml import YAML

_yaml = YAML()
_yaml.preserve_quotes = True
_yaml.width = 4096
_lock = threading.Lock()

_SKIP = {"name", "type"}
# Global'de panelden düzenlenmeyecek altyapı alanları (canlı değişimi riskli)
_GLOBAL_SKIP = {"state_db", "log_dir", "web_host", "web_port", "web_user", "web_password"}
# Şifreler ağ üzerinden düz metin gitmesin diye maskelenir. Kullanıcı dokunmazsa
# bu ASCII sentinel geri gelir ve kaydetmede atlanır (gerçek şifre korunur).
MASK = "__UNCHANGED__"


def _is_secret(key: str) -> bool:
    k = key.lower()
    return "pass" in k or "şifre" in k or "sifre" in k or "password" in k


def _load(path: str):
    with open(path, encoding="utf-8") as f:
        return _yaml.load(f)


def load_editable(path: str) -> dict:
    doc = _load(path)
    g = doc.get("global", {}) or {}
    global_fields = {k: (MASK if _is_secret(k) and v else v)
                     for k, v in g.items() if _is_scalar(v) and k not in _GLOBAL_SKIP}

    agencies = []
    for a in doc.get("agencies", []) or []:
        fields = {k: (MASK if _is_secret(k) and v else v)
                  for k, v in a.items() if k not in _SKIP and _is_scalar(v)}
        agencies.append({
            "name": a.get("name", "?"),
            "type": a.get("type", ""),
            "fields": fields,
        })
    return {"global": global_fields, "agencies": agencies}


def apply_and_save(path: str, updates: dict) -> None:
    with _lock:
        doc = _load(path)

        gsrc = updates.get("global") or {}
        g = doc.get("global", {})
        for k, v in gsrc.items():
            if k in _GLOBAL_SKIP or k not in g or not _is_scalar(g[k]):
                continue
            if _is_secret(k) and v == MASK:
                continue
            g[k] = _coerce(g[k], v)

        by_name = {a.get("name"): a for a in (doc.get("agencies") or [])}
        for upd in updates.get("agencies") or []:
            a = by_name.get(upd.get("name"))
            if not a:
                continue
            for k, v in (upd.get("fields") or {}).items():
                if k in _SKIP or k not in a or not _is_scalar(a[k]):
                    continue
                if _is_secret(k) and v == MASK:
                    continue
                a[k] = _coerce(a[k], v)

        with open(path, "w", encoding="utf-8") as f:
            _yaml.dump(doc, f)


def _is_scalar(v) -> bool:
    return isinstance(v, (str, int, float, bool)) or v is None


def _coerce(old, new):
    """Yeni değeri mevcut değerin tipine çevir (form her şeyi string yollayabilir)."""
    if isinstance(old, bool):
        if isinstance(new, bool):
            return new
        return str(new).strip().lower() in ("true", "1", "evet", "on", "yes")
    if isinstance(old, int) and not isinstance(old, bool):
        try:
            return int(float(new))
        except (TypeError, ValueError):
            return old
    if isinstance(old, float):
        try:
            return float(new)
        except (TypeError, ValueError):
            return old
    return "" if new is None else str(new)
