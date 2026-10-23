"""Scenariusze end-to-end (bez sieci i bez Telegrama) – wymagania (b)–(i)."""

from __future__ import annotations

from datetime import datetime, timedelta

from conftest import (
    T0, URL, ZNACZNIK_DOKUMENTOW, Srodowisko, dopisz_na_gorze, w_warszawie,
)
from monitor_lfr.wiadomosci import TYTUL_AWARIA, TYTUL_HEARTBEAT, TYTUL_INFO, TYTUL_PILNY, TYTUL_POWROT


def _pilne(wiadomosci):
    return [w for w in wiadomosci if TYTUL_PILNY in w]


# ------------------------------------------------------------------ (b) nowy nabór -> PILNE

def test_b_nowy_nabor_daje_alert_pilny_z_danymi_i_przypomnieniami(po_bazie: Srodowisko, html_z_iv: str):
    wynik = po_bazie.uruchom(html_z_iv, T0 + timedelta(minutes=10))

    assert wynik.zmiana and wynik.kod_wyjscia == 0
    assert len(po_bazie.nowe) == 1, po_bazie.nowe
    msg = po_bazie.nowe[0]
    assert msg.startswith(TYTUL_PILNY)
    assert ">>> DOTYCZY TWOICH WOJEWÓDZTW: lubelskie, mazowieckie <<<" in msg
    assert "NIE dotyczy" not in msg
    assert "Województwa: lubelskie, mazowieckie" in msg
    assert "Nabór: IV" in msg
    assert "15.01.2027, godz. 8:30" in msg
    assert "Pula: 2 000 000,00 zł" in msg
    assert "przyjmować będzie wnioski" in msg  # fragment ogłoszenia
    assert f"Link: {URL}" in msg
    # checklista
    for fraza in ["komplet dokumentów gotowy WCZEŚNIEJ", "kwalifikowany podpis elektroniczny",
                  "profil zaufany NIE wystarcza", "dokumenty poręczyciela", "weksel in blanco",
                  "liczy się godzina wpływu maila na serwer LFR, nie godzina wysłania"]:
        assert fraza in msg, fraza

    przyp = [p for p in po_bazie.stan()["przypomnienia"] if p["status"] == "oczekuje"]
    assert sorted(datetime.fromisoformat(p["termin"]) for p in przyp) == [
        w_warszawie(2027, 1, 12, 8, 30),
        w_warszawie(2027, 1, 14, 8, 30),
        w_warszawie(2027, 1, 15, 7, 30),
    ]
    assert {p["etykieta"] for p in przyp} == {"3 dni", "1 dzień", "1 godzinę"}
    assert all(datetime.fromisoformat(p["start"]) == w_warszawie(2027, 1, 15, 8, 30) for p in przyp)


def test_b_nabor_innego_wojewodztwa_wyraznie_oznaczony_bez_przypomnien(po_bazie: Srodowisko, html_dzis: str):
    blok = ("<p>V NABÓR WNIOSKÓW O POŻYCZKĘ woj. małopolskie i podkarpackie</p>"
            "<p>Informujemy, że od dnia 2 lutego 2027 r. (od godz. 8.00) Lubelska Fundacja Rozwoju "
            "przyjmować będzie wnioski.</p><p>……………</p>")
    po_bazie.uruchom(dopisz_na_gorze(html_dzis, blok), T0 + timedelta(minutes=10))
    assert len(po_bazie.nowe) == 1
    msg = po_bazie.nowe[0]
    assert ">>> NIE dotyczy Twoich województw" in msg
    assert "DOTYCZY TWOICH" not in msg
    assert "02.02.2027, godz. 8:00" in msg
    assert "Przypomnienia: nie zaplanowano" in msg
    assert po_bazie.stan()["przypomnienia"] == []


