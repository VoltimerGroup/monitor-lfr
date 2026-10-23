"""Jeden przebieg monitora: pobierz -> wyciągnij -> porównaj -> powiadom -> zapisz stan.

Zasady niezawodności:
* Pierwszy udany odczyt = wersja bazowa (bez alertu).
* Alert wysyłamy tylko raz (deduplikacja po skrócie fragmentu, pamiętana w stanie).
* Jeśli wysyłka się nie uda, NIE przesuwamy wersji bazowej – następny przebieg
  wykryje tę samą zmianę i ponowi tylko to, co nie doszło.
* 3 kolejne nieudane odczyty -> alert awarii; pierwszy udany odczyt -> „znowu działa”.
"""

from __future__ import annotations

import sys
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Callable

from . import wiadomosci as W
from .ekstrakcja import BladEkstrakcji, Tresc, tytul_artykulu, wyciagnij_tresc
from .kanaly import BladWysylki, Kanal
from .klasyfikacja import PILNE, Klasyfikacja, klasyfikuj
from .konfiguracja import Konfiguracja
from .normalizacja import WERSJA_NORMALIZACJI, czy_separator, klucz
from .pobieranie import BladPobierania, Odpowiedz
from .porownanie import TEKST, Zmiana, porownaj
from .stan import MagazynStanu

# Przypomnienie spóźnione o więcej niż tyle PO STARCIE naboru już nie ma sensu.
PRZYPOMNIENIE_WAZNE_PO_STARCIE = timedelta(hours=2)
# Zakończone przypomnienia starsze niż tyle usuwamy ze stanu.
PRZECHOWUJ_PRZYPOMNIENIA = timedelta(days=30)


def teraz_utc() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class WynikPrzebiegu:
    kod_wyjscia: int
    wynik: str  # baza / ok / zmiana / blad
    status_http: int | None
    zmiana: bool
    wyslane: int
    bledy_wysylki: list[str] = field(default_factory=list)
    blad: str | None = None


