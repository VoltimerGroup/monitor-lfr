"""Wspólne narzędzia testów: kopia strony, atrapa kanału, środowisko z „restartem” przy każdym przebiegu.

Testy NIE korzystają z sieci ani z Telegrama.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

KATALOG_REPO = Path(__file__).resolve().parent.parent
if str(KATALOG_REPO) not in sys.path:
    sys.path.insert(0, str(KATALOG_REPO))

from monitor_lfr.kanaly import BladWysylki  # noqa: E402
from monitor_lfr.konfiguracja import z_slownika  # noqa: E402
from monitor_lfr.monitor import Monitor, WynikPrzebiegu  # noqa: E402
from monitor_lfr.pobieranie import BladPobierania, Odpowiedz  # noqa: E402
from monitor_lfr.stan import MagazynStanu  # noqa: E402

FIXTURES = Path(__file__).resolve().parent / "fixtures"
PLIK_STRONY = FIXTURES / "strona_2026-10-23.html"
WAW = ZoneInfo("Europe/Warsaw")
URL = "https://www.lfr.lublin.pl/projekty/pierwszy-biznes-wsparcie-w-starcie-2025/"

# Fikcyjne ogłoszenie IV naboru – w formacie, w jakim LFR publikował poprzednie.
BLOK_IV = """
<p><strong>IV NABÓR WNIOSKÓW O POŻYCZKĘ woj. lubelskie, mazowieckie</strong></p>
<p>Informujemy, że od dnia <strong>15 stycznia 2027 r.</strong> (od godz. 8:30) Lubelska Fundacja Rozwoju
przyjmować będzie wnioski o niskooprocentowaną pożyczkę na podjęcie działalności gospodarczej w ramach
Instrumentu Finansowego Pierwszy biznes &#8211; Wsparcie w starcie:</p>
<ul>
<li>dla wnioskodawców planujących rozpoczęcie działalności gospodarczej w woj. lubelskim i mazowieckim
&#8211; kwota do dyspozycji w ramach naboru &#8211; 2&nbsp;000&nbsp;000,00 zł</li>
</ul>
<p>Wnioski w formie papierowej można składać wyłącznie we wskazanych poniżej biurach Lubelskiej Fundacji Rozwoju:</p>
<p>&#8230;&#8230;&#8230;&#8230;&#8230;&#8230;&#8230;&#8230;&#8230;&#8230;&#8230;&#8230;&#8230;&#8230;</p>
"""

ZNACZNIK_H1 = "nabory od 2026</h1>"
ZNACZNIK_DOKUMENTOW = '<div id="dokumenty-do-pobrania" class="additional-field">'


def dopisz_na_gorze(html: str, blok: str) -> str:
    """Wstawia blok zaraz pod tytułem artykułu (LFR dopisuje nowe ogłoszenia NA GÓRZE)."""
    assert html.count(ZNACZNIK_H1) == 1
    return html.replace(ZNACZNIK_H1, ZNACZNIK_H1 + blok, 1)


def w_warszawie(*args) -> datetime:
    return datetime(*args, tzinfo=WAW)


# Domyślny „teraz” testów: 23.10.2026 8:00 (przed heartbeatem o 9:00).
T0 = w_warszawie(2026, 10, 23, 8, 0)


class AtrapaKanalu:
    """Zamiast Telegrama – zbiera wiadomości; można zasymulować awarię wysyłki."""

    nazwa = "atrapa"

    def __init__(self):
        self.wiadomosci: list[str] = []
        self.awaria = False

    def wyslij(self, tekst: str) -> None:
        if self.awaria:
            raise BladWysylki("atrapa: kanał niedostępny")
        self.wiadomosci.append(tekst)


class Srodowisko:
    """Każde `uruchom()` tworzy NOWY Monitor czytający stan z dysku (jak restart w Actions)."""

    def __init__(self, katalog: Path, **konfig):
        konfig.setdefault("heartbeat", {"wlaczony": False})
        konfig.setdefault("pobieranie", {"backoff_s": 0})
        self.katalog = katalog
        self.konfig = z_slownika(konfig)
        self.kanal = AtrapaKanalu()
        self.nowe: list[str] = []

    def uruchom(self, html: str | None, teraz: datetime = T0) -> WynikPrzebiegu:
        def zrodlo() -> Odpowiedz:
            if html is None:
                raise BladPobierania("Nie udało się pobrać strony po 4 próbach: ConnectTimeout (atrapa)", None, 4)
            return Odpowiedz(status_http=200, html=html)

        przed = len(self.kanal.wiadomosci)
        monitor = Monitor(self.konfig, self.kanal, MagazynStanu(self.katalog), zrodlo=zrodlo,
                          zegar=lambda: teraz, wypisz=lambda s: None)
        wynik = monitor.przebieg()
        self.nowe = self.kanal.wiadomosci[przed:]
        return wynik

    def stan(self) -> dict:
        return json.loads((self.katalog / "stan.json").read_text(encoding="utf-8"))

    def surowy_stan(self) -> bytes:
        return (self.katalog / "stan.json").read_bytes()


@pytest.fixture(scope="session")
def html_dzis() -> str:
    return PLIK_STRONY.read_text(encoding="utf-8")


@pytest.fixture(scope="session")
def html_z_iv(html_dzis: str) -> str:
    return dopisz_na_gorze(html_dzis, BLOK_IV)


@pytest.fixture
def srodowisko(tmp_path: Path) -> Srodowisko:
    return Srodowisko(tmp_path / "state")


@pytest.fixture
def po_bazie(srodowisko: Srodowisko, html_dzis: str) -> Srodowisko:
    """Środowisko z zapisaną wersją bazową (dzisiejsza strona)."""
    srodowisko.uruchom(html_dzis, T0)
    assert srodowisko.nowe == []
    return srodowisko


