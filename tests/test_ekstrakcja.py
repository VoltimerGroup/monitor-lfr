"""Ekstrakcja głównej treści i normalizacja tekstu."""

from __future__ import annotations

import pytest

from conftest import URL
from monitor_lfr.ekstrakcja import BladEkstrakcji, wyciagnij_tresc
from monitor_lfr.konfiguracja import z_slownika
from monitor_lfr.normalizacja import czy_separator, klucz, normalizuj

K = z_slownika({})


def _wyciagnij(html: str):
    return wyciagnij_tresc(html, K.selektory_tresci, K.selektor_dokumentow, K.oczekiwane_frazy, K.min_linii, URL)


# ------------------------------------------------------------------ normalizacja

def test_normalizacja_bialych_znakow_myslnikow_i_cudzyslowow():
    assert normalizuj("  Pierwszy Biznes – Wsparcie—w−Starcie \n\t ") == "Pierwszy Biznes - Wsparcie-w-Starcie"
    assert normalizuj("„Pierwszy biznes”") == '"Pierwszy biznes"'
    assert normalizuj("po­życzka​") == "pożyczka"
    assert normalizuj("ó") == "ó"  # litera rozłożona -> złożona
    assert normalizuj("4 166 250,00 zł") == "4 166 250,00 zł"


def test_klucz_ignoruje_odstepy_i_wielkosc_liter():
    assert klucz("2026 r . (od godz. 8:30)") == klucz("2026 r. (od  godz. 8:30)")
    assert klucz("NABÓR ZAMKNIĘTY") == klucz("nabór zamknięty")
    assert klucz("NABÓR – ZAMKNIĘTY") == klucz("NABÓR - ZAMKNIĘTY")
    assert klucz("NABÓR ZAMKNIĘTY") != klucz("NABÓR OTWARTY")


def test_separator():
    assert czy_separator(normalizuj("……………………………."))
    assert czy_separator("----")
    assert not czy_separator("III NABÓR")


# ------------------------------------------------------------------ ekstrakcja na kopii strony

def test_treść_dzisiejszej_strony(html_dzis: str):
    t = _wyciagnij(html_dzis)
    assert len(t.linie) > 150
    assert t.linie[1] == "Pierwszy Biznes - Wsparcie w Starcie - nabory od 2026"
    tekst = "\n".join(t.linie)
    for fraza in ["III NABÓR WNIOSKÓW O POŻYCZKĘ woj. lubelskie, mazowieckie, podlaskie",
                  "Informujemy, że od dnia 29 września 2026 r. (od godz. 8:30)",
                  "I NABÓR WNIOSKÓW O POŻYCZKĘ - woj. podkarpackie"]:
        assert fraza in tekst
    # bez menu, stopki, przycisków zakładek, banera newslettera/cookies, skryptów
    for smiec in ["O FUNDACJI", "PROJEKT I REALIZACJA", "Wyrażam zgodę na otrzymywanie",
                  "FORMY WSPARCIA", "DOKUMENTY DO POBRANIA", "function(", "gtag"]:
        assert smiec not in tekst, smiec
    # pliki z zakładki „Dokumenty do pobrania” (część bez linku – też liczymy)
    assert t.dokumenty is not None and len(t.dokumenty) == 26
    assert t.dokumenty[0].nazwa.startswith("Regulamin udzielania pożyczek")
    assert t.dokumenty[0].url.endswith("Regulamin-nr-3-FERS-aktualizacja.pdf")
    assert sum(1 for p in t.dokumenty if p.url is None) == 6  # załączniki 7–12 bez linków
    assert "DOKUMENTY:" in t.linie_dokumentow
    # odnośnik w treści (lista wniosków)
    assert any("Lista-wnioskow" in p.url for p in t.linki)


def test_brak_kontenera_to_blad_ekstrakcji(html_dzis: str):
    with pytest.raises(BladEkstrakcji, match="kontenera"):
        _wyciagnij(html_dzis.replace("institution management entry", "inny-uklad"))


def test_strona_bez_tresci_wskazuje_na_javascript_lub_blokade():
    html = ('<html><body><div class="institution entry"><div class="area"><div class="text">'
            '<div id="app"></div></div></div></div><script>render()</script></body></html>')
    with pytest.raises(BladEkstrakcji, match="JavaScript"):
        _wyciagnij(html)


def test_pusta_odpowiedz_to_blad():
    with pytest.raises(BladEkstrakcji):
        _wyciagnij("   ")


def test_hash_tresci_odporny_na_podzial_linii(html_dzis: str):
    a = _wyciagnij(html_dzis)
    b = _wyciagnij(html_dzis.replace("Dziękujemy za cierpliwość i wyrozumiałość.",
                                     "Dziękujemy za cierpliwość<br/>i wyrozumiałość."))
    assert a.linie != b.linie
    assert a.hash_tresci() == b.hash_tresci()
