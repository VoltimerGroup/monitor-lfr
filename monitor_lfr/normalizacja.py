"""Normalizacja tekstu – fundament „zero fałszywych alarmów”.

Dwa poziomy:
* `normalizuj()` – tekst do wyświetlenia i dopasowań: NFKC, jedna spacja zamiast
  dowolnych białych znaków (także NBSP, wąskich spacji, zer szerokości), jeden
  rodzaj myślnika ("-"), jeden rodzaj cudzysłowu.
* `klucz()` – klucz do porównań: znormalizowany tekst BEZ żadnych białych znaków,
  małymi literami. Dzięki temu „2026 r .” i „2026 r.” albo „4 166 250” i
  „4 166 250” (NBSP) dają ten sam klucz i nie wywołują alertu.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata

# Wersja reguł normalizacji. Zmiana reguł => nowa wersja => monitor przyjmuje
# nową bazę bez alertu (inaczej stara baza różniłaby się od nowej „na niby”).
WERSJA_NORMALIZACJI = 1

# Znaki usuwane całkowicie (miękki dywiz, zera szerokości, BOM).
_USUWANE = dict.fromkeys(map(ord, "­​‌‍⁠﻿"), None)

# Wszystkie odmiany myślników i minusów -> zwykły "-".
_MYSLNIKI = dict.fromkeys(
    map(ord, "‐‑‒–—―−⸺⸻﹘﹣－"), "-"
)

# Cudzysłowy podwójne -> ", pojedyncze/apostrofy -> '.
_CUDZYSLOWY = {
    **dict.fromkeys(map(ord, "„“”‟«»″〝〞"), '"'),
    **dict.fromkeys(map(ord, "‚‘’‛‹›′`´"), "'"),
}

_BIALE = re.compile(r"\s+")


def normalizuj(tekst: str) -> str:
    """Zwraca tekst w postaci kanonicznej (do wyświetlania i dopasowań regexami)."""
    if not tekst:
        return ""
    # Zamiana przed NFKC (np. „´” NFKC rozkłada na spację + akcent) i po NFKC
    # (NFKC potrafi z małego myślnika U+FE58 zrobić pauzę U+2014).
    t = _zamien_znaki(tekst)
    t = unicodedata.normalize("NFKC", t)  # NBSP->spacja, „…”->„...”, ó rozłożone->złożone
    t = _zamien_znaki(t)
    return _BIALE.sub(" ", t).strip()


def _zamien_znaki(t: str) -> str:
    return t.translate(_USUWANE).translate(_MYSLNIKI).translate(_CUDZYSLOWY)


def klucz(tekst: str) -> str:
    """Klucz porównawczy: bez białych znaków, casefold. Odporny na zmiany odstępów."""
    return _BIALE.sub("", normalizuj(tekst)).casefold()


def czy_separator(linia: str) -> bool:
    """Linia bez liter i cyfr (np. „……………” między ogłoszeniami) to separator."""
    return not any(z.isalnum() for z in linia)


def skrot(tekst: str) -> str:
    """SHA-256 (hex) – używany do deduplikacji alertów i wersji strony."""
    return hashlib.sha256(tekst.encode("utf-8")).hexdigest()
