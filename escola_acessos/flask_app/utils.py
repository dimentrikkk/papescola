"""Pequenos utilitários partilhados (tempo, formatação, validação)."""
from __future__ import annotations

import re
import unicodedata
from datetime import date, datetime

DIAS_SEMANA = ["Segunda", "Terça", "Quarta", "Quinta", "Sexta", "Sábado", "Domingo"]

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_HHMM_RE = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)$")


def now() -> datetime:
    """Hora atual (sem microssegundos). Os serviços chamam utils.now() para ser fácil simular nos testes."""
    return datetime.now().replace(microsecond=0)


def today() -> date:
    return now().date()


def iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%d %H:%M:%S")


def parse_dt(s: str) -> datetime:
    return datetime.strptime(str(s)[:19], "%Y-%m-%d %H:%M:%S")


def hhmm_to_min(s: str) -> int:
    h, m = s.split(":")
    return int(h) * 60 + int(m)


def at(d: date, hhmm: str) -> datetime:
    h, m = hhmm.split(":")
    return datetime(d.year, d.month, d.day, int(h), int(m))


def valid_email(s: str) -> bool:
    return bool(s) and len(s) <= 120 and bool(_EMAIL_RE.match(s))


def valid_hhmm(s: str) -> bool:
    return bool(s) and bool(_HHMM_RE.match(s))


def valid_date(s: str) -> bool:
    try:
        date.fromisoformat(s)
        return True
    except (TypeError, ValueError):
        return False


def clean(s, maxlen: int = 200) -> str:
    return (s or "").strip()[:maxlen]


def ascii_only(s: str) -> str:
    """Remove acentos (os LCD HD44780 não têm caracteres acentuados)."""
    return unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode("ascii")


def first_name(full: str) -> str:
    return (full or "").split(" ")[0]


def format_minutes(mins: int) -> str:
    h, m = divmod(int(mins or 0), 60)
    return f"{h:02d}h{m:02d}"
