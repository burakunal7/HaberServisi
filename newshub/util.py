"""Küçük yardımcılar."""
from __future__ import annotations


def tr_lower(s: str) -> str:
    return s.replace("I", "ı").replace("İ", "i").lower()


def tr_title(s: str) -> str:
    """Türkçe başlık düzeni: 'İSTANBUL' -> 'İstanbul', 'AĞRI' -> 'Ağrı'."""
    parts = []
    for word in s.split():
        if not word:
            continue
        parts.append(word[0] + tr_lower(word[1:]))
    return " ".join(parts)