class Monitor:
    def __init__(
        self,
        konfig: Konfiguracja,
        kanal: Kanal,
        magazyn: MagazynStanu,
        *,
        zrodlo: Callable[[], Odpowiedz],
        zegar: Callable[[], datetime] = teraz_utc,
        wypisz: Callable[[str], None] = print,
    ):
        self.k = konfig
        self.kanal = kanal
        self.magazyn = magazyn
        self.zrodlo = zrodlo
        self.zegar = zegar
        self.wypisz = wypisz
        self._wyslane = 0
        self._bledy_wysylki: list[str] = []

    # ------------------------------------------------------------ wysyłka

    def _wyslij(self, tekst: str) -> bool:
        try:
            self.kanal.wyslij(tekst)
        except BladWysylki as e:
            self._bledy_wysylki.append(str(e))
            print(f"BŁĄD WYSYŁKI POWIADOMIENIA: {e}", file=sys.stderr)
            return False
        self._wyslane += 1
        return True

    # ------------------------------------------------------------ przebieg

    def przebieg(self) -> WynikPrzebiegu:
        # Zawsze UTC: odejmowanie dat z tą samą strefą Pythona liczy „po zegarze ściennym”,
        # co przy zmianie czasu (CET/CEST) dawałoby błąd o godzinę.
        teraz = self.zegar().astimezone(timezone.utc)
        self._wyslane, self._bledy_wysylki = 0, []
        stan = self.magazyn.wczytaj()

        status_http: int | None = None
        proby = 0
        blad: str | None = None
        tresc: Tresc | None = None
        try:
            odp = self.zrodlo()
            status_http, proby = odp.status_http, odp.proby
            tresc = wyciagnij_tresc(
                odp.html, self.k.selektory_tresci, self.k.selektor_dokumentow,
                self.k.oczekiwane_frazy, self.k.min_linii, self.k.url,
            )
        except BladPobierania as e:
            status_http, proby, blad = e.status_http, e.proby, str(e)
        except BladEkstrakcji as e:
            blad = f"Nie da się wyciągnąć treści: {e}"

        zmiana = False
        if tresc is None:
            wynik = "blad"
            self._obsluz_blad(stan, blad or "nieznany błąd", teraz)
        else:
            self._obsluz_powrot(stan, teraz)
            wynik, zmiana = self._porownaj_i_powiadom(stan, tresc, teraz)

        self._przypomnienia(stan, teraz)
        self._heartbeat(stan, teraz, status_http, wynik, zmiana)
        stan["znacznik_zycia"] = teraz.astimezone(timezone.utc).date().isoformat()
        self.magazyn.zapisz(stan)

        lokalnie = teraz.astimezone(self.k.strefa)
        wpis = {
            "czas": teraz.astimezone(timezone.utc).isoformat(timespec="seconds"),
            "czas_lokalny": f"{lokalnie:%Y-%m-%d %H:%M:%S}",
            "status_http": status_http,
            "proby": proby,
            "zmiana": zmiana,
            "wynik": wynik,
            "wyslane": self._wyslane,
            "bledy_wysylki": len(self._bledy_wysylki),
            "blad": blad,
        }
        self.magazyn.dopisz_log(wpis, self.k.log_max_wpisow)
        linia = (f"{wpis['czas_lokalny']} ({self.k.strefa.key}) | HTTP {status_http if status_http else '-'}"
                 f" | zmiana: {'TAK' if zmiana else 'nie'} | wynik: {wynik} | wysłano: {self._wyslane}")
        if self._bledy_wysylki:
            linia += f" | BŁĘDY WYSYŁKI: {len(self._bledy_wysylki)}"
        if blad:
            linia += f" | błąd: {blad}"
        self.wypisz(linia)

        return WynikPrzebiegu(
            kod_wyjscia=1 if self._bledy_wysylki else 0, wynik=wynik, status_http=status_http,
            zmiana=zmiana, wyslane=self._wyslane, bledy_wysylki=list(self._bledy_wysylki), blad=blad,
        )

    # ------------------------------------------------------------ awaria / powrót

    def _obsluz_blad(self, stan: dict, blad: str, teraz: datetime) -> None:
        b = stan["bledy"]
        if not b.get("kolejne"):
            b["od"] = teraz.isoformat(timespec="seconds")
            b["pierwszy_blad"] = blad
        # Licznik zatrzymuje się na progu – przy długiej awarii stan nie zmienia się co
        # przebieg (brak zbędnych commitów).
        b["kolejne"] = min(int(b.get("kolejne") or 0) + 1, self.k.prog_awarii)
        if b["kolejne"] >= self.k.prog_awarii and not b.get("alert_wyslany"):
            od = datetime.fromisoformat(b["od"]) if b.get("od") else None
            tekst = W.awaria(kolejne=b["kolejne"], od=od, blad=blad, url=self.k.url, strefa=self.k.strefa)
            if self._wyslij(tekst):
                b["alert_wyslany"] = True

    def _obsluz_powrot(self, stan: dict, teraz: datetime) -> None:
        b = stan["bledy"]
        if b.get("alert_wyslany"):
            od = datetime.fromisoformat(b["od"]) if b.get("od") else None
            if not self._wyslij(W.powrot(od=od, teraz=teraz, strefa=self.k.strefa)):
                return  # spróbujemy w następnym przebiegu
        if b.get("kolejne") or b.get("alert_wyslany"):
            stan["bledy"] = {"kolejne": 0, "od": None, "pierwszy_blad": None, "alert_wyslany": False}

    # ------------------------------------------------------------ porównanie

    def _porownaj_i_powiadom(self, stan: dict, tresc: Tresc, teraz: datetime) -> tuple[str, bool]:
        strona = stan.get("strona")
        if not strona or stan.get("wersja_normalizacji") != WERSJA_NORMALIZACJI:
            self._zapisz_wersje(stan, tresc, teraz)
            stan["wersja_normalizacji"] = WERSJA_NORMALIZACJI
            return "baza", False

        stara = Tresc.z_json(strona["tresc"])
        if tresc.dokumenty is None and stara.dokumenty is not None:
            # Sekcja „Dokumenty” chwilowo niewidoczna – zachowujemy poprzednią listę.
            tresc.dokumenty, tresc.linie_dokumentow = stara.dokumenty, stara.linie_dokumentow

        if tresc.hash_calosci() == strona.get("hash"):
            if tresc.do_json() != strona["tresc"]:
                self._zapisz_wersje(stan, tresc, teraz, od=strona.get("od"))  # inny podział linii
            return "ok", False

        zmiany = porownaj(stara, tresc)
        if not zmiany:
            self._zapisz_wersje(stan, tresc, teraz)
            return "ok", False

        sklasyfikowane = [
            (z, klasyfikuj(z, teraz, self.k.strefa, self.k.godzina_startu_gdy_brak)) for z in zmiany
        ]
        wszystko_wyslane = True
        for z, kl in sklasyfikowane:
            if kl.poziom != PILNE or z.hash in stan["wyslane"]:
                continue
            if not self._wyslij_pilny(stan, z, kl, teraz):
                wszystko_wyslane = False

        info = [(z, kl) for z, kl in sklasyfikowane if kl.poziom != PILNE and z.hash not in stan["wyslane"]]
        if info:
            tekst = W.alert_info(info, url=self.k.url, strefa=self.k.strefa)
            if self._wyslij(tekst):
                for z, _ in info:
                    self._zapamietaj(stan, z, "INFO", teraz)
            else:
                wszystko_wyslane = False

        if wszystko_wyslane:
            self._zapisz_wersje(stan, tresc, teraz)
        return "zmiana", True

    def _zapisz_wersje(self, stan: dict, tresc: Tresc, teraz: datetime, od: str | None = None) -> None:
        stan["strona"] = {
            "hash": tresc.hash_calosci(),
            "od": od or teraz.isoformat(timespec="seconds"),
            "tresc": tresc.do_json(),
        }

    @staticmethod
    def _zapamietaj(stan: dict, z: Zmiana, typ: str, teraz: datetime) -> None:
        plik = z.plik or z.stary_plik
        if z.nowe:
            opis = z.nowe[0]
        elif plik is not None:
            opis = plik.nazwa
        else:
            opis = z.stare[0] if z.stare else ""
        stan["wyslane"][z.hash] = {"czas": teraz.isoformat(timespec="seconds"), "typ": typ, "opis": opis[:120]}

    # ------------------------------------------------------------ PILNE + przypomnienia

    def _plan_przypomnien(self, kl: Klasyfikacja, teraz: datetime) -> tuple[list[dict], str | None]:
        if kl.start is None:
            return [], "brak – nie odczytano daty startu"
        status, _ = W.oznaczenie_wojewodztw(kl.dane.wojewodztwa if kl.dane else [], self.k.moje_wojewodztwa)
        if status == "NIE" and self.k.przypomnienia_tylko_moje:
            return [], "nie zaplanowano – nabór nie dotyczy Twoich województw"
        d = kl.dane
        opis = " · ".join(x for x in [
            f"Nabór: {d.numer}" if d and d.numer else "",
            f"województwa: {', '.join(d.wojewodztwa)}" if d and d.wojewodztwa else "",
            f"pula: {W.opis_kwot(d.kwoty)}" if d and d.kwoty else "",
        ] if x)
        plan = []
        for p in self.k.przypomnienia:
            termin = kl.start - p.wyprzedzenie
            if termin <= teraz:
                continue  # ten termin już minął – właśnie wysyłamy alert PILNY
            plan.append({
                "id": f"{kl.start.isoformat()}|{p.etykieta}",
                "start": kl.start.isoformat(),
                "termin": termin.isoformat(),
                "etykieta": p.etykieta,
                "opis": opis,
                "status": "oczekuje",
                "wyslano": None,
            })
        if not plan:
            return [], "brak – do startu zostało mniej niż najkrótsze wyprzedzenie"
        return plan, None

    def _wyslij_pilny(self, stan: dict, z: Zmiana, kl: Klasyfikacja, teraz: datetime) -> bool:
        plan, powod = self._plan_przypomnien(kl, teraz)
        tekst = W.alert_pilny(
            kl, z, url=self.k.url, moje=self.k.moje_wojewodztwa, strefa=self.k.strefa, teraz=teraz,
            przypomnienia=plan, powod_braku_przypomnien=powod,
        )
        if not self._wyslij(tekst):
            return False
        self._zapamietaj(stan, z, "PILNE", teraz)
        if kl.zmiana_terminu and kl.poprzedni_start is not None:
            for p in stan["przypomnienia"]:
                if p["status"] == "oczekuje" and datetime.fromisoformat(p["start"]) == kl.poprzedni_start:
                    p["status"] = "anulowane"  # termin się zmienił
        istniejace = {p["id"] for p in stan["przypomnienia"]}
        stan["przypomnienia"].extend(p for p in plan if p["id"] not in istniejace)
        return True

    def _przypomnienia(self, stan: dict, teraz: datetime) -> None:
        """Wysyła zaległe przypomnienia – każde najwyżej raz, także gdy cron się spóźnił."""
        grupy: dict[str, list[dict]] = defaultdict(list)
        for p in stan["przypomnienia"]:
            if p["status"] == "oczekuje" and datetime.fromisoformat(p["termin"]) <= teraz:
                grupy[p["start"]].append(p)
        for start_iso, zalegle in grupy.items():
            start = datetime.fromisoformat(start_iso)
            if teraz > start + PRZYPOMNIENIE_WAZNE_PO_STARCIE:
                for p in zalegle:
                    p["status"] = "przeterminowane"
                continue
            # Kilka zaległych naraz (np. przerwa w działaniu) -> wysyłamy tylko najświeższe.
            zalegle.sort(key=lambda p: p["termin"])
            for p in zalegle[:-1]:
                p["status"] = "pominiete"
            najnowsze = zalegle[-1]
            if self._wyslij(W.przypomnienie(najnowsze, teraz=teraz, strefa=self.k.strefa, url=self.k.url)):
                najnowsze["status"] = "wyslane"
                najnowsze["wyslano"] = teraz.isoformat(timespec="seconds")
        # sprzątanie: zakończone przypomnienia sprzed ponad 30 dni
        stan["przypomnienia"] = [
            p for p in stan["przypomnienia"]
            if p["status"] == "oczekuje" or datetime.fromisoformat(p["start"]) > teraz - PRZECHOWUJ_PRZYPOMNIENIA
        ]

    # ------------------------------------------------------------ heartbeat

    def _heartbeat(self, stan: dict, teraz: datetime, status_http: int | None, wynik: str, zmiana: bool) -> None:
        if not self.k.heartbeat_wlaczony:
            return
        lokalnie = teraz.astimezone(self.k.strefa)
        dzien = lokalnie.date().isoformat()
        if lokalnie.hour < self.k.heartbeat_godzina or stan["heartbeat"].get("ostatni_dzien") == dzien:
            return
        tekst = W.heartbeat(
            teraz=teraz, strefa=self.k.strefa, status_http=status_http, wynik=wynik, zmiana=zmiana,
            kolejne_bledy=int(stan["bledy"].get("kolejne") or 0), przypomnienia=stan["przypomnienia"],
        )
        if self._wyslij(tekst):
            stan["heartbeat"]["ostatni_dzien"] = dzien


