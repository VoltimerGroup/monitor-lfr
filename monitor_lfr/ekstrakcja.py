"""Wyciąganie WYŁĄCZNIE głównej treści artykułu ze strony LFR.

Struktura strony (ustalona na kopii z 23.10.2026, tests/fixtures/strona_2026-10-23.html):

    div.institution.management.entry
      div.bg > div.area > ul.breadcrumb              <- okruszki (pomijamy)
      div.area > div.text                            <- GŁÓWNA TREŚĆ (kontener)
        div.photo (data publikacji + obrazek)
        h1, p, ul ...                                <- ogłoszenia, najnowsze NA GÓRZE,
                                                        rozdzielone liniami „…………”
        div.area-bottom-button                       <- przyciski zakładek (pomijamy)
        div#formy-wsparcia.additional-field          <- zakładka „Formy wsparcia” (treść)
        div#dokumenty-do-pobrania.additional-field   <- zakładka „Dokumenty do pobrania”
          div.p-files > a[href]                      <- pojedynczy plik (czasem bez linku)

Menu, stopka, baner cookies (brave_popup) i skrypty leżą POZA kontenerem.
Treść jest w statycznym HTML (bez JavaScriptu) – Playwright niepotrzebny.
"""

from __future__ import annotations

import importlib.util
from dataclasses import dataclass, field
from urllib.parse import urljoin, urlsplit, urlunsplit

from bs4 import BeautifulSoup
from bs4.element import NavigableString, PreformattedString, Tag

from .normalizacja import czy_separator, klucz, normalizuj, skrot

# Elementy, które zawsze usuwamy z kontenera (nie niosą treści dla człowieka).
_USUWANE_TAGI = [
    "script", "style", "noscript", "template", "iframe", "svg", "form", "button",
    "input", "select", "textarea", "img", "picture", "video", "audio", "object",
    "embed", "canvas", "link", "meta",
]
# Selektory CSS usuwanych fragmentów: przyciski zakładek, ewentualne cookies/popupy.
_USUWANE_SELEKTORY = [
    ".area-bottom-button",
    "[class*=cookie]", "[id*=cookie]", "[class*=popup]", "[id*=popup]",
]

# Elementy blokowe – każdy zaczyna nową „linię” tekstu.
_BLOKOWE = {
    "address", "article", "aside", "blockquote", "dd", "details", "div", "dl", "dt",
    "fieldset", "figcaption", "figure", "footer", "h1", "h2", "h3", "h4", "h5", "h6",
    "header", "hr", "li", "main", "nav", "ol", "p", "pre", "section", "summary",
    "table", "tbody", "td", "tfoot", "th", "thead", "tr", "ul", "center",
}


class BladEkstrakcji(Exception):
    """Nie da się wyciągnąć treści (np. zmiana HTML, treść ładowana JavaScriptem)."""


@dataclass
class Plik:
    """Pozycja z sekcji „Dokumenty do pobrania” albo odnośnik w treści."""

    nazwa: str
    url: str | None = None

    @property
    def klucz(self) -> str:
        return "url:" + _klucz_url(self.url) if self.url else "tekst:" + klucz(self.nazwa)

    @property
    def klucz_nazwy(self) -> str:
        return klucz(self.nazwa)

    def do_json(self) -> dict:
        return {"nazwa": self.nazwa, "url": self.url}

    @staticmethod
    def z_json(d: dict) -> "Plik":
        return Plik(nazwa=d.get("nazwa", ""), url=d.get("url"))


@dataclass
class Tresc:
    """Wynik ekstrakcji: linie artykułu + pliki + odnośniki."""

    linie: list[str]
    dokumenty: list[Plik] | None  # None = sekcji „Dokumenty do pobrania” nie znaleziono
    linie_dokumentow: list[str] = field(default_factory=list)  # tekst sekcji poza plikami
    linki: list[Plik] = field(default_factory=list)

    def hash_tresci(self) -> str:
        """Skrót odporny na podział na linie i białe znaki (porównanie „całości”)."""
        return skrot("".join(klucz(l) for l in self.linie if not czy_separator(l)))

    def hash_calosci(self) -> str:
        czesci = [self.hash_tresci()]
        czesci += sorted(p.klucz + "|" + p.klucz_nazwy for p in (self.dokumenty or []))
        czesci += [klucz(l) for l in self.linie_dokumentow]
        czesci += sorted(p.klucz for p in self.linki)
        return skrot("\n".join(czesci))

    def do_json(self) -> dict:
        return {
            "linie": self.linie,
            "dokumenty": None if self.dokumenty is None else [p.do_json() for p in self.dokumenty],
            "linie_dokumentow": self.linie_dokumentow,
            "linki": [p.do_json() for p in self.linki],
        }

    @staticmethod
    def z_json(d: dict) -> "Tresc":
        dok = d.get("dokumenty")
        return Tresc(
            linie=list(d.get("linie", [])),
            dokumenty=None if dok is None else [Plik.z_json(x) for x in dok],
            linie_dokumentow=list(d.get("linie_dokumentow", [])),
            linki=[Plik.z_json(x) for x in d.get("linki", [])],
        )


def _klucz_url(url: str) -> str:
    """Porównujemy adresy bez fragmentu (#...) i bez rozróżniania wielkości liter hosta."""
    cz = urlsplit(url.strip())
    return urlunsplit((cz.scheme.lower(), cz.netloc.lower(), cz.path, cz.query, ""))


def _parser() -> str:
    """lxml (szybki, z requirements.txt); awaryjnie wbudowany parser Pythona."""
    return "lxml" if importlib.util.find_spec("lxml") else "html.parser"


