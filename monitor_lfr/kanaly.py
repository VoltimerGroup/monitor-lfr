"""Kanały powiadomień: Telegram (produkcyjnie), konsola (--dry-run).

Token i chat_id czytamy WYŁĄCZNIE ze zmiennych środowiskowych. Token nigdy nie
trafia do komunikatów błędów (adres API zawiera token, więc go maskujemy).
"""

from __future__ import annotations

import os
import sys
import time
from typing import Callable, Mapping, Protocol, TextIO

import requests

LIMIT_TELEGRAM = 4000  # API przyjmuje 4096 znaków; zostawiamy zapas


class BladWysylki(Exception):
    """Nie udało się dostarczyć powiadomienia."""


class Kanal(Protocol):
    nazwa: str

    def wyslij(self, tekst: str) -> None:
        """Wysyła wiadomość albo rzuca BladWysylki."""


def przytnij(tekst: str, limit: int = LIMIT_TELEGRAM) -> str:
    if len(tekst) <= limit:
        return tekst
    return tekst[: limit - 20].rstrip() + "\n…(skrócono)"


class KanalTelegram:
    nazwa = "telegram"
    API = "https://api.telegram.org"

    def __init__(
        self,
        token: str,
        chat_id: str,
        *,
        sesja: requests.Session | None = None,
        timeout_s: float = 20,
        ponowienia: int = 2,
        spij: Callable[[float], None] = time.sleep,
    ):
        self._token = token
        self._chat_id = chat_id
        self._sesja = sesja or requests.Session()
        self._timeout = timeout_s
        self._ponowienia = ponowienia
        self._spij = spij

    def _ukryj(self, tekst: str) -> str:
        return tekst.replace(self._token, "***") if self._token else tekst

    def wyslij(self, tekst: str) -> None:
        url = f"{self.API}/bot{self._token}/sendMessage"
        dane = {"chat_id": self._chat_id, "text": przytnij(tekst), "disable_web_page_preview": True}
        blad = "nieznany błąd"
        for proba in range(self._ponowienia + 1):
            czekaj = 2.0 * (2 ** proba)
            try:
                odp = self._sesja.post(url, json=dane, timeout=self._timeout)
                try:
                    tresc = odp.json()
                except ValueError:
                    tresc = {}
                if odp.status_code == 200 and tresc.get("ok"):
                    return
                blad = f"HTTP {odp.status_code}: {tresc.get('description', 'brak opisu')}"
                if odp.status_code == 429:
                    czekaj = float(tresc.get("parameters", {}).get("retry_after", czekaj))
                elif 400 <= odp.status_code < 500:
                    break  # zły token / chat_id – ponawianie nic nie da
            except requests.RequestException as e:
                blad = f"{type(e).__name__}: {e}"
            if proba < self._ponowienia:
                self._spij(min(czekaj, 30.0))
        raise BladWysylki("Telegram: " + self._ukryj(blad))


class KanalKonsola:
    """--dry-run: niczego nie wysyła, tylko drukuje."""

    nazwa = "konsola"

    def __init__(self, strumien: TextIO | None = None):
        self._strumien = strumien

    def wyslij(self, tekst: str) -> None:
        s = self._strumien or sys.stdout
        s.write("\n===== [DRY-RUN] wiadomość (niewysłana) =====\n")
        s.write(przytnij(tekst) + "\n")
        s.write("===== koniec wiadomości =====\n\n")
        s.flush()


class KanalNieskonfigurowany:
    """Kanał bez sekretów – każda próba wysyłki kończy się błędem z czytelnym opisem."""

    def __init__(self, nazwa: str, powod: str):
        self.nazwa = nazwa
        self.powod = powod

    def wyslij(self, tekst: str) -> None:
        raise BladWysylki(self.powod)


def kanal_z_srodowiska(nazwa: str, srodowisko: Mapping[str, str] | None = None) -> Kanal:
    """Tworzy kanał na podstawie konfiguracji i zmiennych środowiskowych."""
    env = os.environ if srodowisko is None else srodowisko
    nazwa = nazwa.lower()
    if nazwa == "telegram":
        token = (env.get("TELEGRAM_BOT_TOKEN") or "").strip()
        chat_id = (env.get("TELEGRAM_CHAT_ID") or "").strip()
        if not token or not chat_id:
            brak = [n for n, v in (("TELEGRAM_BOT_TOKEN", token), ("TELEGRAM_CHAT_ID", chat_id)) if not v]
            return KanalNieskonfigurowany(
                "telegram",
                "Brak zmiennych środowiskowych: " + ", ".join(brak)
                + " (lokalnie: ustaw w terminalu; w GitHub: Settings -> Secrets and variables -> Actions).",
            )
        return KanalTelegram(token, chat_id)
    if nazwa == "konsola":
        return KanalKonsola()
    return KanalNieskonfigurowany(nazwa, f"Nieznany kanał w config.json: {nazwa!r} (dostępne: telegram, konsola).")