def test_b_zapowiedz_naboru_na_gorze_strony_to_pilne_bez_daty(po_bazie: Srodowisko, html_dzis: str):
    """Zapowiedź bez dokładnej daty – nie może „pożyczyć” daty publikacji strony (15.12.2025)."""
    blok = ("<p>Uprzejmie informujemy, że kolejny nabór wniosków o pożyczkę w ramach Instrumentu "
            "Finansowego Pierwszy Biznes – Wsparcie w Starcie planowany jest na styczeń 2027 r.</p><p>……………</p>")
    po_bazie.uruchom(dopisz_na_gorze(html_dzis, blok), T0 + timedelta(minutes=10))
    assert len(po_bazie.nowe) == 1
    msg = po_bazie.nowe[0]
    assert msg.startswith(TYTUL_PILNY)
    assert "Start: nie odczytano daty" in msg
    assert "Planowany termin: na styczeń 2027 r" in msg
    assert "Przypomnienia: brak – nie odczytano daty startu" in msg


# ------------------------------------------------------------------ (c) obecna strona -> brak alertów

def test_c_pierwsze_uruchomienie_to_baza_a_obecna_strona_nie_daje_alertu(srodowisko: Srodowisko, html_dzis: str):
    w1 = srodowisko.uruchom(html_dzis, T0)
    assert w1.wynik == "baza" and srodowisko.nowe == []
    for i in range(1, 4):
        w = srodowisko.uruchom(html_dzis, T0 + timedelta(minutes=10 * i))
        assert w.wynik == "ok" and not w.zmiana
        assert srodowisko.nowe == []
    assert srodowisko.kanal.wiadomosci == []


# ------------------------------------------------------------------ (d) bez duplikatów

def test_d_dwa_kolejne_uruchomienia_nie_wysylaja_duplikatu(po_bazie: Srodowisko, html_z_iv: str):
    po_bazie.uruchom(html_z_iv, T0 + timedelta(minutes=10))
    assert len(_pilne(po_bazie.nowe)) == 1
    po_bazie.uruchom(html_z_iv, T0 + timedelta(minutes=20))
    assert po_bazie.nowe == []
    po_bazie.uruchom(html_z_iv, T0 + timedelta(minutes=30))
    assert po_bazie.nowe == []


def test_d_migajaca_strona_nie_powtarza_alertu_pilnego(po_bazie: Srodowisko, html_dzis: str, html_z_iv: str):
    """Strona raz z ogłoszeniem, raz bez (np. cache) – PILNE wychodzi tylko raz."""
    po_bazie.uruchom(html_z_iv, T0 + timedelta(minutes=10))
    po_bazie.uruchom(html_dzis, T0 + timedelta(minutes=20))
    po_bazie.uruchom(html_z_iv, T0 + timedelta(minutes=30))
    po_bazie.uruchom(html_dzis, T0 + timedelta(minutes=40))
    assert len(_pilne(po_bazie.kanal.wiadomosci)) == 1


def test_d_nieudana_wysylka_jest_ponawiana_i_dochodzi_raz(po_bazie: Srodowisko, html_z_iv: str):
    po_bazie.kanal.awaria = True
    hash_bazy = po_bazie.stan()["strona"]["hash"]
    w = po_bazie.uruchom(html_z_iv, T0 + timedelta(minutes=10))
    assert w.kod_wyjscia == 1 and po_bazie.nowe == []
    assert po_bazie.stan()["strona"]["hash"] == hash_bazy  # baza NIE przesunięta
    po_bazie.kanal.awaria = False
    po_bazie.uruchom(html_z_iv, T0 + timedelta(minutes=20))
    assert len(_pilne(po_bazie.nowe)) == 1
    po_bazie.uruchom(html_z_iv, T0 + timedelta(minutes=30))
    assert po_bazie.nowe == []


# ------------------------------------------------------------------ (e) awaria i powrót