# ---------------------------------------------------------------- --test-alert

def tekst_testowego_alertu(konfig: Konfiguracja, teraz: datetime) -> str:
    """Przykładowy alert PILNY przepuszczony przez prawdziwą klasyfikację i ekstrakcję."""
    start = (teraz.astimezone(konfig.strefa) + timedelta(days=14)).date()
    miesiace = ["stycznia", "lutego", "marca", "kwietnia", "maja", "czerwca", "lipca", "sierpnia",
                "września", "października", "listopada", "grudnia"]
    linie = [
        "IV NABÓR WNIOSKÓW O POŻYCZKĘ woj. lubelskie, mazowieckie (PRZYKŁAD TESTOWY)",
        f"Informujemy, że od dnia {start.day} {miesiace[start.month - 1]} {start.year} r. (od godz. 8:30) "
        "Lubelska Fundacja Rozwoju przyjmować będzie wnioski o niskooprocentowaną pożyczkę na podjęcie "
        "działalności gospodarczej.",
        "kwota do dyspozycji w ramach naboru – 2 000 000,00 zł",
    ]
    z = Zmiana(rodzaj=TEKST, nowe=linie, stare=[], kontekst=linie)
    kl = klasyfikuj(z, teraz, konfig.strefa, konfig.godzina_startu_gdy_brak)
    plan = []
    if kl.start is not None:
        for p in konfig.przypomnienia:
            plan.append({"termin": (kl.start - p.wyprzedzenie).isoformat(), "etykieta": p.etykieta})
    return W.alert_pilny(kl, z, url=konfig.url, moje=konfig.moje_wojewodztwa, strefa=konfig.strefa,
                         teraz=teraz, przypomnienia=plan, test=True)


