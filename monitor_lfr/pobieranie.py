"""Pobieranie strony: timeout, ponowienia z wykładniczym backoffem, zwykły User-Agent."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Callable

import requests


@dataclass
class Odpowiedz:
    status_http: int | None  # None = wejście z pliku (--plik)
    html: str
    proby: int = 1


class BladPobierania(Exception):
    """Nie udało się pobrać strony mimo ponowień."""

    def __init__(self, komunikat: str, status_http: int | None = None, proby: int = 0):
        super().__init__(komunikat)
        self.status_http = status_http
        self.proby = proby


def _dekoduj(odp: requests.Response) -> str:
    """Kodowanie z nagłówka; gdy go brak – wykrywanie (requests domyślnie dałby ISO-8859-1)."""
    typ = odp.headers.get("content-type", "").lower()
    if "charset=" in typ and odp.encoding:
        kodowanie = odp.encoding
    else:
        kodowanie = odp.apparent_encoding or "utf-8"
    return odp.content.decode(kodowanie, errors="replace")


def pobierz_strone(
    url: str,
    *,
    timeout_s: float = 30,
    ponowienia: int = 3,
    backoff_s: float = 5,
    user_agent: str,
    sesja: requests.Session | None = None,
    spij: Callable[[float], None] = time.sleep,
) -> Odpowiedz:
    """GET z ponowieniami: 1 próba + `ponowienia` kolejnych (odstępy backoff, 2×backoff, 4×…)."""
    naglowki = {
        "User-Agent": user_agent,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "pl-PL,pl;q=0.9,en;q=0.5",
        "Cache-Control": "no-cache",
        "Pragma": "no-cache",
    }
    s = sesja or requests.Session()
    ostatni_blad = "nieznany błąd"
    ostatni_status: int | None = None
    wszystkie = ponowienia + 1
    for proba in range(1, wszystkie + 1):
        try:
            odp = s.get(url, headers=naglowki, timeout=(min(10.0, timeout_s), timeout_s))
            ostatni_status = odp.status_code
            if odp.status_code == 200:
                return Odpowiedz(status_http=200, html=_dekoduj(odp), proby=proba)
            ostatni_blad = f"HTTP {odp.status_code}"
        except requests.RequestException as e:
            ostatni_status = None
            ostatni_blad = f"{type(e).__name__}: {e}"
        if proba < wszystkie:
            spij(backoff_s * (2 ** (proba - 1)))
    raise BladPobierania(
        f"Nie udało się pobrać strony po {wszystkie} próbach: {ostatni_blad}",
        status_http=ostatni_status,
        proby=wszystkie,
    )