def test_e_zmiana_html_po_3_probach_alert_awarii_potem_znowu_dziala(po_bazie: Srodowisko, html_dzis: str):
    zepsuty = html_dzis.replace("institution management entry", "nowy-uklad-strony")
    assert zepsuty != html_dzis
    t = T0
    for _ in range(2):
        t += timedelta(minutes=10)
        w = po_bazie.uruchom(zepsuty, t)
        assert w.wynik == "blad" and po_bazie.nowe == []
    t += timedelta(minutes=10)
    po_bazie.uruchom(zepsuty, t)
    assert len(po_bazie.nowe) == 1 and po_bazie.nowe[0].startswith(TYTUL_AWARIA)
    assert "Kolejne nieudane próby: 3" in po_bazie.nowe[0]
    assert URL in po_bazie.nowe[0]
    # dalsza awaria – bez ponownego alertu i bez zmiany stanu (brak zbędnych commitów)
    przed = po_bazie.surowy_stan()
    t += timedelta(minutes=10)
    po_bazie.uruchom(zepsuty, t)
    assert po_bazie.nowe == []
    assert po_bazie.surowy_stan() == przed
    # powrót
    t += timedelta(minutes=10)
    w = po_bazie.uruchom(html_dzis, t)
    assert w.wynik == "ok"
    assert len(po_bazie.nowe) == 1 and po_bazie.nowe[0].startswith(TYTUL_POWROT)
    assert po_bazie.stan()["bledy"]["kolejne"] == 0
    t += timedelta(minutes=10)
    po_bazie.uruchom(html_dzis, t)
    assert po_bazie.nowe == []


def test_e_brak_odpowiedzi_serwera_tez_liczy_sie_jako_awaria(po_bazie: Srodowisko, html_dzis: str):
    for i in range(1, 4):
        po_bazie.uruchom(None, T0 + timedelta(minutes=10 * i))
    assert len(po_bazie.kanal.wiadomosci) == 1
    assert "ConnectTimeout" in po_bazie.kanal.wiadomosci[0]
    po_bazie.uruchom(html_dzis, T0 + timedelta(minutes=40))
    assert po_bazie.nowe[0].startswith(TYTUL_POWROT)


def test_e_pojedynczy_blad_nie_daje_alertu(po_bazie: Srodowisko, html_dzis: str):
    po_bazie.uruchom(None, T0 + timedelta(minutes=10))
    po_bazie.uruchom(None, T0 + timedelta(minutes=20))
    po_bazie.uruchom(html_dzis, T0 + timedelta(minutes=30))
    po_bazie.uruchom(None, T0 + timedelta(minutes=40))
    assert po_bazie.kanal.wiadomosci == []


# ------------------------------------------------------------------ (f) nowy plik -> INFO

def test_f_nowy_plik_w_dokumentach_daje_info(po_bazie: Srodowisko, html_dzis: str):
    nowy = ('<div class="p-files"><span class="ico-file"></span>'
            '<a href="https://www.lfr.lublin.pl/wp-content/uploads/2027/01/Lista-wnioskow-IV-nabor.pdf" '
            'target="_blank">Lista wniosków &#8211; IV nabór</a></div>')
    assert html_dzis.count(ZNACZNIK_DOKUMENTOW) == 1
    html = html_dzis.replace(ZNACZNIK_DOKUMENTOW, ZNACZNIK_DOKUMENTOW + nowy, 1)
    po_bazie.uruchom(html, T0 + timedelta(minutes=10))
    assert len(po_bazie.nowe) == 1
    msg = po_bazie.nowe[0]
    assert msg.startswith(TYTUL_INFO)
    assert "Nowy plik w „Dokumenty do pobrania”: Lista wniosków - IV nabór" in msg
    assert "Lista-wnioskow-IV-nabor.pdf" in msg
    assert not _pilne(po_bazie.nowe)
    po_bazie.uruchom(html, T0 + timedelta(minutes=20))
    assert po_bazie.nowe == []


def test_f_zmiana_tresci_bez_wzorcow_daje_info(po_bazie: Srodowisko, html_dzis: str):
    html = dopisz_na_gorze(html_dzis, "<p>KOMUNIKAT: biuro w Lublinie nieczynne 2 listopada.</p>")
    po_bazie.uruchom(html, T0 + timedelta(minutes=10))
    assert len(po_bazie.nowe) == 1 and po_bazie.nowe[0].startswith(TYTUL_INFO)
    assert "biuro w Lublinie nieczynne" in po_bazie.nowe[0]


# ------------------------------------------------------------------ (g) heartbeat

