"""Wiersz poleceń: --dry-run, --plik, --test-alert (bez sieci i bez Telegrama)."""

from __future__ import annotations

import json

from conftest import BLOK_IV, PLIK_STRONY, dopisz_na_gorze
from monitor_lfr.cli import main
from monitor_lfr.wiadomosci import TYTUL_PILNY


def _konfig(tmp_path):
    p = tmp_path / "config.json"
    p.write_text(json.dumps({"heartbeat": {"wlaczony": False}}), encoding="utf-8")
    return str(p)


def test_dry_run_z_pliku_zapisuje_baze_a_potem_drukuje_alert(tmp_path, capsys, monkeypatch):
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    stan = tmp_path / "state"
    kod = main(["--dry-run", "--plik", str(PLIK_STRONY), "--stan-dir", str(stan), "--config", _konfig(tmp_path)])
    wyjscie = capsys.readouterr().out
    assert kod == 0
    assert "wynik: baza" in wyjscie and "[DRY-RUN]" not in wyjscie
    assert json.loads((stan / "stan.json").read_text(encoding="utf-8"))["strona"]["hash"]
    assert len((stan / "log.jsonl").read_text(encoding="utf-8").splitlines()) == 1

    zmieniona = tmp_path / "zmieniona.html"
    zmieniona.write_text(dopisz_na_gorze(PLIK_STRONY.read_text(encoding="utf-8"), BLOK_IV), encoding="utf-8")
    kod = main(["--dry-run", "--plik", str(zmieniona), "--stan-dir", str(stan), "--config", _konfig(tmp_path)])
    wyjscie = capsys.readouterr().out
    assert kod == 0
    assert "[DRY-RUN]" in wyjscie and TYTUL_PILNY in wyjscie and "wynik: zmiana" in wyjscie


def test_test_alert_w_trybie_dry_run_nie_rusza_stanu(tmp_path, capsys):
    stan = tmp_path / "state"
    kod = main(["--test-alert", "--dry-run", "--stan-dir", str(stan), "--config", _konfig(tmp_path)])
    wyjscie = capsys.readouterr().out
    assert kod == 0
    assert "TO JEST WIADOMOŚĆ TESTOWA" in wyjscie and TYTUL_PILNY in wyjscie
    assert "DOTYCZY TWOICH WOJEWÓDZTW" in wyjscie and "2 000 000,00 zł" in wyjscie
    assert not stan.exists()


def test_brak_sekretow_konczy_sie_kodem_1_ale_stan_jest_zapisany(tmp_path, monkeypatch):
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)
    stan = tmp_path / "state"
    kod = main(["--plik", str(PLIK_STRONY), "--stan-dir", str(stan), "--config", _konfig(tmp_path)])
    assert kod == 1
    assert (stan / "stan.json").exists()


def test_test_alert_bez_sekretow_zwraca_blad(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    assert main(["--test-alert", "--config", _konfig(tmp_path)]) == 1
    assert "TELEGRAM_BOT_TOKEN" in capsys.readouterr().err


def test_brak_pliku_wejsciowego(tmp_path):
    assert main(["--dry-run", "--plik", str(tmp_path / "nie-ma.html"), "--stan-dir", str(tmp_path)]) == 2
