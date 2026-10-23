"""Kanał Telegram i pobieranie – na atrapach sesji HTTP (bez sieci)."""

from __future__ import annotations

import pytest
import requests

from monitor_lfr.kanaly import (
    BladWysylki, KanalKonsola, KanalNieskonfigurowany, KanalTelegram, kanal_z_srodowiska, przytnij,
)
from monitor_lfr.pobieranie import BladPobierania, pobierz_strone

TOKEN = "123456:SEKRETNY-TOKEN-abc"


class Odp:
    def __init__(self, status=200, json_=None, content=b"", headers=None):
        self.status_code = status
        self._json = json_
        self.content = content
        self.headers = headers or {}
        self.encoding = "utf-8" if "charset" in self.headers.get("content-type", "") else None
        self.apparent_encoding = "utf-8"

    def json(self):
        if self._json is None:
            raise ValueError("brak JSON")
        return self._json


class Sesja:
    def __init__(self, odpowiedzi):
        self.odpowiedzi = list(odpowiedzi)
        self.wywolania = []

    def _nastepna(self, *a, **kw):
        self.wywolania.append((a, kw))
        o = self.odpowiedzi.pop(0)
        if isinstance(o, Exception):
            raise o
        return o

    post = _nastepna
    get = _nastepna


# ------------------------------------------------------------------ Telegram

def test_telegram_wysyla_tekst_bez_formatowania():
    s = Sesja([Odp(200, {"ok": True})])
    KanalTelegram(TOKEN, "42", sesja=s, spij=lambda _: None).wyslij("Cześć")
    (url,), kw = s.wywolania[0]
    assert url == f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    assert kw["json"] == {"chat_id": "42", "text": "Cześć", "disable_web_page_preview": True}
    assert "parse_mode" not in kw["json"]


def test_telegram_blad_nie_ujawnia_tokenu():
    blad_sieci = requests.ConnectionError(f"Max retries exceeded with url: /bot{TOKEN}/sendMessage")
    s = Sesja([blad_sieci, blad_sieci, blad_sieci])
    with pytest.raises(BladWysylki) as e:
        KanalTelegram(TOKEN, "42", sesja=s, spij=lambda _: None).wyslij("x")
    assert TOKEN not in str(e.value) and "***" in str(e.value)
    assert len(s.wywolania) == 3


def test_telegram_zly_token_bez_ponawiania():
    s = Sesja([Odp(401, {"ok": False, "description": "Unauthorized"})])
    with pytest.raises(BladWysylki, match="Unauthorized"):
        KanalTelegram(TOKEN, "42", sesja=s, spij=lambda _: None).wyslij("x")
    assert len(s.wywolania) == 1


def test_telegram_limit_429_czeka_i_ponawia():
    pauzy = []
    s = Sesja([Odp(429, {"ok": False, "parameters": {"retry_after": 3}}), Odp(200, {"ok": True})])
    KanalTelegram(TOKEN, "42", sesja=s, spij=pauzy.append).wyslij("x")
    assert pauzy == [3.0]


def test_przycinanie_dlugiej_wiadomosci():
    assert len(przytnij("a" * 10000)) <= 4000


def test_kanal_bez_sekretow_zglasza_brak_zmiennych():
    k = kanal_z_srodowiska("telegram", {"TELEGRAM_BOT_TOKEN": "", "TELEGRAM_CHAT_ID": "1"})
    assert isinstance(k, KanalNieskonfigurowany)
    with pytest.raises(BladWysylki, match="TELEGRAM_BOT_TOKEN"):
        k.wyslij("x")
    assert isinstance(kanal_z_srodowiska("telegram", {"TELEGRAM_BOT_TOKEN": "a", "TELEGRAM_CHAT_ID": "1"}),
                      KanalTelegram)
    assert isinstance(kanal_z_srodowiska("konsola", {}), KanalKonsola)


# ------------------------------------------------------------------ pobieranie

def test_pobieranie_ponawia_z_backoffem_i_konczy_sukcesem():
    pauzy = []
    s = Sesja([requests.Timeout("timeout"), Odp(503), Odp(200, content="Zażółć".encode(),
                                                          headers={"content-type": "text/html; charset=UTF-8"})])
    odp = pobierz_strone("https://x", user_agent="UA", backoff_s=5, ponowienia=3, sesja=s, spij=pauzy.append)
    assert odp.status_http == 200 and odp.html == "Zażółć" and odp.proby == 3
    assert pauzy == [5, 10]
    _, kw = s.wywolania[0]
    assert kw["headers"]["User-Agent"] == "UA" and kw["timeout"]


def test_pobieranie_po_3_ponowieniach_rzuca_blad_ze_statusem():
    pauzy = []
    s = Sesja([Odp(500)] * 4)
    with pytest.raises(BladPobierania) as e:
        pobierz_strone("https://x", user_agent="UA", backoff_s=2, ponowienia=3, sesja=s, spij=pauzy.append)
    assert e.value.status_http == 500 and e.value.proby == 4
    assert pauzy == [2, 4, 8]
