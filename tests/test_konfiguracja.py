"""Konfiguracja: województwa sprowadzane do postaci kanonicznej (poprawka po recenzji 23.10.2026).

Wada: nazwy z config.json szły do porównania bez zmian, więc „Mazowieckie” albo „mazowieckim”
dawały „NIE dotyczy Twoich województw” i zero przypomnień – wbrew README.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta

import pytest

from conftest import T0, Srodowisko, w_warszawie
from monitor_lfr.cli import main
from monitor_lfr.konfiguracja import BladKonfiguracji, z_slownika


@pytest.mark.parametrize("wpis, oczekiwane", [
    (["mazowieckie", "lubelskie"], ["mazowieckie", "lubelskie"]),
    (["Mazowieckie", "Lubelskie"], ["mazowieckie", "lubelskie"]),
    (["mazowieckim", "woj. lubelskie"], ["mazowieckie", "lubelskie"]),
    (["MAZOWIECKIE", "mazowieckie", "Mazowsze"], ["mazowieckie"]),  # bez powtórzeń
    (["Warmińsko–Mazurskie"], ["warmińsko-mazurskie"]),  # pauza zamiast dywizu
])
def test_wojewodztwa_z_konfiguracji_w_postaci_kanonicznej(wpis, oczekiwane):
    assert z_slownika({"moje_wojewodztwa": wpis}).moje_wojewodztwa == oczekiwane


@pytest.mark.parametrize("wpis", [
    ["Mazury"],  # nie województwo
    ["mazowieckie", "xyz"],
    ["mazowieckie, lubelskie"],  # dwa w jednej pozycji
    [7],
    [],
    "mazowieckie",  # napis zamiast listy (inaczej byłby rozbity na litery)
])
def test_nierozpoznane_wojewodztwo_to_blad_konfiguracji(wpis):
    with pytest.raises(BladKonfiguracji, match="moje_wojewodztwa"):
        z_slownika({"moje_wojewodztwa": wpis})


def test_wielkie_litery_w_konfiguracji_daja_dotyczy_i_trzy_przypomnienia(tmp_path, html_dzis, html_z_iv):
    """Scenariusz z recenzji: [„Mazowieckie”, „Lubelskie”] + IV nabór dla lubelskiego i mazowieckiego."""
    sr = Srodowisko(tmp_path / "state", moje_wojewodztwa=["Mazowieckie", "Lubelskie"])
    sr.uruchom(html_dzis, T0)
    sr.uruchom(html_z_iv, T0 + timedelta(minutes=10))
    assert len(sr.nowe) == 1
    msg = sr.nowe[0]
    assert ">>> DOTYCZY TWOICH WOJEWÓDZTW: lubelskie, mazowieckie <<<" in msg
    assert "NIE dotyczy" not in msg
    przyp = [p for p in sr.stan()["przypomnienia"] if p["status"] == "oczekuje"]
    assert sorted(datetime.fromisoformat(p["termin"]) for p in przyp) == [
        w_warszawie(2027, 1, 12, 8, 30), w_warszawie(2027, 1, 14, 8, 30), w_warszawie(2027, 1, 15, 7, 30),
    ]


def test_cli_odrzuca_nierozpoznane_wojewodztwo(tmp_path, capsys):
    p = tmp_path / "config.json"
    p.write_text(json.dumps({"moje_wojewodztwa": ["Mazury"]}), encoding="utf-8")
    kod = main(["--dry-run", "--test-alert", "--config", str(p)])
    assert kod == 2
    assert "nie rozpoznano województwa 'Mazury'" in capsys.readouterr().err
