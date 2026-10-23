"""Wzorce PILNE, wyciąganie danych naboru i reguły klasyfikacji."""

from __future__ import annotations

from datetime import date, time, timedelta
from decimal import Decimal

import pytest

from conftest import WAW, w_warszawie
from monitor_lfr.klasyfikacja import (
    INFO, PILNE, dopasowane_wzorce, kanoniczne_wojewodztwo, klasyfikuj, wyciagnij_dane, wyciagnij_kwoty,
    wyciagnij_numer, wyciagnij_start, wyciagnij_wojewodztwa,
)
from monitor_lfr.normalizacja import normalizuj
from monitor_lfr.porownanie import TEKST, Zmiana

TERAZ = w_warszawie(2026, 10, 23, 12, 0)
GODZ_8 = time(8, 0)


def _n(t: str) -> str:
    return normalizuj(t)


# ------------------------------------------------------------------ wzorce

@pytest.mark.parametrize("tekst, wzorzec", [
    ("IV NABÓR WNIOSKÓW O POŻYCZKĘ woj. lubelskie", "NABÓR WNIOSKÓW"),
    ("iv nabor wnioskow o pozyczke", "NABÓR WNIOSKÓW"),
    ("Lubelska Fundacja Rozwoju przyjmować będzie wnioski o pożyczkę", "przyjmować będzie wnioski"),
    ("LFR będzie przyjmować wnioski", "przyjmować będzie wnioski"),
    ("Informujemy, że od dnia 15 stycznia 2027 r. (od godz. 8:30)", "od dnia … (od godz."),
    ("Informujemy, że od dnia 15.01.2027 r. ( od godz. 8.30)", "od dnia … (od godz."),
    ("Kwota do dyspozycji w ramach naboru — 2 000 000,00 zł", "kwota do dyspozycji"),
    ("kolejny nabór planowany jest na marzec 2027 r.", "planowany jest"),
    ("Rozpoczęcie naboru – 29.09.2026 godz. 8:30", "Rozpoczęcie naboru"),
    ("ROZPOCZECIE NABORU - 29.09.2026", "Rozpoczęcie naboru"),
])
def test_wzorce_pilne_rozne_zapisy(tekst, wzorzec):
    assert wzorzec in dopasowane_wzorce(_n(tekst))


@pytest.mark.parametrize("tekst", [
    "Lista wniosków złożonych w ramach naboru",
    "Dziękujemy za cierpliwość i wyrozumiałość.",
    "Wnioski oceniane będą w kolejności wpływu.",
    "Tabela prowizji i opłat",
])
def test_zwykly_tekst_nie_pasuje_do_wzorcow(tekst):
    assert dopasowane_wzorce(_n(tekst)) == []


# ------------------------------------------------------------------ daty i godziny

@pytest.mark.parametrize("tekst, data, godzina", [
    ("Informujemy, że od dnia 15 stycznia 2027 r. (od godz. 8:30) LFR", date(2027, 1, 15), time(8, 30)),
    ("od dnia 8 stycznia 2026 r. (od godz. 8.00)", date(2026, 1, 8), time(8, 0)),
    ("Rozpoczęcie naboru – 29.09.2026 godz. 8:30\nWstrzymanie naboru – 29.09.2026 godz. 09:20",
     date(2026, 9, 29), time(8, 30)),
    ("od dnia 1 października 2027 r. (od godz. 10:15)", date(2027, 10, 1), time(10, 15)),
    ("OD DNIA 3 PAZDZIERNIKA 2027 R. (OD GODZ. 7.45)", date(2027, 10, 3), time(7, 45)),
    ("od dnia 2027-02-01 (od godz. 8:30)", date(2027, 2, 1), time(8, 30)),
    ("od dnia 5.3.2027 r.", date(2027, 3, 5), None),
    ("nabór rozpocznie się 12 lutego 2027 r. o godz. 9:00", date(2027, 2, 12), time(9, 0)),
])
def test_data_i_godzina_startu(tekst, data, godzina):
    d, g, pewna = wyciagnij_start(_n(tekst), 2026)
    assert (d, g, pewna) == (data, godzina, True)


def test_data_bez_roku_br_to_biezacy_rok():
    d, g, _ = wyciagnij_start(_n("od dnia 16 czerwca br. (od godz. 8:30)"), 2027)
    assert (d, g) == (date(2027, 6, 16), time(8, 30))


def test_data_bez_slowa_kotwicy_ma_niska_pewnosc():
    d, _, pewna = wyciagnij_start(_n("termin ZMIENIONY NA 20 kwietnia 2026 r."), 2026)
    assert d == date(2026, 4, 20) and pewna is False