def test_g_heartbeat_raz_na_dobe_po_9_czasu_warszawskiego(tmp_path, html_dzis: str):
    s = Srodowisko(tmp_path / "state", heartbeat={"wlaczony": True, "godzina": 9})
    s.uruchom(html_dzis, w_warszawie(2026, 10, 23, 8, 50))
    assert s.nowe == []
    s.uruchom(html_dzis, w_warszawie(2026, 10, 23, 9, 2))
    assert len(s.nowe) == 1 and s.nowe[0].startswith(TYTUL_HEARTBEAT)
    assert "Ostatnie sprawdzenie: 23.10.2026 9:02" in s.nowe[0]
    s.uruchom(html_dzis, w_warszawie(2026, 10, 23, 9, 12))
    s.uruchom(html_dzis, w_warszawie(2026, 10, 23, 23, 55))
    assert s.nowe == []
    s.uruchom(html_dzis, w_warszawie(2026, 10, 24, 8, 59))
    assert s.nowe == []
    s.uruchom(html_dzis, w_warszawie(2026, 10, 24, 10, 41))  # cron spóźniony – i tak wychodzi
    assert len(s.nowe) == 1 and s.nowe[0].startswith(TYTUL_HEARTBEAT)
    heartbeaty = [w for w in s.kanal.wiadomosci if w.startswith(TYTUL_HEARTBEAT)]
    assert len(heartbeaty) == 2


def test_g_heartbeat_wylaczony_w_konfiguracji(tmp_path, html_dzis: str):
    s = Srodowisko(tmp_path / "state", heartbeat={"wlaczony": False})
    s.uruchom(html_dzis, w_warszawie(2026, 10, 23, 9, 30))
    s.uruchom(html_dzis, w_warszawie(2026, 10, 24, 9, 30))
    assert s.kanal.wiadomosci == []


# ------------------------------------------------------------------ (h) przypomnienia

def test_h_spoznione_przypomnienie_wychodzi_raz_z_informacja_ile_zostalo(po_bazie: Srodowisko, html_z_iv: str):
    po_bazie.uruchom(html_z_iv, T0 + timedelta(minutes=10))
    assert len(_pilne(po_bazie.nowe)) == 1

    # przypomnienie „3 dni” zaplanowane na 12.01 8:30 – cron spóźniony o 30 min
    po_bazie.uruchom(html_z_iv, w_warszawie(2027, 1, 12, 9, 0))
    assert len(po_bazie.nowe) == 1
    msg = po_bazie.nowe[0]
    assert msg.startswith("[PRZYPOMNIENIE]")
    assert "Zostało: 2 dni 23 godz. 30 min" in msg
    assert "opóźnieniem 30 min" in msg
    po_bazie.uruchom(html_z_iv, w_warszawie(2027, 1, 12, 9, 10))
    assert po_bazie.nowe == []

    # przerwa w działaniu: „1 dzień” i „1 godzinę” zaległe naraz -> jedna wiadomość
    po_bazie.uruchom(html_z_iv, w_warszawie(2027, 1, 15, 8, 5))
    assert len(po_bazie.nowe) == 1
    assert "Zostało: 25 min" in po_bazie.nowe[0]
    po_bazie.uruchom(html_z_iv, w_warszawie(2027, 1, 15, 8, 15))
    assert po_bazie.nowe == []

    statusy = {p["etykieta"]: p["status"] for p in po_bazie.stan()["przypomnienia"]}
    assert statusy == {"3 dni": "wyslane", "1 dzień": "pominiete", "1 godzinę": "wyslane"}


def test_h_przypomnienie_po_starcie_mowi_ze_nabor_trwa_a_pozniej_przepada(po_bazie: Srodowisko, html_z_iv: str):
    po_bazie.uruchom(html_z_iv, T0 + timedelta(minutes=10))
    po_bazie.uruchom(html_z_iv, w_warszawie(2027, 1, 12, 8, 31))
    po_bazie.uruchom(html_z_iv, w_warszawie(2027, 1, 14, 8, 31))
    # cron „zgubił” 7:30 – pierwszy przebieg już po starcie
    po_bazie.uruchom(html_z_iv, w_warszawie(2027, 1, 15, 8, 41))
    assert len(po_bazie.nowe) == 1
    assert "NABÓR JUŻ TRWA" in po_bazie.nowe[0] and "11 min temu" in po_bazie.nowe[0]
    po_bazie.uruchom(html_z_iv, w_warszawie(2027, 1, 15, 8, 51))
    assert po_bazie.nowe == []


