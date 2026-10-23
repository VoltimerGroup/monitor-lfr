"""Tryb podglądu (--podglad): JEDNA wiadomość z aktualną treścią strony, stan nietknięty.

Bez sieci i bez Telegrama – kanał to atrapa albo konsola (--dry-run).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from conftest import BLOK_IV, PLIK_STRONY, T0, URL, AtrapaKanalu, Srodowisko, dopisz_na_gorze
from monitor_lfr import cli
from monitor_lfr import stan as modul_stanu
from monitor_lfr.cli import main
from monitor_lfr.ekstrakcja import Plik, Tresc, tytul_artykulu, wyciagnij_tresc
from monitor_lfr.kanaly import LIMIT_TELEGRAM
from monitor_lfr.konfiguracja import z_slownika
from monitor_lfr.monitor import podglad, tekst_podgladu, wpisy_strony
from monitor_lfr.pobieranie import BladPobierania, Odpowiedz
from monitor_lfr.wiadomosci import TYTUL_INFO, TYTUL_PILNY

# Dosłownie – test ma paść, gdy ktoś zmieni albo usunie oznaczenie (także w stałej).
PIERWSZA_LINIA = "🔎 PODGLĄD — aktualna treść strony (to NIE jest zmiana ani nowy nabór)"
NAJNOWSZY_WPIS_23_10 = ("Informujemy, że po przeprowadzeniu ponownej, szczegółowej weryfikacji terminów "
                        "wpływu wniosków na serwer pocztowy LFR")
TYTUL_STRONY = "Pierwszy Biznes - Wsparcie w Starcie - nabory od 2026"

# Fikcyjny komunikat bez cech naboru – prawdziwy przebieg dałby dla niego alert INFO.
BLOK_KOMUNIKAT = """
<p><strong>KOMUNIKAT TESTOWY</strong></p>
<p>Informujemy, że biuro Fundacji w Lublinie będzie nieczynne w dniu 2 listopada 2026 r.</p>
<p>&#8230;&#8230;&#8230;&#8230;&#8230;&#8230;&#8230;&#8230;&#8230;&#8230;</p>
"""


def _konfig_plik(tmp_path: Path) -> str:
    p = tmp_path / "config.json"
    p.write_text(json.dumps({"heartbeat": {"wlaczony": False}}), encoding="utf-8")
    return str(p)


def _podglad(html: str, teraz=T0) -> tuple[int, list[str]]:
    kanal = AtrapaKanalu()
    konfig = z_slownika({"heartbeat": {"wlaczony": False}})
    kod = podglad(konfig, kanal, zrodlo=lambda: Odpowiedz(status_http=200, html=html), zegar=lambda: teraz)
    return kod, kanal.wiadomosci


def _przyklad_alertu(wiadomosc: str) -> str:
    poczatek = wiadomosc.index("----- przykład alertu -----\n") + len("----- przykład alertu -----\n")
    return wiadomosc[poczatek: wiadomosc.index("\n----- koniec przykładu -----")]


# ------------------------------------------------------------------ treść wiadomości

def test_wiadomosc_zaczyna_sie_od_oznaczenia_podgladu(html_dzis):
    kod, wyslane = _podglad(html_dzis)
    assert kod == 0 and len(wyslane) == 1
    assert wyslane[0].splitlines()[0] == PIERWSZA_LINIA


def test_zawiera_najnowszy_wpis_a_nie_naglowek_strony(html_dzis):
    _, (wiadomosc,) = _podglad(html_dzis)
    # Najnowszy wpis w formie prawdziwego alertu INFO (stare nabory nie udają PILNEGO).
    assert TYTUL_INFO in wiadomosc and TYTUL_PILNY not in wiadomosc
    assert "1) Nowy/zmieniony fragment:\n" + NAJNOWSZY_WPIS_23_10 in wiadomosc
    # Data publikacji i tytuł <h1> to nagłówek strony, nie wpis.
    assert TYTUL_STRONY not in wiadomosc and "15.12.2025" not in wiadomosc
    assert "Klasyfikacja wpisu: INFO – inna zmiana\nDopasowane wzorce naboru: brak" in wiadomosc
    assert "- Skorygowana lista wniosków\n   https://www.lfr.lublin.pl/wp-content/uploads/" in wiadomosc
    assert "Dokumenty do pobrania: 26 plików." in wiadomosc


def test_lista_starszych_wpisow_z_data_startu_i_stopka(html_dzis):
    _, (wiadomosc,) = _podglad(html_dzis)
    # Dwa wpisy z nagłówkiem „III NABÓR…” (lista wniosków i ogłoszenie) – rozróżnione drugą linią.
    iii = "• start naboru 29.09.2026 8:30 – III NABÓR WNIOSKÓW O POŻYCZKĘ woj. lubelskie, mazowieckie, podlaskie – "
    assert ("Starsze wpisy na stronie:\n"
            "• Komunikat dotyczący usunięcia opublikowanej listy wniosków\n"
            f"{iii}Lista wniosków złożonych w ramach naboru z dnia 29.09.2026 r.") in wiadomosc
    assert f"\n{iii}Informujemy, że od dnia 29 września 2026 r." in wiadomosc
    assert "• start naboru 16.06.2026 8:30 – KOMUNIKAT: W związku z bardzo dużą liczbą" in wiadomosc
    assert "…i jeszcze 3 starsze wpisy na stronie." in wiadomosc
    # Godzina odczytu w czasie polskim i adres – na samym końcu.
    assert wiadomosc.endswith("\n\nOdczyt strony: piątek 23.10.2026, godz. 8:00 (Europe/Warsaw)\n" + URL)


def test_nowy_nabor_na_gorze_wyglada_jak_prawdziwy_alert_pilny(html_z_iv):
    _, (wiadomosc,) = _podglad(html_z_iv)
    przyklad = _przyklad_alertu(wiadomosc)
    assert przyklad.startswith(TYTUL_PILNY)
    assert "\nIV NABÓR WNIOSKÓW O POŻYCZKĘ woj. lubelskie, mazowieckie\n" in przyklad
    assert ">>> DOTYCZY TWOICH WOJEWÓDZTW: lubelskie, mazowieckie <<<" in przyklad
    assert "Start: piątek 15.01.2027, godz. 8:30" in przyklad and "Pula: 2 000 000,00 zł" in przyklad
    # Podgląd niczego nie planuje i mówi to wprost.
    assert "Przypomnienia: podgląd ich nie planuje" in przyklad
    assert "Klasyfikacja wpisu: PILNE – nowe ogłoszenie" in wiadomosc
    # Wcześniejszy „najnowszy” wpis przesunął się na listę starszych.
    assert "Starsze wpisy na stronie:\n• " + NAJNOWSZY_WPIS_23_10[:60] in wiadomosc


@pytest.mark.parametrize("blok, tytul", [(BLOK_IV, TYTUL_PILNY), (BLOK_KOMUNIKAT, TYTUL_INFO)])
def test_przyklad_alertu_to_ten_sam_tekst_co_w_prawdziwym_przebiegu(tmp_path, html_dzis, blok, tytul):
    """Jedyna różnica: linia o przypomnieniach (podgląd ich nie planuje)."""
    html = dopisz_na_gorze(html_dzis, blok)
    sr = Srodowisko(tmp_path / "state")
    sr.uruchom(html_dzis, T0)
    sr.uruchom(html, T0)
    prawdziwy = sr.nowe[0]
    assert prawdziwy.startswith(tytul)

    _, (wiadomosc,) = _podglad(html)

    def bez_przypomnien(tekst: str) -> list[str]:
        return [l for l in tekst.splitlines() if not l.startswith("Przypomnienia:")]

    assert bez_przypomnien(_przyklad_alertu(wiadomosc)) == bez_przypomnien(prawdziwy)


def test_wpisy_strony_odcinaja_naglowek_a_zostawiaja_go_w_kontekscie(html_dzis):
    konfig = z_slownika({})
    tytul = tytul_artykulu(html_dzis, konfig.selektory_tresci)
    assert tytul == [TYTUL_STRONY]
    tresc = wyciagnij_tresc(
        html_dzis, konfig.selektory_tresci, konfig.selektor_dokumentow, konfig.oczekiwane_frazy,
        konfig.min_linii, konfig.url)
    wpisy = wpisy_strony(tresc.linie, tytul)
    assert len(wpisy) == 9
    assert wpisy[0].nowe[0].startswith(NAJNOWSZY_WPIS_23_10)
    assert wpisy[0].kontekst[:2] == ["15.12.2025", TYTUL_STRONY]  # jak w prawdziwej Zmianie
    assert all(z.stare == [] and z.nowe for z in wpisy)


def test_dluga_wiadomosc_miesci_sie_w_limicie_telegrama_a_stopka_zostaje():
    konfig = z_slownika({})
    linie = []
    for i in range(12):
        linie += [f"Wpis {i}: " + "bardzo długi tytuł " * 20, "treść " * 50, "…………"]
    linki = [Plik(nazwa=f"plik {i}", url="https://example.invalid/" + "x" * 1500) for i in range(5)]
    tekst = tekst_podgladu(konfig, Tresc(linie=linie, dokumenty=[], linki=linki), T0)
    assert len(tekst) <= LIMIT_TELEGRAM
    assert tekst.splitlines()[0] == PIERWSZA_LINIA
    assert tekst.endswith("Odczyt strony: piątek 23.10.2026, godz. 8:00 (Europe/Warsaw)\n" + URL)


# ------------------------------------------------------------------ stan nietknięty

def _migawka(katalog: Path) -> dict[str, tuple[bytes, int]]:
    return {p.name: (p.read_bytes(), p.stat().st_mtime_ns) for p in sorted(katalog.iterdir())}


@pytest.mark.parametrize("jawny_katalog", [True, False], ids=["--stan-dir", "katalog domyślny"])
def test_podglad_nie_zmienia_plikow_stanu(tmp_path, capsys, monkeypatch, jawny_katalog):
    stan = tmp_path / "state"
    konfig = _konfig_plik(tmp_path)
    # Stan po zwykłym przebiegu: wersja bazowa + wpis w dzienniku.
    assert main(["--dry-run", "--plik", str(PLIK_STRONY), "--stan-dir", str(stan), "--config", konfig]) == 0
    przed = _migawka(stan)
    assert set(przed) == {"stan.json", "log.jsonl"}

    # Strona z NOWYM naborem: zwykły przebieg zmieniłby stan (alert, przypomnienia, wersja bazowa).
    zmieniona = tmp_path / "z_iv.html"
    zmieniona.write_text(dopisz_na_gorze(PLIK_STRONY.read_text(encoding="utf-8"), BLOK_IV), encoding="utf-8")

    def zakaz_zapisu(*_a, **_k):
        raise AssertionError("podgląd próbuje zapisać plik stanu")

    monkeypatch.setattr(modul_stanu, "_zapisz_atomowo", zakaz_zapisu)
    monkeypatch.setattr(cli, "DOMYSLNY_KATALOG_STANU", stan)
    capsys.readouterr()
    argumenty = ["--podglad", "--dry-run", "--plik", str(zmieniona), "--config", konfig]
    if jawny_katalog:
        argumenty += ["--stan-dir", str(stan)]
    kod = main(argumenty)
    wyjscie = capsys.readouterr().out
    assert kod == 0
    assert "[DRY-RUN]" in wyjscie and PIERWSZA_LINIA in wyjscie and TYTUL_PILNY in wyjscie
    assert "Podgląd strony wydrukowany (dry-run)." in wyjscie
    assert _migawka(stan) == przed  # te same pliki, bajt w bajt, bez ponownego zapisu


def test_podglad_nie_tworzy_katalogu_stanu(tmp_path, capsys):
    stan = tmp_path / "nie-ma"
    kod = main(["--podglad", "--dry-run", "--plik", str(PLIK_STRONY), "--stan-dir", str(stan),
                "--config", _konfig_plik(tmp_path)])
    assert kod == 0 and not stan.exists()


# ------------------------------------------------------------------ błędy

def test_blad_pobrania_kod_1_i_nic_nie_wyslano(tmp_path, capsys, monkeypatch):
    kanal = AtrapaKanalu()
    monkeypatch.setattr(cli, "kanal_z_srodowiska", lambda *_a, **_k: kanal)

    def pobierz(*_a, **_k):
        raise BladPobierania("Nie udało się pobrać strony po 4 próbach: HTTP 503", 503, 4)

    monkeypatch.setattr(cli, "pobierz_strone", pobierz)
    stan = tmp_path / "state"
    kod = main(["--podglad", "--stan-dir", str(stan), "--config", _konfig_plik(tmp_path)])
    bledy = capsys.readouterr().err
    assert kod == 1
    assert kanal.wiadomosci == []
    assert "PODGLĄD NIEUDANY – błąd pobrania strony: Nie udało się pobrać strony po 4 próbach: HTTP 503" in bledy
    assert not stan.exists()


def test_strona_bez_tresci_kod_1_i_nic_nie_wyslano(tmp_path, capsys, monkeypatch):
    kanal = AtrapaKanalu()
    monkeypatch.setattr(cli, "kanal_z_srodowiska", lambda *_a, **_k: kanal)
    plik = tmp_path / "przerwa.html"
    plik.write_text("<html><body><p>Przerwa techniczna</p></body></html>", encoding="utf-8")
    kod = main(["--podglad", "--plik", str(plik), "--config", _konfig_plik(tmp_path)])
    assert kod == 1 and kanal.wiadomosci == []
    assert "PODGLĄD NIEUDANY – nie da się wyciągnąć treści" in capsys.readouterr().err


def test_blad_wysylki_kod_1(html_dzis, capsys):
    kanal = AtrapaKanalu()
    kanal.awaria = True
    konfig = z_slownika({"heartbeat": {"wlaczony": False}})
    kod = podglad(konfig, kanal, zrodlo=lambda: Odpowiedz(status_http=200, html=html_dzis), zegar=lambda: T0)
    assert kod == 1
    assert "PODGLĄD NIEUDANY – błąd wysyłki: atrapa: kanał niedostępny" in capsys.readouterr().err


@pytest.mark.parametrize("dry_run", [False, True])
def test_podglad_razem_z_test_alert_to_czytelny_blad(tmp_path, capsys, monkeypatch, dry_run):
    """Dwie różne wiadomości – zamiast zgadywać kolejność: błąd (kod 2) i nic nie wysłane."""
    kanal = AtrapaKanalu()
    monkeypatch.setattr(cli, "kanal_z_srodowiska", lambda *_a, **_k: kanal)
    argumenty = ["--podglad", "--test-alert", "--config", _konfig_plik(tmp_path)] + (["--dry-run"] if dry_run else [])
    kod = main(argumenty)
    wyjscie = capsys.readouterr()
    assert kod == 2
    assert "BŁĄD: --podglad i --test-alert wykluczają się – uruchom każdą opcję osobno." in wyjscie.err
    assert kanal.wiadomosci == [] and "[DRY-RUN]" not in wyjscie.out