# ---------------------------------------------------------------- --podglad

def wpisy_strony(linie: list[str], tytul: list[str] | None = None) -> list[Zmiana]:
    """Wpisy artykułu (od najnowszego) jako `Zmiana` – tak, jakby każdy właśnie dopisano.

    Wpis = linie między separatorami („……”). Kontrakt jak z `porownaj()` dla bloku dopisanego
    na górze: `nowe` = linie wpisu, `stare` puste, `kontekst` = sekcja od jej początku do końca
    wpisu – u najnowszego razem z nagłówkiem strony (data publikacji i tytuł <h1>), który
    sam wpisem nie jest.
    """
    sekcje: list[list[str]] = [[]]
    for linia in linie:
        if czy_separator(linia):
            sekcje.append([])
        else:
            sekcje[-1].append(linia)
    wynik: list[Zmiana] = []
    for nr, sekcja in enumerate(sekcje):
        naglowek = 0
        if nr == 0 and tytul:
            # Tytuł jest na samej górze (najwyżej za linią z datą publikacji).
            klucze = [klucz(l) for l in sekcja[: len(tytul) + 3]]
            if klucz(tytul[-1]) in klucze:
                naglowek = klucze.index(klucz(tytul[-1])) + 1
        if sekcja[naglowek:]:
            wynik.append(Zmiana(rodzaj=TEKST, nowe=sekcja[naglowek:], stare=[], kontekst=list(sekcja)))
    return wynik