def test_h_czas_do_startu_liczony_poprawnie_przez_zmiane_czasu(tmp_path, html_dzis: str):
    """Start 26.10.2026 (już czas zimowy), przypomnienie 23.10 (jeszcze letni) – realne 3 dni i 1 godz. mniej 10 min."""
    s = Srodowisko(tmp_path / "state")
    s.uruchom(html_dzis, w_warszawie(2026, 10, 22, 12, 0))
    blok = ("<p>IV NABÓR WNIOSKÓW O POŻYCZKĘ woj. mazowieckie</p><p>Informujemy, że od dnia 26 października "
            "2026 r. (od godz. 8:30) Lubelska Fundacja Rozwoju przyjmować będzie wnioski.</p><p>……</p>")
    html = dopisz_na_gorze(html_dzis, blok)
    s.uruchom(html, w_warszawie(2026, 10, 22, 12, 10))
    assert len(_pilne(s.nowe)) == 1
    s.uruchom(html, w_warszawie(2026, 10, 23, 8, 40))  # przypomnienie „3 dni” (23.10 8:30 CEST)
    assert len(s.nowe) == 1
    assert "Zostało: 3 dni 50 min" in s.nowe[0]  # 23.10 6:40 UTC -> 26.10 7:30 UTC


def test_h_przypomnienie_dlugo_po_starcie_nie_jest_wysylane(po_bazie: Srodowisko, html_z_iv: str):
    po_bazie.uruchom(html_z_iv, T0 + timedelta(minutes=10))
    po_bazie.uruchom(html_z_iv, w_warszawie(2027, 1, 16, 12, 0))
    assert po_bazie.nowe == []
    assert {p["status"] for p in po_bazie.stan()["przypomnienia"]} == {"przeterminowane"}


# ------------------------------------------------------------------ (i) normalizacja

def test_i_zmiana_bialych_znakow_i_myslnikow_nie_daje_alertu(po_bazie: Srodowisko, html_dzis: str):
    html = (html_dzis
            .replace("–", "—")                      # półpauza -> pauza
            .replace("&#8211;", "&#8212;")
            .replace("Lubelska Fundacja Rozwoju", "Lubelska&nbsp;Fundacja \n   Rozwoju")
            .replace(". ", ".  ")                    # podwójne spacje
            .replace("„", "&quot;").replace("”", "&quot;")
            .replace("pożyczkę", "po­życzkę")   # miękki dywiz
            .replace("Informujemy", "​Informujemy"))
    assert html != html_dzis
    w = po_bazie.uruchom(html, T0 + timedelta(minutes=10))
    assert w.wynik == "ok" and not w.zmiana
    assert po_bazie.nowe == []


def test_i_inny_podzial_na_akapity_nie_daje_alertu(po_bazie: Srodowisko, html_dzis: str):
    html = html_dzis.replace("Dziękujemy za cierpliwość i wyrozumiałość.",
                             "Dziękujemy za cierpliwość<br>i wyrozumiałość.")
    assert html != html_dzis
    po_bazie.uruchom(html, T0 + timedelta(minutes=10))
    assert po_bazie.nowe == []


# ------------------------------------------------------------------ stan i log

def test_stan_nie_zmienia_sie_bez_zdarzen_w_tej_samej_dobie(po_bazie: Srodowisko, html_dzis: str):
    przed = po_bazie.surowy_stan()
    po_bazie.uruchom(html_dzis, T0 + timedelta(minutes=10))
    po_bazie.uruchom(html_dzis, T0 + timedelta(minutes=20))
    assert po_bazie.surowy_stan() == przed  # brak commitu w Actions
    po_bazie.uruchom(html_dzis, T0 + timedelta(days=1))
    assert po_bazie.stan()["znacznik_zycia"] == "2026-10-24"  # dzienny znacznik „żyję”