def linie_blokowe(element: Tag) -> list[str]:
    """Zamienia drzewo HTML na listę znormalizowanych linii (jak przeglądarka tekstowa).

    Elementy blokowe i <br> kończą linię; elementy liniowe (a, strong, span…)
    sklejają się z otaczającym tekstem. Puste linie są pomijane.
    """
    linie: list[str] = []
    bufor: list[str] = []

    def zrzuc() -> None:
        tekst = normalizuj("".join(bufor))
        bufor.clear()
        if tekst:
            linie.append(tekst)

    def przejdz(wezel: Tag) -> None:
        for dziecko in wezel.children:
            if isinstance(dziecko, NavigableString):
                if not isinstance(dziecko, PreformattedString):  # komentarze, CDATA itp.
                    bufor.append(str(dziecko))
            elif isinstance(dziecko, Tag):
                if dziecko.name == "br":
                    zrzuc()
                elif dziecko.name in _BLOKOWE:
                    zrzuc()
                    przejdz(dziecko)
                    zrzuc()
                else:
                    przejdz(dziecko)

    przejdz(element)
    zrzuc()
    return linie


def _odnosniki(element: Tag, baza: str) -> list[Plik]:
    wynik: list[Plik] = []
    widziane: set[str] = set()
    for a in element.select("a[href]"):
        href = (a.get("href") or "").strip()
        if not href or href.startswith(("#", "mailto:", "javascript:", "tel:")):
            continue
        p = Plik(nazwa=normalizuj(a.get_text(" ")) or href, url=urljoin(baza, href))
        if p.klucz not in widziane:
            widziane.add(p.klucz)
            wynik.append(p)
    return wynik


def _pliki_sekcji(sekcja: Tag, baza: str) -> tuple[list[Plik], list[str]]:
    """Pliki z sekcji „Dokumenty do pobrania” + tekst sekcji spoza pozycji plików."""
    pliki: list[Plik] = []
    pozycje = sekcja.select(".p-files")
    if pozycje:
        for poz in pozycje:
            a = poz.find("a", href=True)
            url = urljoin(baza, a["href"].strip()) if a and a["href"].strip() else None
            nazwa = normalizuj(poz.get_text(" "))
            if nazwa or url:
                pliki.append(Plik(nazwa=nazwa or (url or ""), url=url))
        for poz in pozycje:
            poz.extract()  # reszta sekcji to nagłówki/opisy
    else:
        pliki = _odnosniki(sekcja, baza)
        for a in sekcja.select("a[href]"):
            a.extract()
    return pliki, linie_blokowe(sekcja)


def wyciagnij_tresc(
    html: str,
    selektory: list[str],
    selektor_dokumentow: str,
    oczekiwane_frazy: list[str],
    min_linii: int = 10,
    url_bazowy: str = "",
) -> Tresc:
    """Zwraca `Tresc` albo rzuca `BladEkstrakcji` (z podpowiedzią, co się stało)."""
    if not html or not html.strip():
        raise BladEkstrakcji("Pusta odpowiedź (brak HTML).")
    zupa = BeautifulSoup(html, _parser())

    kontener = None
    for sel in selektory:
        kontener = zupa.select_one(sel)
        if kontener is not None:
            break
    if kontener is None:
        raise BladEkstrakcji(
            "Nie znaleziono kontenera głównej treści (selektory: "
            + ", ".join(selektory) + "). " + _podpowiedz(html, oczekiwane_frazy)
        )

    for tag in kontener.find_all(_USUWANE_TAGI):
        tag.decompose()
    for sel in _USUWANE_SELEKTORY:
        for el in kontener.select(sel):
            el.decompose()

    dokumenty: list[Plik] | None = None
    linie_dok: list[str] = []
    sekcja_dok = kontener.select_one(selektor_dokumentow) if selektor_dokumentow else None
    if sekcja_dok is not None:
        sekcja_dok.extract()  # dokumenty monitorujemy osobno (pliki), nie jako linie artykułu
        dokumenty, linie_dok = _pliki_sekcji(sekcja_dok, url_bazowy)

    linki = _odnosniki(kontener, url_bazowy)
    linie = linie_blokowe(kontener)

    calosc = " ".join(linie).casefold()
    brakujace = [f for f in oczekiwane_frazy if normalizuj(f).casefold() not in calosc]
    if brakujace:
        raise BladEkstrakcji(
            "W treści brak oczekiwanych fraz: " + ", ".join(repr(f) for f in brakujace) + ". "
            + _podpowiedz(html, oczekiwane_frazy)
        )
    if len(linie) < min_linii:
        raise BladEkstrakcji(
            f"Za mało treści: {len(linie)} linii (minimum {min_linii}). " + _podpowiedz(html, oczekiwane_frazy)
        )
    return Tresc(linie=linie, dokumenty=dokumenty, linie_dokumentow=linie_dok, linki=linki)


def _podpowiedz(html: str, frazy: list[str]) -> str:
    """Rozróżnia „treść ładowana JavaScriptem” od „zmienił się układ HTML”."""
    surowy = normalizuj(BeautifulSoup(html, _parser()).get_text(" ")).casefold()
    if frazy and all(normalizuj(f).casefold() not in surowy for f in frazy):
        return ("Oczekiwanych fraz nie ma nawet w surowym HTML – możliwa blokada (np. strona "
                "z wyzwaniem anty-bot), błąd serwera albo treść ładowana JavaScriptem.")
    return "Frazy są w HTML, ale poza kontenerem – prawdopodobnie zmienił się układ strony (selektory)."
