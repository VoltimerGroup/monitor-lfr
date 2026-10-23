"""Treść powiadomień (zwykły tekst – bez formatowania Markdown, żeby nic się nie „rozjechało”)."""

from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from .ekstrakcja import Plik
from .kanaly import LIMIT_TELEGRAM, przytnij
from .klasyfikacja import PILNE, Klasyfikacja, kanoniczne_wojewodztwo
from .porownanie import (
    LINK_NOWY, LINK_USUNIETY, LINK_ZMIENIONY, PLIK_NOWY, PLIK_USUNIETY, PLIK_ZMIENIONY,
    TEKST_DOKUMENTOW, Zmiana,
)

TYTUL_PILNY = "[PILNE] NOWY NABÓR – Pierwszy biznes (LFR)"
TYTUL_INFO = "[INFO] Zmiana na stronie – Pierwszy biznes (LFR)"
TYTUL_AWARIA = "[AWARIA] Monitor nie może odczytać strony LFR"
TYTUL_POWROT = "[OK] Monitor znowu działa"
TYTUL_HEARTBEAT = "[HEARTBEAT] Monitor LFR działa"
# Nagłówek mówi o WIADOMOŚCI (nie sygnalizuje zmiany), a nie o stronie – czy na stronie jest
# aktualny nabór, mówi dopiero linia UWAGA pod nim (_uwaga_aktualny_nabor).
TYTUL_PODGLAD = "🔎 PODGLĄD — aktualna treść strony (to NIE jest powiadomienie o zmianie)"
PRZYPOMNIENIA_PODGLADU = "podgląd ich nie planuje ani nie zmienia (planuje je zwykły alert PILNY)"

MAKS_FRAGMENTU = 500
MAKS_POZYCJI_INFO = 8
MAKS_WPISOW_PODGLADU = 5  # tyle starszych wpisów (tytuł + start naboru) wymienia podgląd
MAKS_ODNOSNIKOW_PODGLADU = 3
MAKS_TYTULU_WPISU = 100

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


def _odmiana(n: int, jeden: str, kilka: str, wiele: str) -> str:
    """1 plik, 2 pliki, 5 plików, 22 pliki, 112 plików."""
    if n == 1:
        return f"1 {jeden}"
    if n % 10 in (2, 3, 4) and n % 100 not in (12, 13, 14):
        return f"{n} {kilka}"
    return f"{n} {wiele}"


def oznaczenie_wojewodztw(wojewodztwa: list[str], moje: list[str]) -> tuple[str, str]:
    """Zwraca (status, linia): status = TAK / NIE / NIEZNANE."""
    if not wojewodztwa:
        return "NIEZNANE", ">>> NIE ODCZYTANO WOJEWÓDZTW – sprawdź w ogłoszeniu, czy dotyczy Ciebie <<<"
    # Porównanie po postaci kanonicznej (konfiguracja jest już kanoniczna – to druga linia obrony).
    moje_kan = {kanoniczne_wojewodztwo(m) or m for m in moje}
    wspolne = [w for w in wojewodztwa if (kanoniczne_wojewodztwo(w) or w) in moje_kan]
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
    if k.poprzednia_zapowiedz:
        linie.append(f"UWAGA: ZMIANA PLANOWANEGO TERMINU (poprzednio: {k.poprzednia_zapowiedz})")
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


# ---------------------------------------------------------------- podgląd (--podglad)

def _tytul_wpisu(linie: list[str], z_druga_linia: bool = False) -> str:
    """Pierwsza linia wpisu; sam nagłówek w rodzaju „KOMUNIKAT:” sklejamy z następną linią.

    `z_druga_linia` – dla wpisów o tym samym nagłówku (np. dwa razy „III NABÓR…”: ogłoszenie
    i lista wniosków), żeby dało się je odróżnić.
    """
    if z_druga_linia and len(linie) > 1:
        return _przytnij(f"{linie[0]} – {linie[1]}", MAKS_TYTULU_WPISU + 40)
    tytul = linie[0]
    for linia in linie[1:]:
        if len(tytul) >= 25:
            break
        tytul += " " + linia
    return _przytnij(tytul, MAKS_TYTULU_WPISU)


def _start_wpisu(k: Klasyfikacja, strefa: ZoneInfo) -> str | None:
    """Start naboru odczytany z wpisu – tylko pewna data; bez godziny, gdy jej nie podano."""
    if k.start is None or k.dane is None or not k.dane.pewna_data:
        return None
    if k.dane.godzina_startu is None:
        return f"{k.start.astimezone(strefa):%d.%m.%Y}"
    return format_krotki(k.start, strefa)


def _dane_klasyfikacji(k: Klasyfikacja, moje: list[str], strefa: ZoneInfo) -> list[str]:
    """Co klasyfikacja odczytała z wpisu – wyłącznie pola, które naprawdę odczytała."""
    d = k.dane
    if d is None:
        return []
    linie: list[str] = []
    if d.wojewodztwa:
        linie.append(oznaczenie_wojewodztw(d.wojewodztwa, moje)[1])
        linie.append("Województwa: " + ", ".join(d.wojewodztwa))
    if d.numer:
        linie.append(f"Nabór: {d.numer}")
    if k.start is not None:
        start = (f"Start: {k.start.astimezone(strefa):%d.%m.%Y} (godziny nie podano)"
                 if d.godzina_startu is None else f"Start: {format_daty(k.start, strefa)}")
        if not d.pewna_data:
            start += " (data bez słów „od dnia”/„Rozpoczęcie naboru” – sprawdź w ogłoszeniu)"
        linie.append(start)
    if d.zapowiedz:
        linie.append(f"Planowany termin: {d.zapowiedz}")
    if d.kwoty:
        linie.append(f"Pula: {opis_kwot(d.kwoty)}")
    return linie