def test_z_dnia_nie_jest_data_startu_gdy_jest_od_dnia():
    tekst = _n("Lista wniosków z naboru z dnia 29.09.2026 r. Kolejny nabór od dnia 15.01.2027 r. (od godz. 8:30)")
    d, g, _ = wyciagnij_start(tekst, 2026)
    assert (d, g) == (date(2027, 1, 15), time(8, 30))


def test_niepoprawna_data_jest_pomijana():
    d, _, _ = wyciagnij_start(_n("od dnia 31.02.2027 r."), 2026)
    assert d is None


# ------------------------------------------------------------------ kwoty, numer, województwa

@pytest.mark.parametrize("tekst, kwoty", [
    ("kwota do dyspozycji w ramach naboru – 2 000 000,00 zł", [Decimal("2000000.00")]),
    ("Kwota do dyspozycji w ramach naboru – 4 166 250,00 zł", [Decimal("4166250.00")]),
    ("kwota do dyspozycji: 4.162.500,00 zł", [Decimal("4162500.00")]),
    ("kwota do dyspozycji w ramach naboru 1 300 000 zł", [Decimal("1300000")]),
    ("nr 323 – kwota do dyspozycji w ramach naboru 1 300 000,00 zł\nnr 259 – kwota do dyspozycji 300 000,00 zł",
     [Decimal("1300000.00"), Decimal("300000.00")]),
])
def test_kwoty(tekst, kwoty):
    assert wyciagnij_kwoty(_n(tekst)) == kwoty


@pytest.mark.parametrize("tekst, numer", [
    ("IV NABÓR WNIOSKÓW O POŻYCZKĘ", ("IV", 4)),
    ("I NABÓR WNIOSKÓW O POŻYCZKĘ – woj. podkarpackie", ("I", 1)),
    ("XII NABÓR WNIOSKÓW", ("XII", 12)),
    ("4. nabór wniosków o pożyczkę", ("4", 4)),
    ("nabór nr 5 rozpocznie się", ("5", 5)),
    ("NABÓR ZAMKNIĘTY", (None, None)),
    ("Umowa Operacyjna nr 2/WWS/1025/2025/IV/EFS/323", (None, None)),
])
def test_numer_naboru(tekst, numer):
    assert wyciagnij_numer(_n(tekst)) == numer


@pytest.mark.parametrize("tekst, woj", [
    ("IV NABÓR WNIOSKÓW O POŻYCZKĘ woj. lubelskie, mazowieckie", ["lubelskie", "mazowieckie"]),
    ("w woj. lubelskim, mazowieckim i podlaskim (Umowa Operacyjna nr 2/WWS)", ["lubelskie", "mazowieckie", "podlaskie"]),
    ("Lubelska Fundacja Rozwoju przyjmować będzie wnioski", []),
    ("woj. kujawsko–pomorskie i pomorskie", ["kujawsko-pomorskie", "pomorskie"]),
    ("w województwie dolnośląskim i śląskim", ["dolnośląskie", "śląskie"]),
    ("obejmujący województwa: lubelskie, mazowieckie, podlaskie i warmińsko-mazurskie",
     ["lubelskie", "mazowieckie", "podlaskie", "warmińsko-mazurskie"]),
    ("woj. małopolskie i podkarpackie", ["małopolskie", "podkarpackie"]),
])
def test_wojewodztwa(tekst, woj):
    assert wyciagnij_wojewodztwa(_n(tekst)) == woj


def test_kanoniczne_wojewodztwo_z_konfiguracji():
    assert kanoniczne_wojewodztwo("Mazowieckie") == "mazowieckie"
    assert kanoniczne_wojewodztwo("lubelskim") == "lubelskie"


def test_brakujace_dane_uzupelniane_z_kontekstu_sekcji():
    kontekst = _n("V NABÓR WNIOSKÓW O POŻYCZKĘ woj. lubelskie\n"
                  "Informujemy, że od dnia 3 marca 2027 r. (od godz. 8:30) LFR przyjmować będzie wnioski\n"
                  "kwota do dyspozycji w ramach naboru – 1 000 000,00 zł")
    fragment = _n("kwota do dyspozycji w ramach naboru – 1 000 000,00 zł")
    d = wyciagnij_dane(fragment, kontekst, 2026)
    assert (d.numer, d.wojewodztwa, d.data_startu, d.godzina_startu) == ("V", ["lubelskie"], date(2027, 3, 3), time(8, 30))


# ------------------------------------------------------------------ klasyfikacja

