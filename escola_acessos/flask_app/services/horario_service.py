"""Horário simplificado: por turma e dia da semana, só a HORA DE ENTRADA (1.ª aula) e a HORA DE SAÍDA
(fim da última aula). O horário detalhado das disciplinas já existe noutra aplicação da escola."""
from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Optional

from ..db import get_db
from .. import utils


def horario_turma(turma_id: int) -> dict[int, dict]:
    """{dia_semana: {hora_entrada, hora_saida}} — só os dias com aulas."""
    rows = get_db().execute("SELECT * FROM horarios_turma WHERE turma_id = ? ORDER BY dia_semana", (turma_id,)).fetchall()
    return {r["dia_semana"]: dict(r) for r in rows}


def horario_do_dia(turma_id: Optional[int], dia_semana: int):
    if not turma_id:
        return None
    return get_db().execute("SELECT * FROM horarios_turma WHERE turma_id = ? AND dia_semana = ?",
                            (turma_id, dia_semana)).fetchone()


def validar(entrada: str, saida: str) -> Optional[str]:
    if not utils.valid_hhmm(entrada) or not utils.valid_hhmm(saida):
        return "Use horas válidas no formato HH:MM."
    if saida <= entrada:
        return "A hora de saída tem de ser depois da hora de entrada."
    return None


def guardar_horario(turma_id: int, dias: dict[int, Optional[tuple[str, str]]]) -> None:
    """dias: {0: ('09:00','17:30'), 1: None, ...}. None remove o dia (sem aulas)."""
    db = get_db()
    for dia, par in dias.items():
        if par is None:
            db.execute("DELETE FROM horarios_turma WHERE turma_id = ? AND dia_semana = ?", (turma_id, dia))
        else:
            db.execute(
                """INSERT INTO horarios_turma (turma_id, dia_semana, hora_entrada, hora_saida) VALUES (?,?,?,?)
                   ON CONFLICT(turma_id, dia_semana) DO UPDATE SET hora_entrada = excluded.hora_entrada, hora_saida = excluded.hora_saida""",
                (turma_id, dia, par[0], par[1]))
    db.commit()


def copiar_para_outras_turmas(turma_origem: int) -> int:
    """Aplica o horário de uma turma a TODAS as outras (substitui o que lá estava). Devolve nº de turmas."""
    db = get_db()
    origem = horario_turma(turma_origem)
    outras = [r["id"] for r in db.execute("SELECT id FROM turmas WHERE id != ?", (turma_origem,))]
    for t in outras:
        db.execute("DELETE FROM horarios_turma WHERE turma_id = ?", (t,))
        for dia, h in origem.items():
            db.execute("INSERT INTO horarios_turma (turma_id, dia_semana, hora_entrada, hora_saida) VALUES (?,?,?,?)",
                       (t, dia, h["hora_entrada"], h["hora_saida"]))
    db.commit()
    return len(outras)


def todos_os_horarios() -> dict[int, dict[int, dict]]:
    out: dict[int, dict[int, dict]] = {}
    for r in get_db().execute("SELECT * FROM horarios_turma ORDER BY turma_id, dia_semana"):
        out.setdefault(r["turma_id"], {})[r["dia_semana"]] = dict(r)
    return out


def proximo_dia_com_aulas(turma_id: int, agora: datetime):
    """Hoje (se ainda não acabou) ou o próximo dia com aulas. Devolve (horario, data) ou (None, None)."""
    hor = horario_turma(turma_id)
    for i in range(8):
        d: date = agora.date() + timedelta(days=i)
        h = hor.get(d.weekday())
        if h and utils.at(d, h["hora_saida"]) > agora:
            return h, d
    return None, None