def _uwaga_aktualny_nabor(k: Klasyfikacja, strefa: ZoneInfo, teraz: datetime) -> str:
    """Druga linia podglądu, gdy najnowszy wpis jest PILNY – widać ją w powiadomieniu tuż pod nagłówkiem.

    PILNE znaczy: start nie minął dawniej niż PROG_HISTORYCZNY temu albo go nie odczytano
    (wtedy pokazujemy planowany termin, jeśli jest).
    """
    d = k.dane
    if k.start is not None:
        kiedy = "start " + (f"{k.start.astimezone(strefa):%d.%m.%Y}" if d and d.godzina_startu is None
                            else format_daty(k.start, strefa))
        if k.start <= teraz:
            kiedy += " – JUŻ TRWA lub minął"
    elif d and d.zapowiedz:
        kiedy = f"planowany termin: {_przytnij(d.zapowiedz, 60)}"
    else:
        kiedy = "daty startu nie odczytano"
    return f"UWAGA: najnowszy wpis wygląda na AKTUALNY nabór ({kiedy}) – sprawdź stronę i zwykłe alerty."


def podglad_strony(
    wpisy: list[tuple[Zmiana, Klasyfikacja]],
    *,
    url: str,
    moje: list[str],
    strefa: ZoneInfo,
    teraz: datetime,
    dokumenty: list[Plik] | None,
    odnosniki: list[Plik],
    z_pliku: bool = False,
) -> str:
    """--podglad: najnowszy wpis w formie prawdziwego alertu + krótki przegląd strony.

    `wpisy` – od najnowszego; każdy jako `Zmiana` „dopisana na górze” razem z klasyfikacją.
    Pokazujemy tylko to, co odczytały ekstrakcja i klasyfikacja. Stopka (godzina odczytu
    i adres) zostaje zawsze – przy limicie Telegrama najpierw ubywa listy starszych wpisów.
    """
    z, k = wpisy[0]
    glowna = [TYTUL_PODGLAD]
    if k.poziom == PILNE:
        glowna.append(_uwaga_aktualny_nabor(k, strefa, teraz))
    glowna += [
        "Najnowszy wpis ze strony – tak wyglądałby alert, gdyby ten wpis właśnie się pojawił.",
        "Monitor nic nie zapisał ani nie zaplanował (stan bez zmian).",
        "",
        "----- przykład alertu -----",
    ]
    if k.poziom == PILNE:
        glowna.append(alert_pilny(k, z, url=url, moje=moje, strefa=strefa, teraz=teraz, przypomnienia=[],
                                  powod_braku_przypomnien=PRZYPOMNIENIA_PODGLADU))
    else:
        glowna.append(alert_info([(z, k)], url=url, strefa=strefa))
    glowna += ["----- koniec przykładu -----", "", f"Klasyfikacja wpisu: {k.poziom} – {k.powod}",
               "Dopasowane wzorce naboru: " + (", ".join(k.wzorce) if k.wzorce else "brak")]
    if k.poziom != PILNE:
        glowna += _dane_klasyfikacji(k, moje, strefa)  # alert PILNY pokazuje je sam
    glowna.append("")
    if odnosniki:
        glowna.append(f"Odnośniki w treści strony ({len(odnosniki)}):")
        for p in odnosniki[:MAKS_ODNOSNIKOW_PODGLADU]:
            glowna.append(f"- {_przytnij(p.nazwa, MAKS_TYTULU_WPISU)}\n   {p.url or '(bez linku)'}")
        if len(odnosniki) > MAKS_ODNOSNIKOW_PODGLADU:
            glowna.append("…oraz " + _odmiana(len(odnosniki) - MAKS_ODNOSNIKOW_PODGLADU, "inny", "inne", "innych")
                          + " – zobacz stronę.")
    if dokumenty is None:
        glowna.append("Dokumenty do pobrania: nie znaleziono sekcji na stronie.")
    else:
        glowna.append("Dokumenty do pobrania: " + _odmiana(len(dokumenty), "plik", "pliki", "plików") + ".")

    starsze = []
    tytuly = [_tytul_wpisu(z_st.nowe) for z_st, _ in wpisy[1:]]
    for (z_st, k_st), tytul in zip(wpisy[1:], tytuly):
        if tytuly.count(tytul) > 1:
            tytul = _tytul_wpisu(z_st.nowe, z_druga_linia=True)
        start = _start_wpisu(k_st, strefa)
        starsze.append(f"• start naboru {start} – {tytul}" if start else f"• {tytul}")

    def z_lista(n: int) -> str:
        linie = list(glowna)
        if n:
            linie += ["", "Starsze wpisy na stronie:"] + starsze[:n]
        if len(starsze) > n:
            linie.append("…i jeszcze " + _odmiana(len(starsze) - n, "starszy wpis", "starsze wpisy",
                                                  "starszych wpisów") + " na stronie.")
        return "\n".join(linie)

    zrodlo = " – treść z pliku (--plik), nie z sieci" if z_pliku else ""
    stopka = f"\n\nOdczyt strony: {format_daty(teraz, strefa)} ({strefa.key}){zrodlo}\n{url}"
    limit = LIMIT_TELEGRAM - len(stopka)
    n = min(MAKS_WPISOW_PODGLADU, len(starsze))
    tresc = z_lista(n)
    while len(tresc) > limit and n > 0:
        n -= 1
        tresc = z_lista(n)
    return przytnij(tresc, limit) + stopka


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
