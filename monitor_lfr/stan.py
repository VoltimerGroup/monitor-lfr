"""Trwały stan monitora (state/stan.json) i dziennik sprawdzeń (state/log.jsonl).

stan.json zmienia się TYLKO przy istotnych zdarzeniach (nowa wersja strony, wysłany
alert, przypomnienie, licznik błędów, heartbeat) oraz raz na dobę (znacznik „żyję”).
Dzięki temu workflow robi commit tylko wtedy, gdy jest po co – a raz dziennie na
pewno, żeby GitHub nie wyłączył harmonogramu po 60 dniach bez aktywności.
"""

from __future__ import annotations

import copy
import json
import os
import tempfile
from pathlib import Path

from .normalizacja import WERSJA_NORMALIZACJI

WERSJA_SCHEMATU = 1
MAKS_WYSLANYCH = 2000  # tyle skrótów wysłanych alertów pamiętamy (deduplikacja)

PUSTY_STAN: dict = {
    "wersja_schematu": WERSJA_SCHEMATU,
    "wersja_normalizacji": WERSJA_NORMALIZACJI,
    "strona": None,  # {"tresc": {...}, "hash": "...", "od": "ISO"}
    "wyslane": {},  # skrót fragmentu -> {"czas", "typ", "opis"}
    "przypomnienia": [],
    "bledy": {"kolejne": 0, "od": None, "pierwszy_blad": None, "alert_wyslany": False},
    "heartbeat": {"ostatni_dzien": None},
    "znacznik_zycia": None,
}


class BladStanu(Exception):
    """Uszkodzony plik stanu – wymaga ręcznej decyzji (nie nadpisujemy go po cichu)."""


def _zapisz_atomowo(sciezka: Path, tresc: str) -> None:
    sciezka.parent.mkdir(parents=True, exist_ok=True)
    fd, tymczasowy = tempfile.mkstemp(dir=sciezka.parent, prefix=sciezka.name, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
            f.write(tresc)
        os.replace(tymczasowy, sciezka)
    except BaseException:
        try:
            os.unlink(tymczasowy)
        except OSError:
            pass
        raise


class MagazynStanu:
    def __init__(self, katalog: Path | str):
        self.katalog = Path(katalog)
        self.plik_stanu = self.katalog / "stan.json"
        self.plik_logu = self.katalog / "log.jsonl"

    def wczytaj(self) -> dict:
        stan = copy.deepcopy(PUSTY_STAN)
        if not self.plik_stanu.exists():
            return stan
        try:
            dane = json.loads(self.plik_stanu.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            raise BladStanu(
                f"Uszkodzony plik stanu {self.plik_stanu}: {e}. Napraw go albo usuń "
                "(usunięcie = nowa wersja bazowa bez alertu)."
            ) from e
        if not isinstance(dane, dict):
            raise BladStanu(f"Plik stanu {self.plik_stanu} nie zawiera obiektu JSON.")
        for k, v in dane.items():
            if isinstance(v, dict) and isinstance(stan.get(k), dict) and k != "wyslane":
                stan[k].update(v)
            else:
                stan[k] = v
        return stan

    def zapisz(self, stan: dict) -> None:
        wyslane = stan.get("wyslane", {})
        if len(wyslane) > MAKS_WYSLANYCH:
            najnowsze = sorted(wyslane.items(), key=lambda kv: kv[1].get("czas", ""))[-MAKS_WYSLANYCH:]
            stan["wyslane"] = dict(najnowsze)
        _zapisz_atomowo(self.plik_stanu, json.dumps(stan, ensure_ascii=False, indent=1) + "\n")

    def dopisz_log(self, wpis: dict, maks_wpisow: int) -> None:
        """Dopisuje wpis i przycina plik do ostatnich `maks_wpisow` linii."""
        linie: list[str] = []
        if self.plik_logu.exists():
            linie = [l for l in self.plik_logu.read_text(encoding="utf-8", errors="replace").splitlines() if l.strip()]
        linie.append(json.dumps(wpis, ensure_ascii=False))
        _zapisz_atomowo(self.plik_logu, "\n".join(linie[-maks_wpisow:]) + "\n")
