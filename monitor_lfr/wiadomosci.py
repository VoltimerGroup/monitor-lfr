"""Treść powiadomień (zwykły tekst – bez formatowania Markdown, żeby nic się nie „rozjechało”)."""

from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from .klasyfikacja import Klasyfikacja
from .porownanie import (
    LINK_NOWY, LINK_USUNIETY, LINK_ZMIENIONY, PLIK_NOWY, PLIK_USUNIETY, PLIK_ZMIENIONY,
    TEKST_DOKUMENTOW, Zmiana,
)

TYTUL_PILNY = "[PILNE] NOWY NABÓR – Pierwszy biznes (LFR)"
TYTUL_INFO = "[INFO] Zmiana na stronie – Pierwszy biznes (LFR)"
TYTUL_AWARIA = "[AWARIA] Monitor nie może odczytać strony LFR"
TYTUL_POWROT = "[OK] Monitor znowu działa"
TYTUL_HEARTBEAT = "[HEARTBEAT] Monitor LFR działa"

MAKS_FRAGMENTU = 500
MAKS_POZYCJI_INFO = 8

CHECKLISTA = [
    "komplet dokumentów gotowy WCZEŚNIEJ (wniosek + wszystkie załączniki, sprawdzone i podpisane)",
    "kwalifikowany podpis elektroniczny – profil zaufany NIE wystarcza",
    "dokumenty poręczyciela (oświadczenie, zaświadczenie o dochodach, upoważnienie BIG)",
    "weksel in blanco",
    "„liczy się godzina wpływu maila na serwer LFR, nie godzina wysłania” – wysyłaj od razu po starcie",
]
STOPKA = (
    "Ostatni nabór zamknął się po ok. 50 minutach.\n"
    "Monitor tylko powiadamia – wniosek składasz samodzielnie."
)

_DNI_TYGODNIA = ["poniedziałek", "wtorek", "środa", "czwartek", "piątek", "sobota", "niedziela"]


# ---------------------------------------------------------------- pomocnicze

def format_daty(dt: datetime, strefa: ZoneInfo, z_dniem: bool = True) -> str:
    d = dt.astimezone(strefa)
    tekst = f"{d:%d.%m.%Y}, godz. {d.hour}:{d.minute:02d}"
    return f"{_DNI_TYGODNIA[d.weekday()]} {tekst}" if z_dniem else tekst


def format_krotki(dt: datetime, strefa: ZoneInfo) -> str:
    d = dt.astimezone(strefa)
    return f"{d:%d.%m.%Y} {d.hour}:{d.minute:02d}"


