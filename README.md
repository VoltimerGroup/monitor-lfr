# Monitor LFR – „Pierwszy biznes – Wsparcie w starcie”

Monitor strony Lubelskiej Fundacji Rozwoju z naborami pożyczek
„Pierwszy biznes – Wsparcie w starcie”:
<https://www.lfr.lublin.pl/projekty/pierwszy-biznes-wsparcie-w-starcie-2025/>

Co 10 minut (GitHub Actions) pobiera stronę, porównuje ją z poprzednią wersją i wysyła
powiadomienie na Telegram:

- **[PILNE] NOWY NABÓR – Pierwszy biznes (LFR)** – gdy pojawi się ogłoszenie naboru
  (numer naboru, województwa z wyraźnym oznaczeniem „dotyczy Twoich województw”, data
  i godzina startu, pula, fragment ogłoszenia, link, checklista),
- **przypomnienia** 3 dni, 1 dzień i 1 godzinę przed startem naboru,
- **[INFO]** – każda inna zmiana (komunikat, lista wniosków, nowy plik w „Dokumenty do pobrania”),
- **[AWARIA] / [OK]** – gdy strony nie da się odczytać 3 razy z rzędu i gdy znowu działa,
- **[HEARTBEAT]** – raz dziennie po 9:00 (czas polski): „monitor działa, ostatnie sprawdzenie: …”.

> **Monitor TYLKO powiadamia.** Nigdy nie wysyła wniosków ani maili do fundacji. Wniosek
> składasz samodzielnie.

---

## Spis treści

