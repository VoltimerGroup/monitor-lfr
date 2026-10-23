"""Wiersz poleceń: python -m monitor_lfr [--dry-run] [--test-alert | --podglad] [--plik strona.html]"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .kanaly import BladWysylki, KanalKonsola, KanalNieskonfigurowany, kanal_z_srodowiska
from .konfiguracja import DOMYSLNY_KATALOG_STANU, BladKonfiguracji, wczytaj
from .monitor import Monitor, podglad, teraz_utc, tekst_testowego_alertu
from .pobieranie import Odpowiedz, pobierz_strone
from .stan import BladStanu, MagazynStanu


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="python -m monitor_lfr",
        description="Monitor strony LFR „Pierwszy biznes – Wsparcie w starcie”. "
                    "Tylko powiadamia – nigdy nie wysyła wniosków ani maili do fundacji.",
    )
    p.add_argument("--dry-run", action="store_true",
                   help="nic nie wysyła – drukuje wiadomości w konsoli (stan zapisuje jak zwykły przebieg)")
    p.add_argument("--test-alert", action="store_true",
                   help="wysyła przykładowy alert PILNY (sprawdzenie dostarczenia na telefon); nie zmienia stanu")
    p.add_argument("--podglad", action="store_true",
                   help="wysyła JEDNĄ wiadomość z aktualną treścią strony (najnowszy wpis w formie alertu); "
                        "nie zmienia stanu")
    p.add_argument("--plik", metavar="HTML", help="czytaj stronę z pliku zamiast z sieci")
    p.add_argument("--config", metavar="JSON", help="ścieżka do config.json (domyślnie w katalogu repozytorium)")
    p.add_argument("--stan-dir", metavar="KATALOG",
                   help=f"katalog stanu (domyślnie {DOMYSLNY_KATALOG_STANU})")
    return p


def _utf8_na_wyjsciu() -> None:
    for strumien in (sys.stdout, sys.stderr):
        try:
            strumien.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass


def main(argv: list[str] | None = None) -> int:
    _utf8_na_wyjsciu()
    args = _parser().parse_args(argv)
    if args.podglad and args.test_alert:
        # Dwie różne wiadomości – zamiast zgadywać kolejność, prosimy o osobne uruchomienia.
        print("BŁĄD: --podglad i --test-alert wykluczają się – uruchom każdą opcję osobno.", file=sys.stderr)
        return 2
    try:
        konfig = wczytaj(args.config)
    except BladKonfiguracji as e:
        print(f"BŁĄD KONFIGURACJI: {e}", file=sys.stderr)
        return 2

    kanal = KanalKonsola() if args.dry_run else kanal_z_srodowiska(konfig.kanal)
    nieskonfigurowany = isinstance(kanal, KanalNieskonfigurowany)
    if nieskonfigurowany:
        print(f"UWAGA: kanał powiadomień nie działa – {kanal.powod}", file=sys.stderr)

    if args.test_alert:
        try:
            kanal.wyslij(tekst_testowego_alertu(konfig, teraz_utc()))
        except BladWysylki as e:
            print(f"Test NIEUDANY: {e}", file=sys.stderr)
            return 1
        print("Testowy alert PILNY wysłany." if not args.dry_run else "Testowy alert wydrukowany (dry-run).")
        return 0

    if args.plik:
        sciezka = Path(args.plik)
        if not sciezka.is_file():
            print(f"Nie ma pliku: {sciezka}", file=sys.stderr)
            return 2

        def zrodlo() -> Odpowiedz:
            return Odpowiedz(status_http=None, html=sciezka.read_bytes().decode("utf-8", errors="replace"))
    else:
        def zrodlo() -> Odpowiedz:
            return pobierz_strone(
                konfig.url, timeout_s=konfig.timeout_s, ponowienia=konfig.ponowienia,
                backoff_s=konfig.backoff_s, user_agent=konfig.user_agent,
            )

    if args.podglad:
        # Bez MagazynStanu: podgląd nie czyta ani nie zapisuje niczego w katalogu stanu.
        kod = podglad(konfig, kanal, zrodlo=zrodlo)
        if kod == 0:
            print("Podgląd strony wysłany." if not args.dry_run else "Podgląd strony wydrukowany (dry-run).")
        return kod

    magazyn = MagazynStanu(Path(args.stan_dir) if args.stan_dir else DOMYSLNY_KATALOG_STANU)
    try:
        wynik = Monitor(konfig, kanal, magazyn, zrodlo=zrodlo).przebieg()
    except BladStanu as e:
        print(f"BŁĄD STANU: {e}", file=sys.stderr)
        return 2
    # Brak sekretów = czerwony przebieg w Actions (GitHub może wtedy wysłać e-mail).
    return max(wynik.kod_wyjscia, 1 if nieskonfigurowany else 0)