def format_okresu(delta: timedelta) -> str:
    """timedelta -> „2 dni 3 godz. 5 min” (zaokrąglenie w dół do minut)."""
    minuty = max(0, int(delta.total_seconds() // 60))
    dni, reszta = divmod(minuty, 24 * 60)
    godz, minut = divmod(reszta, 60)
    czesci = []
    if dni:
        czesci.append("1 dzień" if dni == 1 else f"{dni} dni")
    if godz:
        czesci.append(f"{godz} godz.")
    if minut or not czesci:
        czesci.append(f"{minut} min")
    return " ".join(czesci)


def format_kwoty(k: Decimal) -> str:
    calosc = int(k)
    grosze = int((k - calosc) * 100)
    return f"{calosc:,}".replace(",", " ") + f",{grosze:02d} zł"


def opis_kwot(kwoty: list[Decimal]) -> str | None:
    if not kwoty:
        return None
    tekst = " + ".join(format_kwoty(k) for k in kwoty)
    if len(kwoty) > 1:
        tekst += f" (razem {format_kwoty(sum(kwoty, Decimal(0)))})"
    return tekst


def _przytnij(tekst: str, limit: int) -> str:
    return tekst if len(tekst) <= limit else tekst[: limit - 1].rstrip() + "…"


def oznaczenie_wojewodztw(wojewodztwa: list[str], moje: list[str]) -> tuple[str, str]:
    """Zwraca (status, linia): status = TAK / NIE / NIEZNANE."""
    if not wojewodztwa:
        return "NIEZNANE", ">>> NIE ODCZYTANO WOJEWÓDZTW – sprawdź w ogłoszeniu, czy dotyczy Ciebie <<<"
    wspolne = [w for w in wojewodztwa if w in moje]
    if wspolne:
        return "TAK", f">>> DOTYCZY TWOICH WOJEWÓDZTW: {', '.join(wspolne)} <<<"
    return "NIE", f">>> NIE dotyczy Twoich województw ({', '.join(moje)}) <<<"


# ---------------------------------------------------------------- alert PILNY

def alert_pilny(
    k: Klasyfikacja,
    zmiana: Zmiana,
    *,
    url: str,
    moje: list[str],
    strefa: ZoneInfo,
    teraz: datetime,
    przypomnienia: list[dict],
    powod_braku_przypomnien: str | None = None,
    test: bool = False,
) -> str:
    d = k.dane
    linie: list[str] = []
    if test:
        linie += ["TO JEST WIADOMOŚĆ TESTOWA (--test-alert) – dane są fikcyjne.",
                  "Jeśli ją widzisz na telefonie, powiadomienia działają.", ""]
    linie.append(TYTUL_PILNY)
    linie.append("")
    _, oznaczenie = oznaczenie_wojewodztw(d.wojewodztwa if d else [], moje)
    linie.append(oznaczenie)
    if k.zmiana_terminu and k.poprzedni_start:
        linie.append(f"UWAGA: ZMIANA TERMINU (poprzednio: {format_daty(k.poprzedni_start, strefa)})")
    linie.append("Województwa: " + (", ".join(d.wojewodztwa) if d and d.wojewodztwa else "nie odczytano"))
    linie.append("Nabór: " + (d.numer if d and d.numer else "numer nieodczytany"))
    if k.start is not None:
        start = f"Start: {format_daty(k.start, strefa)}"
        if d and d.godzina_startu is None:
            start += " (godziny nie podano – przyjęto ją do przypomnień, SPRAWDŹ)"
        do_startu = k.start - teraz
        start += f" – za {format_okresu(do_startu)}" if do_startu.total_seconds() > 0 else " – JUŻ TRWA lub minął"
        linie.append(start)
        if d and not d.pewna_data:
            linie.append("(data odczytana bez słów „od dnia”/„Rozpoczęcie naboru” – sprawdź w ogłoszeniu)")
    else:
        linie.append("Start: nie odczytano daty – sprawdź ogłoszenie")
    if d and d.zapowiedz:
        linie.append(f"Planowany termin: {d.zapowiedz}")
    linie.append("Pula: " + (opis_kwot(d.kwoty) if d and d.kwoty else "nie odczytano"))
    linie.append("")
    linie.append("Fragment ogłoszenia:")
    linie.append(_przytnij(zmiana.tekst_nowy, MAKS_FRAGMENTU))
    linie.append("")
    linie.append(f"Link: {url}")
    linie.append("")
    if przypomnienia:
        linie.append("Przypomnienia: " + "; ".join(
            f"{format_krotki(datetime.fromisoformat(p['termin']), strefa)} ({p['etykieta']} przed)"
            for p in przypomnienia))
    else:
        linie.append("Przypomnienia: " + (powod_braku_przypomnien or "brak"))
    linie.append("")
    linie.append("CHECKLISTA:")
    linie += [f"[ ] {pozycja}" for pozycja in CHECKLISTA]
    linie.append("")
    linie.append(STOPKA)
    return "\n".join(linie)


# ---------------------------------------------------------------- alert INFO

def _opis_zmiany(z: Zmiana, k: Klasyfikacja | None, strefa: ZoneInfo) -> str:
    if z.rodzaj == PLIK_NOWY:
        return f"Nowy plik w „Dokumenty do pobrania”: {z.plik.nazwa}\n   {z.plik.url or '(bez linku)'}"
    if z.rodzaj == PLIK_USUNIETY:
        return f"Usunięto plik z „Dokumenty do pobrania”: {z.stary_plik.nazwa}"
    if z.rodzaj == PLIK_ZMIENIONY:
        return f"Zmieniony plik w „Dokumenty do pobrania”: {z.plik.nazwa}\n   {z.plik.url or '(bez linku)'}"
    if z.rodzaj == LINK_NOWY:
        return f"Nowy odnośnik w treści: {z.plik.nazwa}\n   {z.plik.url}"
    if z.rodzaj == LINK_USUNIETY:
        return f"Usunięto odnośnik z treści: {z.stary_plik.nazwa}"
    if z.rodzaj == LINK_ZMIENIONY:
        return f"Zmieniony odnośnik w treści: {z.plik.nazwa}\n   {z.plik.url}"
    gdzie = " (sekcja „Dokumenty do pobrania”)" if z.rodzaj == TEKST_DOKUMENTOW else ""
    if not z.nowe:
        return f"Usunięto fragment{gdzie}:\n{_przytnij(z.tekst_stary, 300)}"
    naglowek = f"Nowy/zmieniony fragment{gdzie}"
    if k is not None and k.powod not in ("inna zmiana",):
        dopisek = k.powod
        if k.start is not None:
            dopisek += f", start {format_krotki(k.start, strefa)}"
        naglowek += f" ({dopisek})"
    return f"{naglowek}:\n{_przytnij(z.tekst_nowy, 300)}"


def alert_info(pozycje: list[tuple[Zmiana, Klasyfikacja | None]], *, url: str, strefa: ZoneInfo) -> str:
    linie = [TYTUL_INFO, ""]
    for i, (z, k) in enumerate(pozycje[:MAKS_POZYCJI_INFO], start=1):
        linie.append(f"{i}) {_opis_zmiany(z, k, strefa)}")
        linie.append("")
    if len(pozycje) > MAKS_POZYCJI_INFO:
        linie.append(f"…oraz {len(pozycje) - MAKS_POZYCJI_INFO} innych zmian – zobacz stronę.")
        linie.append("")
    linie.append(f"Link: {url}")
    return "\n".join(linie)


# ---------------------------------------------------------------- przypomnienia

def przypomnienie(p: dict, *, teraz: datetime, strefa: ZoneInfo, url: str) -> str:
    start = datetime.fromisoformat(p["start"])
    termin = datetime.fromisoformat(p["termin"])
    zostalo = start - teraz
    opis = p.get("opis", "")
    if zostalo.total_seconds() <= 0:
        linie = [
            "[PILNE] NABÓR JUŻ TRWA – Pierwszy biznes (LFR)",
            f"Start był {format_daty(start, strefa)} ({format_okresu(-zostalo)} temu).",
            "Jeśli dokumenty są gotowe – wysyłaj natychmiast.",
        ]
    else:
        linie = [
            f"[PRZYPOMNIENIE] Nabór Pierwszy biznes (LFR) – start za {format_okresu(zostalo)}",
            f"Start: {format_daty(start, strefa)}",
            f"Zostało: {format_okresu(zostalo)}",
        ]
    spoznienie = teraz - termin
    if spoznienie > timedelta(minutes=5):
        linie.append(f"(przypomnienie „{p['etykieta']} przed” wysłane z opóźnieniem {format_okresu(spoznienie)} "
                     "– opóźnienie uruchomienia monitora)")
    if opis:
        linie.append(opis)
    linie += ["", f"Link: {url}", "", "CHECKLISTA:"]
    linie += [f"[ ] {pozycja}" for pozycja in CHECKLISTA]
    linie += ["", STOPKA]
    return "\n".join(linie)


# ---------------------------------------------------------------- awaria / powrót / heartbeat

def awaria(*, kolejne: int, od: datetime | None, blad: str, url: str, strefa: ZoneInfo) -> str:
    linie = [TYTUL_AWARIA, "", f"Kolejne nieudane próby: {kolejne}"]
    if od is not None:
        linie[-1] += f" (od {format_krotki(od, strefa)})"
    linie += [f"Błąd: {_przytnij(blad, 600)}", "",
              "Do czasu naprawy sprawdzaj stronę ręcznie:", url]
    return "\n".join(linie)


def powrot(*, od: datetime | None, teraz: datetime, strefa: ZoneInfo) -> str:
    linie = [TYTUL_POWROT, "Strona LFR znów jest odczytywana poprawnie."]
    if od is not None:
        linie.append(f"Przerwa: od {format_krotki(od, strefa)} do {format_krotki(teraz, strefa)} "
                     f"({format_okresu(teraz - od)}).")
    linie.append("Zmiany z czasu przerwy zostaną zgłoszone w tym samym przebiegu (jeśli były).")
    return "\n".join(linie)


def heartbeat(*, teraz: datetime, strefa: ZoneInfo, status_http: int | None, wynik: str, zmiana: bool,
              kolejne_bledy: int, przypomnienia: list[dict]) -> str:
    stan = f"HTTP {status_http}" if status_http else "wejście z pliku"
    if wynik == "blad":
        opis = f"{stan}, BŁĄD odczytu"
    elif wynik == "baza":
        opis = f"{stan}, zapisano wersję bazową strony"
    else:
        opis = f"{stan}, " + ("wykryto zmianę" if zmiana else "bez zmian")
    linie = [TYTUL_HEARTBEAT, f"Monitor działa. Ostatnie sprawdzenie: {format_krotki(teraz, strefa)} – {opis}.",
             f"Kolejne nieudane odczyty: {kolejne_bledy}."]
    oczekujace = [p for p in przypomnienia if p.get("status") == "oczekuje"]
    if oczekujace:
        najblizsze = min(oczekujace, key=lambda p: p["termin"])
        linie.append(f"Zaplanowane przypomnienia: {len(oczekujace)} (najbliższe: "
                     f"{format_krotki(datetime.fromisoformat(najblizsze['termin']), strefa)}).")
    else:
        linie.append("Zaplanowane przypomnienia: brak.")
    return "\n".join(linie)
