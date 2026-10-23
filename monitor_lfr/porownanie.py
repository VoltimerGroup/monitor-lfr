"""Porównanie dwóch wersji strony – wynik to lista NOWYCH/zmienionych fragmentów.

* Linie porównujemy po kluczach (bez białych znaków, casefold) algorytmem difflib,
  więc sama zmiana odstępów, NBSP czy myślników nie daje żadnej różnicy.
* Jeżeli „całość” (sklejone klucze) się nie zmieniła, a zmienił się tylko podział
  na akapity – uznajemy, że zmiany nie ma.
* Separatory (linie bez liter i cyfr, np. „……………”) traktujemy jak jeden symbol.
"""

from __future__ import annotations

import difflib
from dataclasses import dataclass, field

from .ekstrakcja import Plik, Tresc
from .normalizacja import czy_separator, klucz, skrot

_SEP = "\x00separator"

# Rodzaje zmian
TEKST = "tekst"
TEKST_DOKUMENTOW = "tekst_dokumentow"
PLIK_NOWY = "plik_nowy"
PLIK_USUNIETY = "plik_usuniety"
PLIK_ZMIENIONY = "plik_zmieniony"
LINK_NOWY = "link_nowy"
LINK_USUNIETY = "link_usuniety"
LINK_ZMIENIONY = "link_zmieniony"


@dataclass
class Zmiana:
    rodzaj: str
    nowe: list[str] = field(default_factory=list)  # nowe linie (bez separatorów)
    stare: list[str] = field(default_factory=list)  # zastąpione/usunięte linie
    kontekst: list[str] = field(default_factory=list)  # sekcja ogłoszenia: od jej początku do końca fragmentu
    plik: Plik | None = None
    stary_plik: Plik | None = None

    @property
    def tekst_nowy(self) -> str:
        return "\n".join(self.nowe)

    @property
    def tekst_stary(self) -> str:
        return "\n".join(self.stare)

    @property
    def hash(self) -> str:
        """Skrót fragmentu do deduplikacji (odporny na białe znaki)."""
        if self.plik is not None or self.stary_plik is not None:
            p = self.plik or self.stary_plik
            return skrot(f"{self.rodzaj}\n{p.klucz}\n{p.klucz_nazwy}")
        if self.nowe:
            return skrot(f"{self.rodzaj}\n" + "\n".join(klucz(l) for l in self.nowe))
        return skrot(f"{self.rodzaj}-usuniete\n" + "\n".join(klucz(l) for l in self.stare))


def _klucze(linie: list[str]) -> list[str]:
    return [_SEP if czy_separator(l) else klucz(l) for l in linie]


def _roznice_linii(stare: list[str], nowe: list[str], rodzaj: str) -> list[Zmiana]:
    ks, kn = _klucze(stare), _klucze(nowe)
    if "".join(k for k in ks if k != _SEP) == "".join(k for k in kn if k != _SEP):
        return []  # identyczna treść (najwyżej inny podział na linie / separatory)
    wynik: list[Zmiana] = []
    sm = difflib.SequenceMatcher(None, ks, kn, autojunk=False)
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            continue
        st = [l for l in stare[i1:i2] if not czy_separator(l)]
        nw = [l for l in nowe[j1:j2] if not czy_separator(l)]
        if not st and not nw:
            continue  # dodano/usunięto sam separator
        if "".join(klucz(l) for l in st) == "".join(klucz(l) for l in nw):
            continue  # tylko inny podział tego samego tekstu
        wynik.append(Zmiana(rodzaj=rodzaj, nowe=nw, stare=st, kontekst=_kontekst(nowe, j1, j2) if nw else []))
    return wynik


def _kontekst(linie: list[str], j1: int, j2: int) -> list[str]:
    """Linie sekcji (między separatorami) od jej początku do końca fragmentu.

    Bierzemy tylko to, co PRZED i W fragmencie – żeby przy ogłoszeniu dopisanym na
    górze nie „pożyczyć” daty czy kwoty z następnego (starszego) ogłoszenia.
    """
    start = j1
    while start > 0 and not czy_separator(linie[start - 1]):
        start -= 1
    return [l for l in linie[start:j2] if not czy_separator(l)]


def _roznice_plikow(stare: list[Plik], nowe: list[Plik], nowy: str, usuniety: str, zmieniony: str) -> list[Zmiana]:
    st = {p.klucz: p for p in stare}
    nw = {p.klucz: p for p in nowe}
    dodane = [p for k, p in nw.items() if k not in st]
    usuniete = [p for k, p in st.items() if k not in nw]
    wynik: list[Zmiana] = []
    # Ten sam adres, inna nazwa -> zmiana opisu pliku.
    for k, p in nw.items():
        if k in st and st[k].klucz_nazwy != p.klucz_nazwy:
            wynik.append(Zmiana(rodzaj=zmieniony, plik=p, stary_plik=st[k]))
    # Ta sama nazwa, inny adres -> nowa wersja pliku (np. zaktualizowany regulamin).
    po_nazwie = {p.klucz_nazwy: p for p in usuniete}
    for p in dodane:
        stary = po_nazwie.pop(p.klucz_nazwy, None)
        if stary is not None:
            usuniete.remove(stary)
            wynik.append(Zmiana(rodzaj=zmieniony, plik=p, stary_plik=stary))
        else:
            wynik.append(Zmiana(rodzaj=nowy, plik=p))
    for p in usuniete:
        wynik.append(Zmiana(rodzaj=usuniety, stary_plik=p))
    return wynik


def porownaj(stara: Tresc, nowa: Tresc) -> list[Zmiana]:
    """Zwraca zmiany (w kolejności: treść, dokumenty, odnośniki)."""
    zmiany = _roznice_linii(stara.linie, nowa.linie, TEKST)
    if stara.dokumenty is not None and nowa.dokumenty is not None:
        zmiany += _roznice_plikow(stara.dokumenty, nowa.dokumenty, PLIK_NOWY, PLIK_USUNIETY, PLIK_ZMIENIONY)
        zmiany += _roznice_linii(stara.linie_dokumentow, nowa.linie_dokumentow, TEKST_DOKUMENTOW)
    zmiany += _roznice_plikow(stara.linki, nowa.linki, LINK_NOWY, LINK_USUNIETY, LINK_ZMIENIONY)
    return zmiany