def _zmiana(nowe, stare=(), kontekst=None):
    nowe = [_n(x) for x in nowe]
    return Zmiana(rodzaj=TEKST, nowe=nowe, stare=[_n(x) for x in stare],
                  kontekst=nowe if kontekst is None else [_n(x) for x in kontekst])


def test_dopisek_nabor_zamkniety_w_starym_naglowku_to_info():
    z = _zmiana(["III NABÓR WNIOSKÓW O POŻYCZKĘ woj. lubelskie, mazowieckie, podlaskie – NABÓR ZAMKNIĘTY"],
                ["III NABÓR WNIOSKÓW O POŻYCZKĘ woj. lubelskie, mazowieckie, podlaskie"])
    assert klasyfikuj(z, TERAZ, WAW, GODZ_8).poziom == INFO


def test_zmiana_terminu_w_ogloszeniu_to_pilne_ze_zmiana_terminu():
    z = _zmiana(["Informujemy, że od dnia 22 stycznia 2027 r. (od godz. 8:30) LFR przyjmować będzie wnioski"],
                ["Informujemy, że od dnia 15 stycznia 2027 r. (od godz. 8:30) LFR przyjmować będzie wnioski"])
    k = klasyfikuj(z, TERAZ, WAW, GODZ_8)
    assert k.poziom == PILNE and k.zmiana_terminu
    assert k.start == w_warszawie(2027, 1, 22, 8, 30)
    assert k.poprzedni_start == w_warszawie(2027, 1, 15, 8, 30)


def test_publikacja_listy_po_dawnym_naborze_to_info():
    """Np. „Lista wniosków … Rozpoczęcie naboru – 29.09.2026” dopisana 09.10.2026."""
    z = _zmiana(["III NABÓR WNIOSKÓW O POŻYCZKĘ woj. lubelskie, mazowieckie, podlaskie",
                 "Lista wniosków złożonych w ramach naboru z dnia 29.09.2026 r.",
                 "Rozpoczęcie naboru – 29.09.2026 godz. 8:30",
                 "Kwota do dyspozycji w ramach naboru – 4 166 250,00 zł"])
    k = klasyfikuj(z, w_warszawie(2026, 10, 9, 12, 0), WAW, GODZ_8)
    assert k.poziom == INFO and "już się odbył" in k.powod


def test_zapowiedz_bez_dokladnej_daty_to_pilne():
    z = _zmiana(["Uprzejmie informujemy, że kolejny nabór wniosków planowany jest na marzec 2027 r."])
    k = klasyfikuj(z, TERAZ, WAW, GODZ_8)
    assert k.poziom == PILNE and k.start is None
    assert k.dane.zapowiedz.startswith("na marzec 2027")


def test_zapowiedz_z_przeszla_data_bez_kotwicy_nadal_pilna_bez_daty_startu():
    z = _zmiana(["W nawiązaniu do naboru z 29.09.2026 r. kolejny nabór planowany jest na styczeń 2027 r."],
                kontekst=["15.12.2025", "Pierwszy Biznes - Wsparcie w Starcie - nabory od 2026",
                          "W nawiązaniu do naboru z 29.09.2026 r. kolejny nabór planowany jest na styczeń 2027 r."])
    k = klasyfikuj(z, TERAZ, WAW, GODZ_8)
    assert k.poziom == PILNE and k.start is None and k.dane.data_startu is None


def test_data_publikacji_z_kontekstu_nie_udaje_daty_startu():
    kontekst = ["15.12.2025", "Pierwszy Biznes - Wsparcie w Starcie - nabory od 2026",
                "Kolejny nabór planowany jest na styczeń 2027 r."]
    d = wyciagnij_dane(_n(kontekst[-1]), "\n".join(kontekst), 2026)
    assert d.data_startu is None


def test_nabor_ktory_wlasnie_trwa_nadal_pilny():
    z = _zmiana(["Informujemy, że od dnia 23 października 2026 r. (od godz. 8:30) LFR przyjmować będzie wnioski"])
    k = klasyfikuj(z, TERAZ + timedelta(hours=1), WAW, GODZ_8)
    assert k.poziom == PILNE


def test_brak_godziny_przyjmuje_godzine_domyslna():
    z = _zmiana(["IV NABÓR WNIOSKÓW woj. lubelskie", "Nabór rozpocznie się 10 lutego 2027 r."])
    k = klasyfikuj(z, TERAZ, WAW, GODZ_8)
    assert k.poziom == PILNE
    assert k.start == w_warszawie(2027, 2, 10, 8, 0) and k.dane.godzina_startu is None
