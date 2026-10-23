"""Klasyfikacja nowych fragmentów (PILNE / INFO) i wyciąganie danych naboru.

Wejściem są ZAWSZE znormalizowane linie (myślniki -> "-", NBSP -> spacja), więc
wzorce nie muszą znać wszystkich odmian myślników i spacji.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from .porownanie import TEKST, Zmiana

PILNE = "PILNE"
INFO = "INFO"

_F = re.IGNORECASE | re.DOTALL

# Wzorce PILNE (nazwa do wyświetlenia, regex). Dopasowanie bez względu na wielkość
# liter, z polskimi znakami albo bez nich (ó/o, ę/e, ć/c).
WZORCE_PILNE: list[tuple[str, re.Pattern]] = [
    ("przyjmować będzie wnioski",
     re.compile(r"przyjmowa[ćc]\s+b[ęe]d(?:zie|ą)\s+wniosk|b[ęe]d(?:zie|ą)\s+przyjmowa[ćc]\s+wniosk", _F)),
    ("NABÓR WNIOSKÓW", re.compile(r"\bnab[oó]r\s+wniosk[oó]w\b", _F)),
    ("od dnia … (od godz.", re.compile(r"\bod\s+dnia\b.{1,80}?\(\s*od\s+godz", _F)),
    ("kwota do dyspozycji", re.compile(r"\bkwot\w*\s+do\s+dyspozycji\b", _F)),
    ("planowany jest", re.compile(r"\bplanowan[aey]\s+jest\b|\bjest\s+planowan[aey]\b", _F)),
    ("Rozpoczęcie naboru", re.compile(r"\brozpocz[ęe]ci[ea]\s+naboru\b", _F)),
    # Dodatkowe, ostrożne warianty tej samej informacji:
    ("nabór rozpocznie się",
     re.compile(r"\bnab[oó]r\w*\s+(?:wniosk[oó]w\s+)?rozpocznie\s+si[ęe]|\brozpocznie\s+si[ęe]\s+nab[oó]r", _F)),
]

# ---------------------------------------------------------------- daty i godziny

MIESIACE_DOPELNIACZ = {
    "stycznia": 1, "lutego": 2, "marca": 3, "kwietnia": 4, "maja": 5, "czerwca": 6,
    "lipca": 7, "sierpnia": 8, "września": 9, "wrzesnia": 9, "października": 10,
    "pazdziernika": 10, "listopada": 11, "grudnia": 12,
}
_MIES = "|".join(sorted(MIESIACE_DOPELNIACZ, key=len, reverse=True))

_DATA = (
    rf"(?:(?P<d1>\d{{1,2}})\s+(?P<mies>{_MIES})\b\s*(?:(?P<r1>\d{{4}})|(?P<br>b\.\s?r\.|br\.?))?"
    r"|(?P<d2>\d{1,2})\s*[./-]\s*(?P<m2>\d{1,2})\s*[./-]\s*(?P<r2>\d{4})"
    r"|(?P<r3>\d{4})-(?P<m3>\d{2})-(?P<d3>\d{2}))"
)

# Kotwice daty startu – od najpewniejszej. Ostatnia (sama data) = pewność niska.
_KOTWICE_STARTU: list[tuple[re.Pattern, bool]] = [
    (re.compile(r"\bod\s+dnia\s*" + _DATA, _F), True),
    (re.compile(r"\brozpocz[ęe]ci[ea]\s+naboru\s*[-:]?\s*(?:w\s+dniu\s+|dnia\s+)?" + _DATA, _F), True),
    (re.compile(r"\brozpocznie\s+si[ęe]\s+(?:w\s+dniu\s+|dnia\s+)?" + _DATA, _F), True),
    (re.compile(r"(?:\bw\s+dniu|(?<![zZ] )\bdnia)\s+" + _DATA, _F), True),
    (re.compile(r"(?<![\d.])" + _DATA, _F), False),
]

_GODZ_PO_DACIE = re.compile(r"godz\w*\.?\s*(\d{1,2})\s*[:.]\s*(\d{2})\b", _F)
_GODZ_TUZ_PO_DACIE = re.compile(r"^\s*(?:r\.?\s*)?,?\s*(\d{1,2}):(\d{2})\b", _F)
_OD_GODZ = re.compile(r"\bod\s+godz\w*\.?\s*(\d{1,2})\s*[:.]\s*(\d{2})\b", _F)

# ---------------------------------------------------------------- kwoty

_KWOTA = re.compile(
    r"\bkwot\w*\s+do\s+dyspozycji[^\d\n]{0,60}?(\d{1,3}(?:[ .]\d{3})+|\d+)(?:,(\d{1,2}))?\s*(?:zł|zl|pln)\b", _F
)

# ---------------------------------------------------------------- numer naboru

_RZYMSKIE = {"I": 1, "V": 5, "X": 10, "L": 50, "C": 100}
_NUMER_PRZED = re.compile(r"(?<![\w-])([IVXLC]{1,6}|\d{1,2})\s*\.?\s+(?i:nab[oó]r)\b")
_NUMER_PO = re.compile(r"(?i:\bnab[oó]r)\s+(?i:nr\.?\s*)?([IVXLC]{1,6}|\d{1,2})\b(?![./-]\d)")

# ---------------------------------------------------------------- województwa

# Kolejność ma znaczenie: najpierw nazwy złożone (żeby „kujawsko-pomorskie” nie dało
# też „pomorskie”, a „dolnośląskie” – „śląskie”).
WOJEWODZTWA: list[tuple[str, re.Pattern]] = [
    ("warmińsko-mazurskie", re.compile(r"warmi[nń]sko\s*-\s*mazur\w*", _F)),
    ("kujawsko-pomorskie", re.compile(r"kujawsko\s*-\s*pomor\w*", _F)),
    ("zachodniopomorskie", re.compile(r"zachodnio\s*-?\s*pomor\w*", _F)),
    ("dolnośląskie", re.compile(r"doln\w*\s*-?\s*[sś]l[aą]s\w*", _F)),
    ("świętokrzyskie", re.compile(r"[sś]wi[eę]tokrzysk\w*", _F)),
    ("małopolskie", re.compile(r"ma[łl]opol\w*", _F)),
    ("wielkopolskie", re.compile(r"wielkopol\w*", _F)),
    ("podkarpackie", re.compile(r"podkarpac\w*", _F)),
    ("lubelskie", re.compile(r"\blubels\w*", _F)),
    ("lubuskie", re.compile(r"\blubus\w*", _F)),
    ("łódzkie", re.compile(r"\b[łl][oó]dzk\w*", _F)),
    ("mazowieckie", re.compile(r"\bmazowie\w*|\bmazowsz\w*", _F)),
    ("opolskie", re.compile(r"\bopolsk\w*", _F)),
    ("podlaskie", re.compile(r"\bpodlas\w*", _F)),
    ("pomorskie", re.compile(r"\bpomorsk\w*", _F)),
    ("śląskie", re.compile(r"\b[sś]l[aą]sk\w*", _F)),
]
# Fragmenty po słowie „woj.” / „województwo…” – tam szukamy w pierwszej kolejności.
_PO_WOJ = re.compile(r"\bwoj(?:\.|ew[oó]dztw\w*)\s*:?\s*([^.;()\n]{1,200})", _F)
# Nazwa fundacji zawiera „Lubelska” – to NIE jest województwo.
_FUNDACJA = re.compile(r"\blubels\w*\s+fundacj\w*(?:\s+rozwoju)?", _F)

_ZAPOWIEDZ = re.compile(r"\b(?:planowan[aey]\s+jest|jest\s+planowan[aey])\s+([^.\n]{1,60}(?:\s*r\.)?)", _F)


@dataclass
class DaneNaboru:
    numer: str | None = None  # np. „IV” albo „4”
    numer_liczba: int | None = None
    wojewodztwa: list[str] = field(default_factory=list)
    data_startu: date | None = None
    godzina_startu: time | None = None
    pewna_data: bool = True  # False = data bez słowa-kotwicy („od dnia”, „Rozpoczęcie naboru”…)
    kwoty: list[Decimal] = field(default_factory=list)
    zapowiedz: str | None = None  # np. „na maj 2026 r.”

    def start(self, strefa: ZoneInfo, godzina_gdy_brak: time) -> datetime | None:
        """Data i godzina startu w strefie Europe/Warsaw (godzina domyślna, gdy nie podano)."""
        if self.data_startu is None:
            return None
        return datetime.combine(self.data_startu, self.godzina_startu or godzina_gdy_brak, tzinfo=strefa)

    def pusta(self) -> bool:
        return not (self.numer or self.wojewodztwa or self.data_startu or self.kwoty or self.zapowiedz)


def _rzymska_na_liczbe(s: str) -> int | None:
    wartosc, poprzednia = 0, 0
    for znak in reversed(s):
        v = _RZYMSKIE[znak]
        wartosc = wartosc - v if v < poprzednia else wartosc + v
        poprzednia = max(poprzednia, v)
    return wartosc if _liczba_na_rzymska(wartosc) == s else None  # odrzuca np. „IIII”, „VV”


def _liczba_na_rzymska(n: int) -> str:
    tab = [(100, "C"), (90, "XC"), (50, "L"), (40, "XL"), (10, "X"), (9, "IX"), (5, "V"), (4, "IV"), (1, "I")]
    wynik = ""
    for v, z in tab:
        while n >= v:
            wynik, n = wynik + z, n - v
    return wynik


def wyciagnij_numer(tekst: str) -> tuple[str | None, int | None]:
    for wzor in (_NUMER_PRZED, _NUMER_PO):
        for m in wzor.finditer(tekst):
            s = m.group(1)
            if s.isdigit():
                n = int(s)
                if 1 <= n <= 99:
                    return s, n
            else:
                n = _rzymska_na_liczbe(s)
                if n:
                    return s, n
    return None, None


def wyciagnij_wojewodztwa(tekst: str) -> list[str]:
    """Kanoniczne nazwy województw (w kolejności wystąpienia, bez powtórzeń)."""
    tekst = _FUNDACJA.sub(" ", tekst)
    segmenty = [m.group(1) for m in _PO_WOJ.finditer(tekst)]
    wynik = _wojewodztwa_w(" | ".join(segmenty)) if segmenty else []
    return wynik or _wojewodztwa_w(tekst)


def _wojewodztwa_w(tekst: str) -> list[str]:
    znalezione: list[tuple[int, str]] = []
    reszta = tekst
    for nazwa, wzor in WOJEWODZTWA:
        for m in wzor.finditer(reszta):
            znalezione.append((m.start(), nazwa))
        reszta = wzor.sub(lambda m: " " * len(m.group(0)), reszta)  # zachowujemy pozycje
    wynik: list[str] = []
    for _, nazwa in sorted(znalezione):
        if nazwa not in wynik:
            wynik.append(nazwa)
    return wynik


def kanoniczne_wojewodztwo(nazwa: str) -> str | None:
    """„Mazowieckim”, „mazowieckie” -> „mazowieckie” (do porównań z konfiguracją)."""
    w = _wojewodztwa_w(nazwa)
    return w[0] if w else None


def _data_z_dopasowania(m: re.Match, rok_biezacy: int) -> date | None:
    g = m.groupdict()
    try:
        if g.get("d1"):
            rok = int(g["r1"]) if g.get("r1") else rok_biezacy
            return date(rok, MIESIACE_DOPELNIACZ[g["mies"].lower()], int(g["d1"]))
        if g.get("d2"):
            return date(int(g["r2"]), int(g["m2"]), int(g["d2"]))
        if g.get("r3"):
            return date(int(g["r3"]), int(g["m3"]), int(g["d3"]))
    except (ValueError, KeyError):
        return None
    return None


def _godzina(h: str, m: str) -> time | None:
    try:
        return time(int(h), int(m))
    except ValueError:
        return None


def wyciagnij_start(tekst: str, rok_biezacy: int) -> tuple[date | None, time | None, bool]:
    """(data startu, godzina startu, czy data pewna)."""
    for wzor, pewna in _KOTWICE_STARTU:
        for m in wzor.finditer(tekst):
            d = _data_z_dopasowania(m, rok_biezacy)
            if d is None:
                continue
            za_data = tekst[m.end(): m.end() + 100]
            # Kolejność: „(od godz. 8:30)” tuż za datą -> „godz. 8:30” blisko daty ->
            # „8:30” zaraz po dacie -> „od godz.” gdziekolwiek we fragmencie.
            g = (_OD_GODZ.search(za_data) or _GODZ_PO_DACIE.search(za_data[:40])
                 or _GODZ_TUZ_PO_DACIE.search(za_data) or _OD_GODZ.search(tekst))
            return d, (_godzina(g.group(1), g.group(2)) if g else None), pewna
    return None, None, True


def wyciagnij_kwoty(tekst: str) -> list[Decimal]:
    kwoty: list[Decimal] = []
    for m in _KWOTA.finditer(tekst):
        calosc = re.sub(r"[ .]", "", m.group(1))
        grosze = (m.group(2) or "0").ljust(2, "0")
        k = Decimal(f"{calosc}.{grosze}")
        if k > 0 and k not in kwoty:
            kwoty.append(k)
    return kwoty


def wyciagnij_zapowiedz(tekst: str) -> str | None:
    m = _ZAPOWIEDZ.search(tekst)
    return m.group(1).strip() if m else None


def wyciagnij_dane(tekst: str, kontekst: str = "", rok_biezacy: int | None = None) -> DaneNaboru:
    """Dane z fragmentu; brakujące pola uzupełniane z kontekstu (sekcji ogłoszenia)."""
    rok = rok_biezacy or date.today().year
    dane = _dane_z(tekst, rok)
    if kontekst and kontekst != tekst:
        z_kontekstu = _dane_z(kontekst, rok)
        if dane.numer is None:
            dane.numer, dane.numer_liczba = z_kontekstu.numer, z_kontekstu.numer_liczba
        if not dane.wojewodztwa:
            dane.wojewodztwa = z_kontekstu.wojewodztwa
        # Z kontekstu bierzemy tylko datę z kotwicą („od dnia”, „Rozpoczęcie naboru”…) –
        # inaczej np. data publikacji strony („15.12.2025”) udawałaby datę startu.
        if dane.data_startu is None and z_kontekstu.pewna_data:
            dane.data_startu, dane.godzina_startu, dane.pewna_data = (
                z_kontekstu.data_startu, z_kontekstu.godzina_startu, z_kontekstu.pewna_data)
        if not dane.kwoty:
            dane.kwoty = z_kontekstu.kwoty
        if dane.zapowiedz is None:
            dane.zapowiedz = z_kontekstu.zapowiedz
    return dane


def _dane_z(tekst: str, rok: int) -> DaneNaboru:
    numer, liczba = wyciagnij_numer(tekst)
    d, g, pewna = wyciagnij_start(tekst, rok)
    return DaneNaboru(
        numer=numer, numer_liczba=liczba, wojewodztwa=wyciagnij_wojewodztwa(tekst),
        data_startu=d, godzina_startu=g, pewna_data=pewna,
        kwoty=wyciagnij_kwoty(tekst), zapowiedz=wyciagnij_zapowiedz(tekst),
    )


def dopasowane_wzorce(tekst: str) -> list[str]:
    return [nazwa for nazwa, wzor in WZORCE_PILNE if wzor.search(tekst)]


# ---------------------------------------------------------------- klasyfikacja

# Ogłoszenie, którego start minął dawno temu, to informacja „po fakcie”
# (np. publikacja listy wniosków z dawnego naboru) – nie PILNE.
PROG_HISTORYCZNY = timedelta(hours=24)


@dataclass
class Klasyfikacja:
    poziom: str  # PILNE / INFO
    powod: str
    wzorce: list[str] = field(default_factory=list)
    dane: DaneNaboru | None = None
    start: datetime | None = None
    zmiana_terminu: bool = False
    poprzedni_start: datetime | None = None


def klasyfikuj(zmiana: Zmiana, teraz: datetime, strefa: ZoneInfo, godzina_gdy_brak: time) -> Klasyfikacja:
    """PILNE, gdy NOWY fragment treści pasuje do wzorców naboru; w pozostałych przypadkach INFO."""
    if zmiana.rodzaj != TEKST or not zmiana.nowe:
        return Klasyfikacja(INFO, "inna zmiana")
    wz_nowe = dopasowane_wzorce(zmiana.tekst_nowy)
    if not wz_nowe:
        return Klasyfikacja(INFO, "inna zmiana")

    rok = teraz.astimezone(strefa).year

    def start_wiarygodny(d: DaneNaboru) -> datetime | None:
        """Przeszła data BEZ kotwicy to raczej odwołanie do dawnego naboru niż start nowego."""
        s = d.start(strefa, godzina_gdy_brak)
        if s is not None and not d.pewna_data and s < teraz:
            d.data_startu, d.godzina_startu, d.pewna_data = None, None, True
            return None
        return s

    dane = wyciagnij_dane(zmiana.tekst_nowy, "\n".join(zmiana.kontekst), rok)
    start = start_wiarygodny(dane)

    # Zmiana istniejącej linii: PILNE tylko, gdy doszedł NOWY wzorzec albo zmieniły się
    # dane (termin/kwota). Dopisek „– NABÓR ZAMKNIĘTY” w starym nagłówku to INFO.
    zmiana_terminu, poprzedni_start = False, None
    if zmiana.stare:
        wz_stare = set(dopasowane_wzorce(zmiana.tekst_stary))
        nowe_wzorce = [w for w in wz_nowe if w not in wz_stare]
        dane_frag = wyciagnij_dane(zmiana.tekst_nowy, "", rok)
        dane_stare = wyciagnij_dane(zmiana.tekst_stary, "", rok)
        start_frag = start_wiarygodny(dane_frag)
        poprzedni_start = start_wiarygodny(dane_stare)
        termin_inny = start_frag is not None and start_frag != poprzedni_start
        kwota_inna = bool(dane_frag.kwoty) and dane_frag.kwoty != dane_stare.kwoty
        if not nowe_wzorce and not termin_inny and not kwota_inna:
            return Klasyfikacja(INFO, "zmiana w istniejącym ogłoszeniu", wz_nowe, dane, start)
        zmiana_terminu = termin_inny and poprzedni_start is not None

    if start is not None and start < teraz - PROG_HISTORYCZNY:
        return Klasyfikacja(INFO, "dotyczy naboru, który już się odbył", wz_nowe, dane, start)
    return Klasyfikacja(PILNE, "nowe ogłoszenie", wz_nowe, dane, start, zmiana_terminu, poprzedni_start)