def tekst_podgladu(konfig: Konfiguracja, tresc: Tresc, teraz: datetime, *,
                   tytul: list[str] | None = None, z_pliku: bool = False) -> str | None:
    """Treść wiadomości --podglad (None, gdy na stronie nie ma żadnego wpisu)."""
    wpisy = wpisy_strony(tresc.linie, tytul)
    if not wpisy:
        return None
    sklasyfikowane = [(z, klasyfikuj(z, teraz, konfig.strefa, konfig.godzina_startu_gdy_brak)) for z in wpisy]
    return W.podglad_strony(
        sklasyfikowane, url=konfig.url, moje=konfig.moje_wojewodztwa, strefa=konfig.strefa, teraz=teraz,
        dokumenty=tresc.dokumenty, odnosniki=tresc.linki, z_pliku=z_pliku,
    )


def podglad(konfig: Konfiguracja, kanal: Kanal, *, zrodlo: Callable[[], Odpowiedz],
            zegar: Callable[[], datetime] = teraz_utc) -> int:
    """--podglad: JEDNA wiadomość z aktualną treścią strony (najnowszy wpis w formie alertu).

    Celowo bez `MagazynStanu`: niczego nie czyta ani nie zapisuje w state/ – wersja bazowa,
    wysłane alerty, przypomnienia, liczniki błędów, heartbeat i log.jsonl zostają nietknięte.
    Kod wyjścia: 0 – wysłano; 1 – błąd pobrania/odczytu strony albo wysyłki.
    Przy błędzie strony nic nie jest wysyłane.
    """
    teraz = zegar().astimezone(timezone.utc)
    try:
        odp = zrodlo()
        tresc = wyciagnij_tresc(
            odp.html, konfig.selektory_tresci, konfig.selektor_dokumentow,
            konfig.oczekiwane_frazy, konfig.min_linii, konfig.url,
        )
    except BladPobierania as e:
        print(f"PODGLĄD NIEUDANY – błąd pobrania strony: {e}", file=sys.stderr)
        return 1
    except BladEkstrakcji as e:
        print(f"PODGLĄD NIEUDANY – nie da się wyciągnąć treści: {e}", file=sys.stderr)
        return 1
    tekst = tekst_podgladu(konfig, tresc, teraz, tytul=tytul_artykulu(odp.html, konfig.selektory_tresci),
                           z_pliku=odp.status_http is None)
    if tekst is None:
        print("PODGLĄD NIEUDANY – na stronie nie znaleziono żadnego wpisu.", file=sys.stderr)
        return 1
    try:
        kanal.wyslij(tekst)
    except BladWysylki as e:
        print(f"PODGLĄD NIEUDANY – błąd wysyłki: {e}", file=sys.stderr)
        return 1
    return 0
