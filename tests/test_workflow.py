"""Workflow monitor.yml (poprawka po recenzji 23.10.2026).

Wada: przebieg czekający w kolejce concurrency pobierał github.sha sprzed commitu stanu
poprzedniego przebiegu – czytał stary stan.json (duplikaty alertów), a commit stanu kończył
się konfliktem, którego pętla ponowień nie mogła naprawić (rebase zostawał „w trakcie”).

Testy uruchamiają PRAWDZIWY skrypt kroku „Commit stanu” (wycięty z monitor.yml) na lokalnych
repozytoriach git – bez sieci i bez GitHuba.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from conftest import KATALOG_REPO

WORKFLOW = KATALOG_REPO / ".github" / "workflows" / "monitor.yml"
BASH = shutil.which("bash")
GIT = shutil.which("git")
# Na Windowsie „bash” z System32 to WSL – nie widzi ścieżek Windows; potrzebny Git Bash.
BRAK_NARZEDZI = not BASH or not GIT or "system32" in BASH.lower()


def _wciecie(linia: str) -> int:
    return len(linia) - len(linia.lstrip())


def _krok(nazwa: str) -> list[str]:
    """Linie kroku „- name: <nazwa…>” aż do następnego kroku."""
    linie = WORKFLOW.read_text(encoding="utf-8").splitlines()
    start = next(i for i, l in enumerate(linie) if l.strip().startswith(f"- name: {nazwa}"))
    koniec = next((i for i in range(start + 1, len(linie))
                   if linie[i].strip().startswith("- ") and _wciecie(linie[i]) == _wciecie(linie[start])),
                  len(linie))
    return linie[start:koniec]


def _skrypt_commitu() -> str:
    linie = _krok("Commit stanu")
    i = next(i for i, l in enumerate(linie) if l.strip() == "run: |")
    wciecie = _wciecie(linie[i + 1])
    blok = []
    for linia in linie[i + 1:]:
        if linia.strip() and _wciecie(linia) < wciecie:
            break
        blok.append(linia[wciecie:])
    return "\n".join(blok).rstrip() + "\n"


def test_checkout_bierze_czubek_galezi_a_nie_github_sha():
    krok = "\n".join(_krok("Pobierz repozytorium"))
    assert "actions/checkout@" in krok
    assert re.search(r"^\s+ref:\s*\$\{\{\s*github\.ref_name\s*\}\}\s*$", krok, re.M), krok


def test_concurrency_bez_anulowania_trwajacego():
    tekst = WORKFLOW.read_text(encoding="utf-8")
    assert re.search(r"^concurrency:\n\s+group: monitor-lfr\n\s+cancel-in-progress: false$", tekst, re.M)


# ------------------------------------------------------------------ prawdziwy git

def _posix(p: Path) -> str:
    return str(p).replace("\\", "/")


@pytest.fixture
def git_env(tmp_path: Path) -> dict:
    """Środowisko git odcięte od globalnej konfiguracji użytkownika (podpisy, hooki, autocrlf…)."""
    pusta = tmp_path / "pusty.gitconfig"
    pusta.write_text("", encoding="utf-8")
    env = dict(os.environ)
    env.update({"GIT_CONFIG_GLOBAL": str(pusta), "GIT_CONFIG_NOSYSTEM": "1", "GIT_TERMINAL_PROMPT": "0",
                "GITHUB_REF_NAME": "main"})
    return env


def _git(env: dict, cwd: Path, *args: str) -> str:
    wynik = subprocess.run([GIT, "-c", "user.name=test", "-c", "user.email=test@example.invalid", *args],
                           cwd=cwd, env=env, capture_output=True, text=True, encoding="utf-8", errors="replace",
                           check=True)
    return wynik.stdout


def _zapisz_stan(katalog: Path, stan: dict, log: list[str]) -> None:
    (katalog / "state").mkdir(exist_ok=True)
    (katalog / "state" / "stan.json").write_text(json.dumps(stan), encoding="utf-8", newline="\n")
    (katalog / "state" / "log.jsonl").write_text("".join(f"{l}\n" for l in log), encoding="utf-8", newline="\n")


@pytest.fixture
def repozytoria(tmp_path: Path, git_env: dict):
    """origin (bare) + klon „poprzedni” (przebieg N-1) + klon „biezacy” (przebieg N, na starym SHA)."""
    origin = tmp_path / "origin.git"
    _git(git_env, tmp_path, "init", "-q", "--bare", "-b", "main", str(origin))
    poprzedni = tmp_path / "poprzedni"
    _git(git_env, tmp_path, "clone", "-q", str(origin), str(poprzedni))
    _zapisz_stan(poprzedni, {"wyslane": {}}, ["start"])
    _git(git_env, poprzedni, "add", "-A")
    _git(git_env, poprzedni, "commit", "-qm", "baza")
    _git(git_env, poprzedni, "push", "-q", "origin", "HEAD:main")
    biezacy = tmp_path / "biezacy"
    _git(git_env, tmp_path, "clone", "-q", str(origin), str(biezacy))
    # N-1 wysyła alert i wypycha stan, zanim N skończy (N ma już pobrany stary SHA).
    _zapisz_stan(poprzedni, {"wyslane": {"a": "N-1"}}, ["start", "N-1"])
    _git(git_env, poprzedni, "commit", "-qam", "stan N-1")
    _git(git_env, poprzedni, "push", "-q", "origin", "HEAD:main")
    # N zapisuje własny stan (konflikt w obu plikach stanu).
    _zapisz_stan(biezacy, {"wyslane": {"a": "N-1", "b": "N"}}, ["start", "N"])
    return origin, poprzedni, biezacy


def _uruchom_skrypt(env: dict, cwd: Path, przed: str = "") -> subprocess.CompletedProcess:
    return subprocess.run([BASH, "-c", przed + _skrypt_commitu()], cwd=cwd, env=env,
                          capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120)


@pytest.mark.skipif(BRAK_NARZEDZI, reason="potrzebny git i bash (Git Bash na Windowsie)")
def test_commit_stanu_po_rownoleglym_commicie_konczy_sie_sukcesem(repozytoria, git_env):
    origin, _, biezacy = repozytoria
    wynik = _uruchom_skrypt(git_env, biezacy, przed="sleep() { :; }\n")
    assert wynik.returncode == 0, wynik.stdout + wynik.stderr
    # Na gałęzi jest stan TEGO przebiegu, a commit N-1 nie przepadł.
    stan = json.loads(_git(git_env, origin, "show", "main:state/stan.json"))
    assert stan == {"wyslane": {"a": "N-1", "b": "N"}}
    historia = _git(git_env, origin, "log", "--format=%s", "main")
    assert "stan N-1" in historia and historia.splitlines()[0].startswith("stan: ")
    autor = _git(git_env, origin, "log", "-1", "--format=%an <%ae>", "main").strip()
    assert autor == "github-actions[bot] <41898282+github-actions[bot]@users.noreply.github.com>"


@pytest.mark.skipif(BRAK_NARZEDZI, reason="potrzebny git i bash (Git Bash na Windowsie)")
def test_nieudany_rebase_jest_przerywany_i_kolejna_proba_przechodzi(repozytoria, git_env, tmp_path):
    """Konflikt, którego -X nie rozwiąże (plik usunięty po drugiej stronie), znika przed 2. próbą.

    Bez `git rebase --abort` druga próba kończy się „you have unmerged files” i przebieg przepada.
    """
    origin, poprzedni, biezacy = repozytoria
    _git(git_env, poprzedni, "rm", "-q", "state/log.jsonl")
    _git(git_env, poprzedni, "commit", "-qm", "usunięcie dziennika")
    _git(git_env, poprzedni, "push", "-q", "origin", "HEAD:main")
    # „sleep” w skrypcie = chwila, w której ktoś przywraca plik na gałęzi.
    naprawa = tmp_path / "naprawa.sh"
    naprawa.write_text(
        f'cd "{_posix(poprzedni)}" && printf "start\\n" > state/log.jsonl && git add state/log.jsonl'
        ' && git -c user.name=t -c user.email=t@example.invalid commit -qm przywrocenie'
        ' && git push -q origin HEAD:main\n', encoding="utf-8", newline="\n")
    przed = f'sleep() {{ if [ ! -e "{_posix(naprawa)}.ok" ]; then bash "{_posix(naprawa)}" && touch "{_posix(naprawa)}.ok"; fi; }}\n'
    wynik = _uruchom_skrypt(git_env, biezacy, przed=przed)
    assert wynik.returncode == 0, wynik.stdout + wynik.stderr
    assert "próba 1/3" in wynik.stdout
    assert json.loads(_git(git_env, origin, "show", "main:state/stan.json")) == {"wyslane": {"a": "N-1", "b": "N"}}
    assert not (biezacy / ".git" / "rebase-merge").exists() and not (biezacy / ".git" / "rebase-apply").exists()


@pytest.mark.skipif(BRAK_NARZEDZI, reason="potrzebny git i bash (Git Bash na Windowsie)")
def test_brak_zmiany_stanu_to_brak_commitu(tmp_path, git_env):
    origin = tmp_path / "origin.git"
    _git(git_env, tmp_path, "init", "-q", "--bare", "-b", "main", str(origin))
    klon = tmp_path / "klon"
    _git(git_env, tmp_path, "clone", "-q", str(origin), str(klon))
    _zapisz_stan(klon, {"wyslane": {}}, ["start"])
    _git(git_env, klon, "add", "-A")
    _git(git_env, klon, "commit", "-qm", "baza")
    _git(git_env, klon, "push", "-q", "origin", "HEAD:main")
    wynik = _uruchom_skrypt(git_env, klon)
    assert wynik.returncode == 0 and "brak commitu" in wynik.stdout
    assert _git(git_env, origin, "rev-list", "--count", "main").strip() == "1"