1. [Jak to działa](#jak-to-działa)
2. [Uruchomienie lokalne](#uruchomienie-lokalne)
3. [Bot Telegram krok po kroku](#bot-telegram-krok-po-kroku)
4. [Uruchomienie w GitHub Actions](#uruchomienie-w-github-actions)
5. [Testowy alert z Actions](#testowy-alert-z-actions)
6. [Konfiguracja](#konfiguracja)
7. [Jak sprawdzić, że działa](#jak-sprawdzić-że-działa)
8. [Jak zatrzymać](#jak-zatrzymać)
9. [Ograniczenia – uczciwie](#ograniczenia--uczciwie)
10. [Testy](#testy)
11. [Struktura plików](#struktura-plików)

---

## Jak to działa

```
cron GitHub (co 10 min, UTC)
  └─ python -m monitor_lfr
       1. pobierz stronę (timeout 30 s, 3 ponowienia z backoffem 5/10/20 s, User-Agent przeglądarki)
       2. wyciągnij TYLKO główną treść artykułu + listę plików z „Dokumenty do pobrania”
       3. znormalizuj (białe znaki, NBSP, myślniki, cudzysłowy) -> zero fałszywych alarmów
       4. porównaj z poprzednią wersją z state/stan.json (pierwszy przebieg = wersja bazowa, bez alertu)
       5. przeanalizuj TYLKO nowe fragmenty: PILNE (ogłoszenie naboru) albo INFO (reszta)
       6. wyślij na Telegram (każdy alert tylko raz – deduplikacja po skrócie fragmentu)
       7. wyślij zaległe przypomnienia, heartbeat, alert awarii / powrotu
       8. zapisz stan; workflow robi commit state/stan.json, gdy się zmienił
```

### Skąd monitor wie, co jest treścią

Struktura strony (ustalona na kopii z 23.10.2026 – `tests/fixtures/strona_2026-10-23.html`):

| Element | Selektor CSS | Co z nim robimy |
|---|---|---|
| Główna treść (ogłoszenia, najnowsze na górze) | `div.institution.entry > div.area > div.text` | monitorujemy linia po linii |
| Zakładka „Formy wsparcia” | `#formy-wsparcia` (wewnątrz treści) | monitorujemy jak treść |
| Zakładka „Dokumenty do pobrania” | `#dokumenty-do-pobrania`, pozycje `.p-files` | monitorujemy listę plików (nowy plik = INFO) |
| Przyciski zakładek | `.area-bottom-button` | pomijamy |
| Menu, stopka, baner newslettera/cookies, skrypty | poza kontenerem | pomijamy |

Treść jest w zwykłym HTML (bez JavaScriptu) – sprawdzone 23.10.2026, więc Playwright nie jest
potrzebny. Każdy przebieg i tak to weryfikuje: jeśli w treści zabraknie frazy „Pierwszy Biznes”
albo kontenera, przebieg liczy się jako nieudany (po 3 takich – alert awarii z podpowiedzią,
czy to zmiana układu strony, czy treść ładowana JavaScriptem / blokada).

### Kiedy PILNE, a kiedy INFO

Nowy fragment jest **PILNY**, gdy pasuje do któregoś wzorca (bez względu na wielkość liter,
z polskimi znakami lub bez, z dowolnym myślnikiem):
„przyjmować będzie wnioski”, „NABÓR WNIOSKÓW”, „od dnia … (od godz.”, „kwota do dyspozycji”,
„planowany jest”, „Rozpoczęcie naboru” (oraz „nabór rozpocznie się”).

Żeby nie było fałszywych PILNYCH, dwa wyjątki dają **INFO**:

- zmiana **istniejącej** linii, w której nie doszedł żaden nowy wzorzec ani nie zmienił się
  termin, kwota ani planowany termin z zapowiedzi – np. dopisek „– NABÓR ZAMKNIĘTY”
  w nagłówku starego naboru;
- ogłoszenie, którego **start był ponad 24 godziny temu** i które nie zapowiada kolejnego
  naboru – np. publikacja listy wniosków z naboru, który już się odbył.

Zmiana terminu w ogłoszeniu daje PILNE z dopiskiem „UWAGA: ZMIANA TERMINU”, a stare
przypomnienia są anulowane. Zmiana miesiąca w zapowiedzi („planowany jest na maj” → „na
czerwiec”) daje PILNE z dopiskiem „UWAGA: ZMIANA PLANOWANEGO TERMINU”.

Z PILNEGO fragmentu monitor wyciąga: numer naboru (rzymski lub arabski), województwa,
datę startu („15 stycznia 2027 r.”, „15.01.2027”, „2027-01-15”, „16 czerwca br.”), godzinę
(„8:30”, „8.30”), pulę („2 000 000,00 zł”, kilka pul = suma). Gdy czegoś brakuje w samym
fragmencie, dopełnia to z początku tej samej sekcji ogłoszenia (między liniami „………”).
Gdy godziny nie podano, do przypomnień przyjmuje 8:00 i pisze to wprost w alercie.

Jak monitor wybiera datę startu, gdy we fragmencie jest kilka dat (np. „w związku
z zakończeniem naboru z dnia 29.09.2026 r. … kolejny nabór od dnia 15 stycznia 2027 r.”):
liczą się tylko daty **przyszłe** (albo sprzed najwyżej doby). Spośród nich wygrywa data przy
najpewniejszym sformułowaniu: najpierw szablon LFR „od dnia X r. (od godz. Y)”, potem
„Rozpoczęcie naboru”, „nabór rozpocznie się”, „od dnia”, „w dniu”, a na końcu sama data.
Przy tym samym sformułowaniu – najbliższa. Data bez roku dostaje rok, przy którym wypada
najbliżej dzisiejszego dnia (w grudniu „15 stycznia” = styczeń następnego roku);
„br.” to zawsze bieżący rok.

---

## Uruchomienie lokalne

Wymagany Python 3.11+ (testowane na 3.12). W PowerShellu:

```powershell
cd C:\Users\karol\Desktop\monitor-lfr
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements-dev.txt

python -m pytest -q                    # testy (bez sieci, bez Telegrama)
python -m monitor_lfr --dry-run        # żywa strona, wiadomości tylko drukowane
```

Opcje:

| Opcja | Działanie |
|---|---|
| `--dry-run` | nic nie wysyła, drukuje wiadomości; **stan zapisuje jak zwykły przebieg** |
| `--test-alert` | wysyła przykładowy alert PILNY (sprawdzenie dostarczenia na telefon); stanu nie zmienia |
| `--plik strona.html` | czyta stronę z pliku zamiast z sieci |
| `--stan-dir KATALOG` | inny katalog stanu (np. do eksperymentów, żeby nie ruszać `state/`) |
| `--config plik.json` | inny plik konfiguracji |

Wysyłka na Telegram lokalnie (sekrety tylko w zmiennych środowiskowych, nigdy w plikach):

```powershell
$env:TELEGRAM_BOT_TOKEN = "123456789:AA...twój-token"
$env:TELEGRAM_CHAT_ID   = "123456789"
python -m monitor_lfr --test-alert
```

> Uwaga: `state/stan.json` jest wspólny z botem w GitHub. Do eksperymentów lokalnych używaj
> `--stan-dir C:\Temp\stan-lfr`, a przed commitem czegokolwiek zrób `git pull`.

Kody wyjścia: `0` – OK, `1` – nie udało się wysłać powiadomienia (albo brak sekretów),
`2` – błąd konfiguracji/stanu/pliku wejściowego.

---

## Bot Telegram krok po kroku

1. W Telegramie wyszukaj **@BotFather** (z niebieskim znaczkiem weryfikacji) i otwórz czat.
2. Wyślij `/newbot`.
3. Podaj nazwę bota, np. `Monitor LFR`.
4. Podaj nazwę użytkownika bota – musi kończyć się na `bot`, np. `monitor_lfr_karol_bot`.
5. BotFather odpisze **tokenem** w postaci `123456789:AAH...`. To jest `TELEGRAM_BOT_TOKEN`.
   Traktuj go jak hasło – nie wklejaj go nigdzie publicznie.
6. Otwórz czat ze swoim botem (link `t.me/<nazwa_bota>` z wiadomości BotFathera),
   naciśnij **Start** i wyślij dowolną wiadomość, np. `cześć`.
7. W przeglądarce otwórz (wstaw swój token):
   `https://api.telegram.org/bot<TOKEN>/getUpdates`
8. W odpowiedzi znajdź `"chat":{"id":123456789,...}` – ta liczba to `TELEGRAM_CHAT_ID`.
   - Jeśli widzisz `"result":[]`, wyślij botowi kolejną wiadomość i odśwież stronę.
   - Dla grupy: dodaj bota do grupy, napisz coś w grupie, odśwież – id grupy jest ujemne
     (np. `-1001234567890`).
9. Zamknij kartę z adresem zawierającym token.

---

## Uruchomienie w GitHub Actions

Repozytorium jest **publiczne** (w publicznych repozytoriach minuty Actions są bezpłatne).

1. Utwórz repozytorium i wypchnij kod (gałąź `main`).
2. Dodaj sekrety: **Settings → Secrets and variables → Actions → New repository secret**
   - Name: `TELEGRAM_BOT_TOKEN`, Secret: token od BotFathera → **Add secret**
   - Name: `TELEGRAM_CHAT_ID`, Secret: liczba z `getUpdates` → **Add secret**
3. Wejdź w zakładkę **Actions** i – jeśli GitHub o to poprosi – włącz workflowy.
4. Jeśli commit stanu kończy się błędem 403: **Settings → Actions → General → Workflow
   permissions → Read and write permissions → Save** (workflow i tak prosi tylko
   o `contents: write`).
5. Wyślij testowy alert (następna sekcja) – sprawdź, czy dochodzi na telefon.

Co robi workflow `.github/workflows/monitor.yml`:

- cron `2-59/10 * * * *` – co 10 minut (minuty :02, :12, …, :52),
- `concurrency` – przebiegi nie nakładają się, trwający nie jest anulowany,
- `actions/checkout` z `ref: ${{ github.ref_name }}` – przebieg, który czekał w kolejce,
  pobiera **czubek gałęzi** (ze stanem zapisanym przed chwilą przez poprzedni przebieg), a nie
  commit z chwili wywołania – inaczej czytałby stary `stan.json` i wysłał te same alerty drugi
  raz. Dlatego „Run workflow” w trakcie przebiegu z crona jest bezpieczne,
- `actions/setup-python` z cache pip,
- uruchomienie `python -m monitor_lfr` z sekretami w zmiennych środowiskowych,
- **commit `state/stan.json` tylko, gdy się zmienił** (tożsamość bota `github-actions[bot]`).
  Jeśli ktoś w międzyczasie wypchnął commit, krok robi rebase na czubek gałęzi (przy konflikcie
  w plikach stanu wygrywa wersja z tego przebiegu – ona pamięta wysłane przed chwilą alerty),
  a nieudany rebase przerywa (`git rebase --abort`) przed kolejną z 3 prób.
  Stan zmienia się przy zdarzeniach (nowa wersja strony, alert, przypomnienie, błędy,
  heartbeat) oraz **raz na dobę** (pole `znacznik_zycia`) – ten codzienny commit sprawia,
  że GitHub nie wyłączy harmonogramu po 60 dniach bez aktywności w repozytorium,
- dziennik `state/log.jsonl` dostaje wpis w każdym przebiegu; między commitami przenosi go
  cache Actions, a do repozytorium trafia razem z każdym commitem stanu (co najmniej raz dziennie).

Drugi workflow, `testy.yml`, uruchamia `pytest` po każdej zmianie kodu (commity bota go nie
uruchamiają).

> Repozytorium jest publiczne, więc publiczne są też `state/stan.json` i `state/log.jsonl`.
> Zawierają wyłącznie treść publicznej strony LFR, czasy sprawdzeń i opisy wysłanych alertów –
> **nie** zawierają tokenu ani `chat_id`. Logi Actions też są publiczne; GitHub maskuje sekrety,
> a monitor dodatkowo nigdy nie wypisuje tokenu (także w komunikatach błędów).

---

## Testowy alert z Actions

**Actions → Monitor LFR → Run workflow** → zaznacz
„Wyślij TYLKO testowy alert PILNY…” → **Run workflow**.

Na telefon przyjdzie alert PILNY z fikcyjnym IV naborem (start za 14 dni) poprzedzony
nagłówkiem „TO JEST WIADOMOŚĆ TESTOWA”. Stan monitora się nie zmienia.
Bez zaznaczenia pola „Run workflow” wykonuje zwykłe sprawdzenie strony od razu.

---

## Konfiguracja

Plik `config.json` (sekretów NIE wpisuj tutaj):

| Pole | Domyślnie | Znaczenie |
|---|---|---|
| `url` | strona naboru | adres monitorowanej strony |
| `moje_wojewodztwa` | `["mazowieckie", "lubelskie"]` | „Twoje” województwa – alert oznacza, czy nabór ich dotyczy |
| `strefa_czasowa` | `Europe/Warsaw` | strefa dla dat, heartbeatu i przypomnień |
| `kanal` | `telegram` | kanał powiadomień (`telegram` albo `konsola`) |
| `heartbeat.wlaczony` / `heartbeat.godzina` | `true` / `9` | heartbeat raz dziennie w pierwszym przebiegu po tej godzinie |
| `przypomnienia.przed_startem` | `["3d", "1d", "1h"]` | wyprzedzenia przypomnień (`d` dni, `h` godziny, `m` minuty) |
| `przypomnienia.tylko_moje_wojewodztwa` | `true` | nie planuj przypomnień dla naborów spoza Twoich województw |
| `przypomnienia.godzina_startu_gdy_brak` | `08:00` | godzina przyjmowana, gdy ogłoszenie podaje tylko datę |
| `awaria.kolejne_bledy_do_alertu` | `3` | po ilu nieudanych przebiegach z rzędu wysłać alert awarii |
| `pobieranie.timeout_s` / `ponowienia` / `backoff_s` | `30` / `3` / `5` | timeout żądania, liczba ponowień, pierwszy odstęp (potem ×2) |
| `ekstrakcja.selektory_tresci` | patrz plik | selektory CSS kontenera treści (próbowane po kolei) |
| `ekstrakcja.selektor_dokumentow` | `#dokumenty-do-pobrania` | sekcja z plikami |
| `ekstrakcja.oczekiwane_frazy` | `["Pierwszy Biznes"]` | frazy, które muszą być w treści (inaczej: błąd odczytu) |
| `log.max_wpisow` | `2000` | ile ostatnich wpisów trzyma `state/log.jsonl` |

**Zmiana województw:** popraw `moje_wojewodztwa`, np. `["mazowieckie"]`. Można pisać w dowolnej
odmianie i wielkości liter („Mazowieckie”, „mazowieckim”) – monitor sprowadza nazwy do postaci
kanonicznej. Jedna pozycja = jedno województwo. Nazwa, której monitor nie rozpozna (np.
„Mazury”), albo dwa województwa w jednej pozycji to **błąd konfiguracji**: przebieg kończy się
na czerwono z komunikatem „BŁĄD KONFIGURACJI: moje_wojewodztwa: nie rozpoznano…” – zamiast
po cichu oznaczać nabory jako „NIE dotyczy Twoich województw” i nie planować przypomnień.

**Zmiana częstotliwości:** w `.github/workflows/monitor.yml` zmień linię `cron`. Przykłady:

| Cel | Wpis |
|---|---|
| co 10 minut (obecnie) | `2-59/10 * * * *` |
| co 5 minut (minimum, na które pozwala GitHub) | `*/5 * * * *` |
| co 15 minut | `2-59/15 * * * *` |

Cron w GitHub Actions jest **zawsze w UTC**. Przy „co N minut” to bez znaczenia. Jeśli chcesz
ograniczyć godziny, przelicz: czas polski zimą = UTC+1, latem = UTC+2. Np. „od 6:00 do 22:00
czasu polskiego przez cały rok” to godziny UTC 4–21: `2-59/10 4-21 * * *`. Nie polecamy
ograniczania – przypomnienia i heartbeat wychodzą tylko wtedy, gdy monitor działa.

**Zmiana kanału:** `"kanal": "konsola"` – tylko wypisuje (jak `--dry-run`). Inny kanał (np. e-mail,
ntfy) dodaje się jako klasę z metodą `wyslij(tekst)` w `monitor_lfr/kanaly.py` i wpis
w `kanal_z_srodowiska()`; sekrety nowego kanału też wyłącznie w zmiennych środowiskowych.

---

## Jak sprawdzić, że działa

1. **Actions → Monitor LFR** – co ~10 minut nowy przebieg z zielonym znaczkiem. W logu kroku
   „Sprawdź stronę LFR” jest linia w rodzaju:
   `2026-10-23 21:12:04 (Europe/Warsaw) | HTTP 200 | zmiana: nie | wynik: ok | wysłano: 0`
2. **Heartbeat** – codziennie po 9:00 przychodzi „[HEARTBEAT] Monitor LFR działa…”.
   Brak heartbeatu = coś jest nie tak (wyłączony workflow, brak sekretów, awaria Telegrama).
3. **`state/log.jsonl`** – ostatnie 2000 sprawdzeń (czas, status HTTP, czy była zmiana, wynik).
4. **`state/stan.json`** – zapamiętana wersja strony, wysłane alerty, zaplanowane przypomnienia
   (`przypomnienia[].status`: `oczekuje`, `wyslane`, `pominiete`, `anulowane`, `przeterminowane`).
5. Czerwony przebieg = nie udało się wysłać powiadomienia (np. zły token, brak sekretów). GitHub
   może wtedy wysłać e-mail – włącz to w ustawieniach konta: **Settings → Notifications → Actions**
   (powiadomienia tylko o nieudanych workflowach).

---

## Jak zatrzymać

- **Actions → Monitor LFR → „…” (prawy górny róg) → Disable workflow.** Ponowne włączenie:
  ten sam przycisk – **Enable workflow**.
- Na stałe: usuń sekcję `schedule` z `.github/workflows/monitor.yml` albo cały plik.

---

## Ograniczenia – uczciwie

- **Cron GitHub się spóźnia.** Zaplanowane przebiegi startują z opóźnieniem kilku minut,
  w godzinach szczytu kilkunastu, a czasem GitHub pomija przebieg. Ostatni nabór zamknął się
  **po 50 minutach**, więc monitor **nie jest** narzędziem do „łapania” momentu startu. Liczy się
  przede wszystkim **alert o ogłoszeniu** (LFR publikuje je zwykle z wyprzedzeniem dni lub tygodni)
  i **przypomnienia**. Przypomnienie „1 godzinę przed” może dojść z opóźnieniem crona – po alercie
  PILNYM ustaw sobie budzik w telefonie.
- **Spóźnione przypomnienie wychodzi raz** z informacją, ile zostało do startu; jeśli zaległych
  jest kilka naraz, wychodzi tylko najświeższe. Po starcie (do 2 godzin) przychodzi
  „NABÓR JUŻ TRWA”, później przypomnienia przepadają.
- **Heurystyka.** Klasyfikacja i odczyt dat opierają się na wzorcach z dotychczasowych ogłoszeń LFR.
  Nietypowo napisane ogłoszenie może dać tylko INFO albo PILNE bez daty (alert mówi wtedy wprost
  „nie odczytano daty – sprawdź”). Dlatego INFO też warto czytać.
- **Tylko ta jedna strona.** Ogłoszenia opublikowane gdzie indziej (inna podstrona, Facebook,
  mail) nie zostaną wykryte. Jeśli strona serwuje wersję z pamięci podręcznej, zmiana może być
  widoczna z opóźnieniem.
- **Zmiana układu strony** (nowy szablon) zatrzyma odczyt – dostaniesz alert awarii po 3 przebiegach
  (~30 min). Trzeba wtedy poprawić selektory w `config.json`.
- **Zależność od Telegrama i GitHuba.** Gdy któryś nie działa, powiadomienie nie dojdzie;
  nieudana wysyłka jest ponawiana w kolejnych przebiegach (wersja bazowa nie jest przesuwana,
  dopóki alert nie dojdzie), a przebieg kończy się na czerwono.
- **Checklista w alercie to przypomnienie, nie porada prawna** – wiążący jest regulamin LFR.

---

## Testy

```powershell
python -m pytest -q
```

Testy działają bez sieci i bez Telegrama (kanał zastąpiony atrapą). Każdy przebieg w teście
tworzy nowy monitor czytający stan z dysku – jak restart w Actions. Pokrywają m.in.:

| Wymaganie | Test |
|---|---|
| (a) kopia strony z 23.10.2026 | `tests/fixtures/strona_2026-10-23.html` |
| (b) fikcyjny IV nabór → PILNE z datą 15.01.2027, 8:30, pulą, „dotyczy Twoich województw”, 3 przypomnienia | `test_b_*` |
| (c) obecna strona (nabory I–III) po bazie → brak alertów | `test_c_*` |
| (d) brak duplikatów (także po „restarcie” i przy migającej stronie) | `test_d_*` |
| (e) zmiana HTML / brak odpowiedzi → alert awarii po 3 próbach, potem „znowu działa” | `test_e_*` |
| (f) nowy plik w „Dokumenty do pobrania” → INFO | `test_f_*` |
| (g) heartbeat raz na dobę po 9:00 czasu polskiego | `test_g_*` |
| (h) spóźnione przypomnienie wychodzi raz | `test_h_*` |
| (i) zmiana samych białych znaków/myślników → brak alertu | `test_i_*` |
| województwa z `config.json` w dowolnej odmianie; nierozpoznane = błąd konfiguracji | `tests/test_konfiguracja.py` |
| przeszła data obok przyszłej, data bez roku w grudniu, zmiana zapowiedzi | `tests/test_klasyfikacja.py` (sekcja „poprawki po recenzji”) |
| workflow: checkout czubka gałęzi, commit stanu po równoległym commicie (prawdziwy git) | `tests/test_workflow.py` |

Aktualizacja kopii strony: pobierz stronę do nowego pliku w `tests/fixtures/` i podmień nazwę
w `tests/conftest.py` (`PLIK_STRONY`).

---

## Struktura plików

```
monitor-lfr/
├── .github/workflows/
│   ├── monitor.yml          # cron co 10 min, test-alert, commit stanu
│   └── testy.yml            # pytest po zmianie kodu
├── monitor_lfr/
│   ├── __main__.py          # python -m monitor_lfr
│   ├── cli.py               # opcje --dry-run, --test-alert, --plik, --stan-dir, --config
│   ├── konfiguracja.py      # config.json + wartości domyślne
│   ├── pobieranie.py        # HTTP: timeout, ponowienia, backoff, User-Agent
│   ├── ekstrakcja.py        # główna treść, pliki, odnośniki (selektory)
│   ├── normalizacja.py      # białe znaki, NBSP, myślniki, cudzysłowy, klucze porównań
│   ├── porownanie.py        # diff wersji – tylko nowe fragmenty
│   ├── klasyfikacja.py      # PILNE/INFO, numer, województwa, data, godzina, pula
│   ├── wiadomosci.py        # treść alertów, przypomnień, heartbeatu
│   ├── kanaly.py            # Telegram, konsola
│   ├── stan.py              # state/stan.json, state/log.jsonl
│   └── monitor.py           # jeden przebieg: awarie, deduplikacja, przypomnienia, heartbeat
├── state/
│   ├── stan.json            # stan (commitowany przez bota)
│   └── log.jsonl            # ostatnie sprawdzenia
├── tests/                   # pytest + tests/fixtures/strona_2026-10-23.html
├── config.json
├── requirements.txt         # zależności (wersje przypięte)
├── requirements-dev.txt     # + pytest
└── pytest.ini
```