def test_log_jsonl_ograniczony_do_maks_wpisow(tmp_path, html_dzis: str):
    import json

    s = Srodowisko(tmp_path / "state", log={"max_wpisow": 10})
    for i in range(15):
        s.uruchom(html_dzis, T0 + timedelta(minutes=10 * i))
    linie = (tmp_path / "state" / "log.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(linie) == 10
    wpis = json.loads(linie[-1])
    assert wpis["status_http"] == 200 and wpis["zmiana"] is False and wpis["wynik"] == "ok"
    assert {"czas", "czas_lokalny", "proby", "wyslane", "blad"} <= wpis.keys()


# ------------------------------------------------------------------ poprawki po recenzji 23.10.2026

def test_zapowiedz_obok_wzmianki_o_minionym_naborze_to_pilne(po_bazie: Srodowisko, html_dzis: str):
    """Wada 2: przeszła data „w dniu 29.09.2026” nie może zamienić zapowiedzi w INFO."""
    blok = ("<p>KOMUNIKAT: W związku z zakończeniem naboru przeprowadzonego w dniu 29.09.2026 r. informujemy, "
            "że kolejny nabór wniosków dla woj. lubelskiego i mazowieckiego planowany jest na styczeń 2027 r.</p>"
            "<p>……………</p>")
    po_bazie.uruchom(dopisz_na_gorze(html_dzis, blok), T0 + timedelta(minutes=10))
    assert len(_pilne(po_bazie.nowe)) == 1, po_bazie.nowe
    msg = po_bazie.nowe[0]
    assert ">>> DOTYCZY TWOICH WOJEWÓDZTW: lubelskie, mazowieckie <<<" in msg
    assert "Planowany termin: na styczeń 2027 r" in msg
    assert "już się odbył" not in msg


def test_grudniowe_ogloszenie_bez_roku_daje_pilne_i_przypomnienia(srodowisko: Srodowisko, html_dzis: str):
    """Wada 4: „od dnia 15 stycznia” opublikowane 10.12.2026 to 15.01.2027, nie 15.01.2026."""
    grudzien = w_warszawie(2026, 12, 10, 8, 0)
    srodowisko.uruchom(html_dzis, grudzien)
    blok = ("<p><strong>IV NABÓR WNIOSKÓW O POŻYCZKĘ woj. lubelskie, mazowieckie</strong></p>"
            "<p>Informujemy, że od dnia 15 stycznia (od godz. 8:30) Lubelska Fundacja Rozwoju przyjmować "
            "będzie wnioski o niskooprocentowaną pożyczkę.</p><p>……………</p>")
    srodowisko.uruchom(dopisz_na_gorze(html_dzis, blok), grudzien + timedelta(minutes=10))
    assert len(_pilne(srodowisko.nowe)) == 1, srodowisko.nowe
    assert "15.01.2027, godz. 8:30" in srodowisko.nowe[0]
    przyp = [p for p in srodowisko.stan()["przypomnienia"] if p["status"] == "oczekuje"]
    assert len(przyp) == 3


def test_zmiana_planowanego_terminu_w_miejscu_to_pilne_raz(srodowisko: Srodowisko, html_dzis: str):
    """Wada 5: „planowany jest na marzec” -> „na kwiecień” w tej samej linii to PILNE (i tylko raz)."""
    zapowiedz = ("<p>Uprzejmie informujemy, że kolejny nabór wniosków o pożyczkę w ramach Instrumentu "
                 "Finansowego Pierwszy Biznes – Wsparcie w Starcie planowany jest na marzec 2027 r.</p><p>……………</p>")
    srodowisko.uruchom(dopisz_na_gorze(html_dzis, zapowiedz), T0)
    assert srodowisko.nowe == []  # wersja bazowa
    zmieniona = dopisz_na_gorze(html_dzis, zapowiedz.replace("na marzec 2027", "na kwiecień 2027"))
    srodowisko.uruchom(zmieniona, T0 + timedelta(minutes=10))
    assert len(srodowisko.nowe) == 1, srodowisko.nowe
    msg = srodowisko.nowe[0]
    assert msg.startswith(TYTUL_PILNY)
    assert "UWAGA: ZMIANA PLANOWANEGO TERMINU (poprzednio: na marzec 2027 r" in msg
    assert "Planowany termin: na kwiecień 2027 r" in msg
    srodowisko.uruchom(zmieniona, T0 + timedelta(minutes=20))
    assert srodowisko.nowe == []  # bez duplikatu
