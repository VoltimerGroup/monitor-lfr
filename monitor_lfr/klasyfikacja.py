"""Klasyfikacja nowych fragmentów (PILNE / INFO) i wyciąganie danych naboru.

Wejściem są ZAWSZE znormalizowane linie (myślniki -> "-", NBSP -> spacja), więc
wzorce nie muszą znać wszystkich odmian myślników i spacji.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from .normalizacja import normalizuj
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
# Najpierw szablon LFR („od dnia X r. (od godz. Y)”), potem słowa o naborze, a dopiero
# potem ogólne „od dnia” / „w dniu”, które bywają też w zdaniach o czymś innym
# („Od dnia 1 października biuro ma nowy adres”).
_KOTWICE_STARTU: list[tuple[re.Pattern, bool]] = [
    (re.compile(r"\bod\s+dnia\s*" + _DATA + r"(?=[^()\n]{0,15}\(\s*od\s+godz)", _F), True),
    (re.compile(r"\brozpocz[ęe]ci[ea]\s+naboru\s*[-:]?\s*(?:w\s+dniu\s+|dnia\s+)?" + _DATA, _F), True),
    (re.compile(r"\brozpocznie\s+si[ęe]\s+(?:w\s+dniu\s+|dnia\s+)?" + _DATA, _F), True),
    (re.compile(r"\bod\s+dnia\s*" + _DATA, _F), True),
    (re.compile(r"(?:\bw\s+dniu|(?<![zZ] )\bdnia)\s+" + _DATA, _F), True),
    (re.compile(r"(?<![\d.])" + _DATA, _F), False),
]
_SAMA_DATA = _KOTWICE_STARTU[-1][0]

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

# Zapowiedź („planowany jest na maj 2026 r.”) – do kropki, nawiasu albo dopisku po myślniku
# („… na maj 2026 – termin ZMIENIONY …”), najwyżej 60 znaków.
_ZAPOWIEDZ = re.compile(
    r"\b(?:planowan[aey]\s+jest|jest\s+planowan[aey])\s+((?:(?!\s-\s)[^.\n(;]){1,60})", _F)

# Rdzenie nazw miesięcy bez ogonków – pasują do każdego przypadku („maj/maja/maju”, „styczeń/stycznia”).
_RDZENIE_MIESIECY = [
    ("stycz", 1), ("lut", 2), ("marz", 3), ("marc", 3), ("kwie", 4), ("maj", 5), ("czerw", 6),
    ("lip", 7), ("sierp", 8), ("wrze", 9), ("pazdziern", 10), ("listopad", 11), ("grud", 12),
]

# Ogłoszenie, którego start minął dawno temu, to informacja „po fakcie”
# (np. publikacja listy wniosków z dawnego naboru) – nie PILNE.
PROG_HISTORYCZNY = timedelta(hours=24)


@dataclass(frozen=True)
class Odniesienie:
    """Chwila sprawdzenia – do odróżniania dat przyszłych od przeszłych i do uzupełniania roku."""

    teraz: datetime
    strefa: ZoneInfo
    godzina_gdy_brak: time

    @property
    def dzis(self) -> date:
        return self.teraz.astimezone(self.strefa).date()

    def aktualna(self, d: date, g: time | None) -> bool:
        """Czy start (d, g) nie jest „po fakcie” (minął najwyżej PROG_HISTORYCZNY temu)."""
        return datetime.combine(d, g or self.godzina_gdy_brak, tzinfo=self.strefa) >= self.teraz - PROG_HISTORYCZNY


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
    """„Mazowieckim”, „Mazowieckie” -> „mazowieckie” (do porównań z konfiguracją).

    None, gdy w napisie nie ma województwa albo jest ich kilka („mazowieckie, lubelskie”).
    """
    w = _wojewodztwa_w(normalizuj(str(nazwa)))
    return w[0] if len(w) == 1 else None


def _rok_najblizszy(dzien: int, miesiac: int, dzis: date) -> int:
    """Rok dla daty bez roku: ten z (poprzedni, bieżący, następny), który daje datę najbliższą dziś.

    10.12.2026 „od dnia 15 stycznia” -> 15.01.2027 (a nie 15.01.2026 – prawie rok temu);
    23.10.2026 „w dniu 16 czerwca” -> 16.06.2026 (odwołanie do minionego naboru).
    """
    najlepszy, odleglosc = dzis.year, None
    for rok in (dzis.year - 1, dzis.year, dzis.year + 1):
        try:
            d = date(rok, miesiac, dzien)
        except ValueError:
            continue
        o = abs((d - dzis).days)
        if odleglosc is None or o < odleglosc or (o == odleglosc and d > dzis):
            najlepszy, odleglosc = rok, o
    return najlepszy


def _data_z_dopasowania(m: re.Match, rok_biezacy: int, odn: Odniesienie | None = None) -> date | None:
    g = m.groupdict()
    try:
        if g.get("d1"):
            miesiac, dzien = MIESIACE_DOPELNIACZ[g["mies"].lower()], int(g["d1"])
            if g.get("r1"):
                rok = int(g["r1"])
            elif g.get("br") or odn is None:
                rok = rok_biezacy  # „br.” = bieżący rok
            else:
                rok = _rok_najblizszy(dzien, miesiac, odn.dzis)
            return date(rok, miesiac, dzien)
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


@dataclass
class _Kandydat:
    data: date
    godzina: time | None
    pewna: bool
    poziom: int  # numer kotwicy w _KOTWICE_STARTU (0 = najpewniejsza)
    pozycja: int  # miejsce w tekście


def _kandydaci_startu(tekst: str, rok_biezacy: int, odn: Odniesienie | None) -> list[_Kandydat]:
    """Wszystkie daty z kotwicami (i bez) – fragment bywa pełen odwołań do dawnych naborów."""
    poczatki_dat = [m.start() for m in _SAMA_DATA.finditer(tekst)]
    wynik: list[_Kandydat] = []
    for poziom, (wzor, pewna) in enumerate(_KOTWICE_STARTU):
        for m in wzor.finditer(tekst):
            d = _data_z_dopasowania(m, rok_biezacy, odn)
            if d is None:
                continue
            # Godziny szukamy tylko do następnej daty – żeby nie „pożyczyć” godziny innego terminu.
            nastepna = min((p for p in poczatki_dat if p >= m.end()), default=len(tekst))
            za_data = tekst[m.end(): min(m.end() + 100, nastepna)]
            # Kolejność: „(od godz. 8:30)” tuż za datą -> „godz. 8:30” blisko daty -> „8:30” zaraz po dacie.
            g = (_OD_GODZ.search(za_data) or _GODZ_PO_DACIE.search(za_data[:40])
                 or _GODZ_TUZ_PO_DACIE.search(za_data))
            wynik.append(_Kandydat(d, _godzina(g.group(1), g.group(2)) if g else None, pewna, poziom, m.start()))
    # „od godz.” gdziekolwiek we fragmencie – tylko gdy fragment mówi o jednej dacie.
    if len({k.data for k in wynik}) == 1:
        g = _OD_GODZ.search(tekst)
        for k in wynik:
            if k.godzina is None and g:
                k.godzina = _godzina(g.group(1), g.group(2))
    return wynik


def _wybierz_start(kandydaci: list[_Kandydat], odn: Odniesienie | None) -> _Kandydat | None:
    """Data startu spośród kandydatów.

    Z odniesieniem („teraz”): liczą się daty jeszcze aktualne – z najpewniejszej kotwicy,
    a w jej obrębie najbliższa. Data bez kotwicy wygrywa tylko wtedy, gdy żadna data
    z kotwicą nie jest aktualna. Gdy aktualnych brak (albo nie ma odniesienia): pierwsza
    data najpewniejszej kotwicy – klasyfikacja uzna ją za nabór, który już się odbył.
    """
    if not kandydaci:
        return None
    if odn is not None:
        aktualne = [k for k in kandydaci if odn.aktualna(k.data, k.godzina)]
        pula = [k for k in aktualne if k.pewna] or aktualne
        if pula:
            poziom = min(k.poziom for k in pula)
            return min((k for k in pula if k.poziom == poziom),
                       key=lambda k: (k.data, k.godzina or odn.godzina_gdy_brak, k.pozycja))
    poziom = min(k.poziom for k in kandydaci)
    return min((k for k in kandydaci if k.poziom == poziom), key=lambda k: k.pozycja)


def wyciagnij_start(tekst: str, rok_biezacy: int,
                    odn: Odniesienie | None = None) -> tuple[date | None, time | None, bool]:
    """(data startu, godzina startu, czy data pewna)."""
    k = _wybierz_start(_kandydaci_startu(tekst, rok_biezacy, odn), odn)
    return (k.data, k.godzina, k.pewna) if k else (None, None, True)


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


def _bez_ogonkow(tekst: str) -> str:
    t = unicodedata.normalize("NFKD", tekst.replace("ł", "l").replace("Ł", "L"))
    return "".join(z for z in t if not unicodedata.combining(z)).casefold()


def klucz_zapowiedzi(zapowiedz: str | None) -> str | None:
    """Klucz do porównania dwóch zapowiedzi: bez ogonków, wielkości liter, interpunkcji i „r.”."""
    if zapowiedz is None:
        return None
    slowa = re.findall(r"\w+", _bez_ogonkow(zapowiedz))
    while slowa and slowa[-1] in ("r", "roku", "br"):
        slowa.pop()
    return " ".join(slowa)


def zapowiedz_aktualna(zapowiedz: str, odn: Odniesienie) -> bool:
    """False tylko wtedy, gdy zapowiedź wyraźnie wskazuje termin, który już minął.

    Dokładna data -> próg PROG_HISTORYCZNY; miesiąc z rokiem -> czy miesiąc minął;
    sam rok -> czy rok minął. Bez roku (np. „na wiosnę”) -> aktualna (lepiej powiadomić).
    """
    for m in _SAMA_DATA.finditer(zapowiedz):
        d = _data_z_dopasowania(m, odn.dzis.year, odn)
        if d is not None:
            return odn.aktualna(d, None)
    slowa = re.findall(r"\w+", _bez_ogonkow(zapowiedz))
    lata = {int(s) for s in slowa if re.fullmatch(r"20\d\d", s)}
    if not lata:
        return True
    miesiace = [nr for s in slowa for rdzen, nr in _RDZENIE_MIESIECY if s.startswith(rdzen)]
    dzis = odn.dzis
    if len(lata) == 1 and miesiace:
        return (max(lata), max(miesiace)) >= (dzis.year, dzis.month)
    return max(lata) >= dzis.year


def wyciagnij_dane(tekst: str, kontekst: str = "", rok_biezacy: int | None = None,
                   odn: Odniesienie | None = None) -> DaneNaboru:
    """Dane z fragmentu; brakujące pola uzupełniane z kontekstu (sekcji ogłoszenia).

    Z odniesieniem (`odn`) data startu to najbliższa aktualna data z kotwicą, a data bez
    roku dostaje rok najbliższy dziś (ogłoszenie z grudnia o „15 stycznia” = następny rok).
    """
    rok = rok_biezacy or (odn.dzis.year if odn else date.today().year)
    dane = _dane_z(tekst, rok, odn)
    if kontekst and kontekst != tekst:
        z_kontekstu = _dane_z(kontekst, rok, odn)
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


def _dane_z(tekst: str, rok: int, odn: Odniesienie | None = None) -> DaneNaboru:
    numer, liczba = wyciagnij_numer(tekst)
    d, g, pewna = wyciagnij_start(tekst, rok, odn)
    return DaneNaboru(
        numer=numer, numer_liczba=liczba, wojewodztwa=wyciagnij_wojewodztwa(tekst),
        data_startu=d, godzina_startu=g, pewna_data=pewna,
        kwoty=wyciagnij_kwoty(tekst), zapowiedz=wyciagnij_zapowiedz(tekst),
    )


def dopasowane_wzorce(tekst: str) -> list[str]:
    return [nazwa for nazwa, wzor in WZORCE_PILNE if wzor.search(tekst)]


# ---------------------------------------------------------------- klasyfikacja

@dataclass
class Klasyfikacja:
    poziom: str  # PILNE / INFO
    powod: str
    wzorce: list[str] = field(default_factory=list)
    dane: DaneNaboru | None = None
    start: datetime | None = None
    zmiana_terminu: bool = False
    poprzedni_start: datetime | None = None
    poprzednia_zapowiedz: str | None = None  # gdy zmienił się planowany termin („na maj” -> „na czerwiec”)


def klasyfikuj(zmiana: Zmiana, teraz: datetime, strefa: ZoneInfo, godzina_gdy_brak: time) -> Klasyfikacja:
    """PILNE, gdy NOWY fragment treści pasuje do wzorców naboru; w pozostałych przypadkach INFO."""
    if zmiana.rodzaj != TEKST or not zmiana.nowe:
        return Klasyfikacja(INFO, "inna zmiana")
    wz_nowe = dopasowane_wzorce(zmiana.tekst_nowy)
    if not wz_nowe:
        return Klasyfikacja(INFO, "inna zmiana")

    odn = Odniesienie(teraz, strefa, godzina_gdy_brak)
    rok = odn.dzis.year

    def start_wiarygodny(d: DaneNaboru) -> datetime | None:
        """Przeszła data BEZ kotwicy to raczej odwołanie do dawnego naboru niż start nowego."""
        s = d.start(strefa, godzina_gdy_brak)
        if s is not None and not d.pewna_data and s < teraz:
            d.data_startu, d.godzina_startu, d.pewna_data = None, None, True
            return None
        return s

    dane = wyciagnij_dane(zmiana.tekst_nowy, "\n".join(zmiana.kontekst), rok, odn)
    start = start_wiarygodny(dane)
    # Zapowiedź bierzemy tylko z NOWEGO fragmentu – stara zapowiedź z sekcji nie jest nowiną.
    zapowiedz = wyciagnij_zapowiedz(zmiana.tekst_nowy)
    zapowiedz_akt = zapowiedz is not None and zapowiedz_aktualna(zapowiedz, odn)

    # Zmiana istniejącej linii: PILNE tylko, gdy doszedł NOWY wzorzec albo zmieniły się dane
    # (termin, kwota, planowany termin). Dopisek „– NABÓR ZAMKNIĘTY” w starym nagłówku to INFO.
    zmiana_terminu, poprzedni_start, poprzednia_zapowiedz = False, None, None
    if zmiana.stare:
        wz_stare = set(dopasowane_wzorce(zmiana.tekst_stary))
        nowe_wzorce = [w for w in wz_nowe if w not in wz_stare]
        dane_frag = wyciagnij_dane(zmiana.tekst_nowy, "", rok, odn)
        dane_stare = wyciagnij_dane(zmiana.tekst_stary, "", rok, odn)
        start_frag = start_wiarygodny(dane_frag)
        poprzedni_start = start_wiarygodny(dane_stare)
        termin_inny = start_frag is not None and start_frag != poprzedni_start
        kwota_inna = bool(dane_frag.kwoty) and dane_frag.kwoty != dane_stare.kwoty
        zapowiedz_inna = zapowiedz_akt and klucz_zapowiedzi(zapowiedz) != klucz_zapowiedzi(dane_stare.zapowiedz)
        if not nowe_wzorce and not termin_inny and not kwota_inna and not zapowiedz_inna:
            return Klasyfikacja(INFO, "zmiana w istniejącym ogłoszeniu", wz_nowe, dane, start)
        zmiana_terminu = termin_inny and poprzedni_start is not None
        if zapowiedz_inna and dane_stare.zapowiedz is not None:
            poprzednia_zapowiedz = dane_stare.zapowiedz

    if start is not None and start < teraz - PROG_HISTORYCZNY:
        if not zapowiedz_akt:
            return Klasyfikacja(INFO, "dotyczy naboru, który już się odbył", wz_nowe, dane, start)
        # Fragment wspomina miniony nabór, ale zapowiada kolejny – PILNE bez daty startu
        # (data z fragmentu dotyczy minionego naboru, a nie zapowiadanego).
        dane.data_startu, dane.godzina_startu, dane.pewna_data = None, None, True
        dane.zapowiedz = zapowiedz
        start, zmiana_terminu = None, False
    return Klasyfikacja(PILNE, "nowe ogłoszenie", wz_nowe, dane, start, zmiana_terminu, poprzedni_start,
                        poprzednia_zapowiedz)
