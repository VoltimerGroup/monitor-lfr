"""Konfiguracja monitora (plik config.json w katalogu głównym repozytorium).

Sekrety (TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID) NIGDY nie trafiają do config.json –
czytamy je wyłącznie ze zmiennych środowiskowych (lokalnie lub z GitHub Secrets).
"""

from __future__ import annotations

import copy
import json
import re
from dataclasses import dataclass, field
from datetime import time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

KATALOG_GLOWNY = Path(__file__).resolve().parent.parent
DOMYSLNY_PLIK = KATALOG_GLOWNY / "config.json"
DOMYSLNY_KATALOG_STANU = KATALOG_GLOWNY / "state"

USER_AGENT_PRZEGLADARKI = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36"
)

DOMYSLNE: dict = {
    "url": "https://www.lfr.lublin.pl/projekty/pierwszy-biznes-wsparcie-w-starcie-2025/",
    "moje_wojewodztwa": ["mazowieckie", "lubelskie"],
    "strefa_czasowa": "Europe/Warsaw",
    "kanal": "telegram",
    "heartbeat": {"wlaczony": True, "godzina": 9},
    "przypomnienia": {
        "przed_startem": ["3d", "1d", "1h"],
        "tylko_moje_wojewodztwa": True,
        "godzina_startu_gdy_brak": "08:00",
    },
    "awaria": {"kolejne_bledy_do_alertu": 3},
    "pobieranie": {
        "timeout_s": 30,
        "ponowienia": 3,
        "backoff_s": 5,
        "user_agent": USER_AGENT_PRZEGLADARKI,
    },
    "ekstrakcja": {
        "selektory_tresci": [
            "div.institution.entry > div.area > div.text",
            "div.entry > div.area > div.text",
        ],
        "selektor_dokumentow": "#dokumenty-do-pobrania",
        "oczekiwane_frazy": ["Pierwszy Biznes"],
        "min_linii": 10,
    },
    "log": {"max_wpisow": 2000},
}


class BladKonfiguracji(Exception):
    """Niepoprawny config.json."""


@dataclass
class Przypomnienie:
    etykieta: str  # np. „3 dni”
    wyprzedzenie: timedelta


@dataclass
class Konfiguracja:
    url: str
    moje_wojewodztwa: list[str]
    strefa: ZoneInfo
    kanal: str
    heartbeat_wlaczony: bool
    heartbeat_godzina: int
    przypomnienia: list[Przypomnienie]
    przypomnienia_tylko_moje: bool
    godzina_startu_gdy_brak: time
    prog_awarii: int
    timeout_s: float
    ponowienia: int
    backoff_s: float
    user_agent: str
    selektory_tresci: list[str]
    selektor_dokumentow: str
    oczekiwane_frazy: list[str]
    min_linii: int
    log_max_wpisow: int
    surowe: dict = field(default_factory=dict, repr=False)


def _scal(baza: dict, nadpisanie: dict) -> dict:
    """Głębokie scalenie słowników (wartości z pliku nadpisują domyślne)."""
    wynik = copy.deepcopy(baza)
    for k, v in nadpisanie.items():
        if k.startswith("_"):
            continue  # klucze „_komentarz” itp. ignorujemy
        if isinstance(v, dict) and isinstance(wynik.get(k), dict):
            wynik[k] = _scal(wynik[k], v)
        else:
            wynik[k] = v
    return wynik


_WYPRZEDZENIE = re.compile(r"^\s*(\d+)\s*([dhm])\s*$", re.IGNORECASE)


def _parsuj_wyprzedzenie(tekst: str) -> Przypomnienie:
    """„3d” -> 3 dni, „1h” -> 1 godz., „30m” -> 30 min."""
    m = _WYPRZEDZENIE.match(str(tekst))
    if not m:
        raise BladKonfiguracji(f"Niepoprawne wyprzedzenie przypomnienia: {tekst!r} (użyj np. 3d, 1d, 1h, 30m)")
    n, jedn = int(m.group(1)), m.group(2).lower()
    if jedn == "d":
        etykieta = "1 dzień" if n == 1 else f"{n} dni"
        return Przypomnienie(etykieta, timedelta(days=n))
    if jedn == "h":
        etykieta = "1 godzinę" if n == 1 else f"{n} godz."
        return Przypomnienie(etykieta, timedelta(hours=n))
    return Przypomnienie(f"{n} min", timedelta(minutes=n))


def z_slownika(dane: dict) -> Konfiguracja:
    """Buduje konfigurację ze słownika (scalonego z domyślnymi)."""
    c = _scal(DOMYSLNE, dane)
    try:
        hh, mm = str(c["przypomnienia"]["godzina_startu_gdy_brak"]).replace(".", ":").split(":")
        godz_brak = time(int(hh), int(mm))
        przyp = sorted(
            (_parsuj_wyprzedzenie(x) for x in c["przypomnienia"]["przed_startem"]),
            key=lambda p: p.wyprzedzenie,
            reverse=True,
        )
        return Konfiguracja(
            url=str(c["url"]),
            moje_wojewodztwa=[str(w) for w in c["moje_wojewodztwa"]],
            strefa=ZoneInfo(str(c["strefa_czasowa"])),
            kanal=str(c["kanal"]).lower(),
            heartbeat_wlaczony=bool(c["heartbeat"]["wlaczony"]),
            heartbeat_godzina=int(c["heartbeat"]["godzina"]),
            przypomnienia=przyp,
            przypomnienia_tylko_moje=bool(c["przypomnienia"]["tylko_moje_wojewodztwa"]),
            godzina_startu_gdy_brak=godz_brak,
            prog_awarii=max(1, int(c["awaria"]["kolejne_bledy_do_alertu"])),
            timeout_s=float(c["pobieranie"]["timeout_s"]),
            ponowienia=max(0, int(c["pobieranie"]["ponowienia"])),
            backoff_s=float(c["pobieranie"]["backoff_s"]),
            user_agent=str(c["pobieranie"]["user_agent"]),
            selektory_tresci=[str(s) for s in c["ekstrakcja"]["selektory_tresci"]],
            selektor_dokumentow=str(c["ekstrakcja"]["selektor_dokumentow"]),
            oczekiwane_frazy=[str(f) for f in c["ekstrakcja"]["oczekiwane_frazy"]],
            min_linii=int(c["ekstrakcja"]["min_linii"]),
            log_max_wpisow=max(10, int(c["log"]["max_wpisow"])),
            surowe=c,
        )
    except BladKonfiguracji:
        raise
    except (KeyError, TypeError, ValueError) as e:
        raise BladKonfiguracji(f"Błąd w konfiguracji: {e}") from e


def wczytaj(sciezka: Path | str | None = None) -> Konfiguracja:
    """Wczytuje config.json (brak pliku = same wartości domyślne)."""
    p = Path(sciezka) if sciezka else DOMYSLNY_PLIK
    if not p.exists():
        if sciezka:
            raise BladKonfiguracji(f"Nie ma pliku konfiguracji: {p}")
        return z_slownika({})
    try:
        dane = json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise BladKonfiguracji(f"{p}: niepoprawny JSON ({e})") from e
    if not isinstance(dane, dict):
        raise BladKonfiguracji(f"{p}: oczekiwano obiektu JSON")
    return z_slownika(dane)
