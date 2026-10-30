"""Assiduidade por DIA. Só contam a 1.ª entrada e a última saída (a porta está só à entrada da escola).

Regras (ver README):
  • 1.ª entrada ≤ hora prevista + tolerância ........ presente
  • 1.ª entrada depois disso ........................ atraso (e aviso ao encarregado)
  • sem entrada passados FALTA_APOS_MIN minutos ..... falta (e aviso ao encarregado)
  • falta com justificação aprovada ................. falta justificada
  • a marcação manual (professor/admin) nunca é sobrescrita pelo cálculo automático
"""
from __future__ import annotations

import time as _time
from datetime import date, datetime, timedelta
from typing import Optional

from flask import current_app

from ..db import get_db
from .. import utils
from . import comunicacao_service as comunic
from . import horario_service
from . import notification_service as notif

ESTADOS = ("presente", "atraso", "falta", "falta_justificada")
ROTULOS = {"presente": "Presente", "atraso": "Atraso", "falta": "Falta", "falta_justificada": "Falta justificada"}


# ------------------------------ regra pura ------------------------------
def avaliar_dia(entrada: Optional[datetime], saida: Optional[datetime], prev_entrada: datetime, prev_saida: datetime,
                agora: datetime, tol_min: int, falta_apos_min: int, saida_tol_min: int) -> Optional[dict]:
    """Devolve {estado, atraso, saida_antecipada} ou None se ainda é cedo para decidir."""
    if entrada is not None:
        if entrada >= prev_saida:                       # só apareceu depois de as aulas acabarem
            estado, atraso = "falta", 0
        else:
            delta = int((entrada - prev_entrada).total_seconds() // 60)
            estado, atraso = ("presente", 0) if delta <= tol_min else ("atraso", delta)
    else:
        if agora < prev_entrada + timedelta(minutes=falta_apos_min):
            return None
        estado, atraso = "falta", 0

    saida_ant = 0
    if entrada is not None and saida is not None and saida < prev_saida - timedelta(minutes=saida_tol_min):
        saida_ant = int((prev_saida - saida).total_seconds() // 60)
    return {"estado": estado, "atraso": atraso, "saida_antecipada": saida_ant}


def _entrada_e_saida(aluno_id: int, d: date) -> tuple[Optional[datetime], Optional[datetime]]:
    rows = get_db().execute(
        "SELECT tipo, timestamp FROM acessos WHERE aluno_id = ? AND date(timestamp) = ? ORDER BY timestamp, id",
        (aluno_id, d.isoformat())).fetchall()
    entrada = next((utils.parse_dt(r["timestamp"]) for r in rows if r["tipo"] == "entrada"), None)
    saida = None
    if rows and rows[-1]["tipo"] == "saida":            # a última passagem foi uma saída → já saiu da escola
        saida = utils.parse_dt(rows[-1]["timestamp"])
    return entrada, saida


def _justificado(aluno_id: int, d: date) -> bool:
    return get_db().execute(
        "SELECT 1 FROM justificacoes WHERE aluno_id = ? AND estado = 'aprovado' AND data_inicio <= ? AND data_fim >= ? LIMIT 1",
        (aluno_id, d.isoformat(), d.isoformat())).fetchone() is not None


# ------------------------------ cálculo ------------------------------
def atualizar_dia_aluno(aluno_id: int, d: date, agora: Optional[datetime] = None, avisar: Optional[bool] = None) -> Optional[str]:
    """(Re)calcula a presença de um aluno num dia. Devolve o estado ou None (sem horário / ainda cedo / marcação manual).
    `avisar`: enviar avisos ao aluno/EE. Por defeito só para o dia de hoje (nunca se avisa sobre dias antigos)."""
    db = get_db()
    cfg = current_app.config
    agora = agora or utils.now()
    avisar = (d == utils.today()) if avisar is None else avisar   # nunca se avisa sobre dias que não são hoje

    aluno = db.execute("SELECT al.*, t.nome AS turma, t.diretor_turma_id FROM alunos al LEFT JOIN turmas t ON t.id = al.turma_id "
                       "WHERE al.id = ? AND al.ativo = 1", (aluno_id,)).fetchone()
    if not aluno:
        return None
    hor = horario_service.horario_do_dia(aluno["turma_id"], d.weekday())
    if not hor:
        return None

    atual = db.execute("SELECT * FROM presencas WHERE aluno_id = ? AND data = ?", (aluno_id, d.isoformat())).fetchone()
    if atual and atual["origem"] == "manual":
        return None

    prev_e, prev_s = utils.at(d, hor["hora_entrada"]), utils.at(d, hor["hora_saida"])
    entrada, saida = _entrada_e_saida(aluno_id, d)
    res = avaliar_dia(entrada, saida, prev_e, prev_s, agora, cfg["TOLERANCIA_ATRASO_MIN"], cfg["FALTA_APOS_MIN"],
                      cfg["SAIDA_ANTECIPADA_TOL_MIN"])
    if res is None:
        return None
    estado = res["estado"]
    if estado == "falta" and _justificado(aluno_id, d):
        estado = "falta_justificada"

    h_ent = entrada.strftime("%H:%M") if entrada else None
    h_sai = saida.strftime("%H:%M") if saida else None
    ts = utils.iso(agora)
    if atual:
        db.execute("""UPDATE presencas SET estado=?, hora_entrada=?, hora_saida=?, atraso_minutos=?, saida_antecipada_min=?, updated_at=?
                       WHERE id=?""", (estado, h_ent, h_sai, res["atraso"], res["saida_antecipada"], ts, atual["id"]))
    else:
        db.execute("""INSERT INTO presencas (aluno_id, data, estado, hora_entrada, hora_saida, atraso_minutos, saida_antecipada_min, origem, updated_at)
                      VALUES (?,?,?,?,?,?,?, 'auto', ?)""",
                   (aluno_id, d.isoformat(), estado, h_ent, h_sai, res["atraso"], res["saida_antecipada"], ts))
    db.commit()

    if avisar:
        _avisos(aluno, d, estado, h_ent, hor["hora_entrada"], res["atraso"], res["saida_antecipada"], h_sai, hor["hora_saida"])
    return estado


def _avisos(aluno, d: date, estado: str, h_ent: Optional[str], prevista: str, atraso: int, saida_ant: int,
            h_sai: Optional[str], prevista_saida: str) -> None:
    """Notificações e emails, sem repetir (a coluna aviso_estado lembra o que já foi avisado)."""
    db = get_db()
    row = db.execute("SELECT id, aviso_estado, aviso_saida FROM presencas WHERE aluno_id = ? AND data = ?",
                     (aluno["id"], d.isoformat())).fetchone()
    if not row:
        return
    anterior = row["aviso_estado"]
    novo_aviso = anterior
    turma = aluno["turma"] or ""

    if estado in ("atraso", "falta") and anterior != estado:
        if estado == "atraso":
            notif.notify("aluno", aluno["id"], "Chegada com atraso",
                         f"Entrou às {h_ent}, {atraso} min depois da hora prevista ({prevista}).", "warn")
            comunic.avisar("atraso", aluno, d, prevista=prevista, real=h_ent or "", atraso=atraso, turma=turma)
        else:
            notif.notify("aluno", aluno["id"], "Falta registada", f"Não registou entrada hoje (previsto às {prevista}).", "error")
            if aluno["diretor_turma_id"]:
                notif.notify("professor", aluno["diretor_turma_id"], "Falta de aluno",
                             f"{aluno['nome_completo']} ({turma}) não registou entrada hoje.", "warn")
            comunic.avisar("falta", aluno, d, prevista=prevista, turma=turma)
        novo_aviso = estado
    elif estado in ("presente", "falta_justificada") and anterior in ("atraso", "falta"):
        if estado == "presente":                       # corrigido manualmente → pedir desculpa ao EE
            comunic.avisar("correcao", aluno, d, turma=turma)
        novo_aviso = None

    if novo_aviso != anterior:
        db.execute("UPDATE presencas SET aviso_estado = ? WHERE id = ?", (novo_aviso, row["id"]))
    if saida_ant and not row["aviso_saida"]:
        comunic.avisar("saida_antecipada", aluno, d, prevista=prevista_saida, real=h_sai or "", turma=turma, saida_antecipada=saida_ant)
        db.execute("UPDATE presencas SET aviso_saida = 1 WHERE id = ?", (row["id"],))
    db.commit()


def processar_dia(d: date, turma_id: Optional[int] = None, agora: Optional[datetime] = None, avisar: Optional[bool] = None) -> dict:
    """Recalcula todos os alunos das turmas que têm aulas nesse dia. Idempotente."""
    db = get_db()
    agora = agora or utils.now()
    sql = "SELECT turma_id FROM horarios_turma WHERE dia_semana = ?"
    args: list = [d.weekday()]
    if turma_id:
        sql += " AND turma_id = ?"
        args.append(turma_id)
    stats = {"turmas": 0, "alunos": 0, "presentes": 0, "atrasos": 0, "faltas": 0}
    for t in db.execute(sql, args).fetchall():
        stats["turmas"] += 1
        for al in db.execute("SELECT id FROM alunos WHERE turma_id = ? AND ativo = 1", (t["turma_id"],)).fetchall():
            estado = atualizar_dia_aluno(al["id"], d, agora, avisar)
            if estado:
                stats["alunos"] += 1
                stats["presentes"] += estado == "presente"
                stats["atrasos"] += estado == "atraso"
                stats["faltas"] += estado in ("falta", "falta_justificada")
    return stats


def recalcular_periodo(de: date, ate: date, turma_id: Optional[int] = None) -> int:
    """Recalcula dias passados SEM enviar avisos (usado após migrações e correções)."""
    n, d = 0, de
    while d <= ate:
        if d.weekday() < 6:
            # dias passados: "agora" é o fim do dia; hoje: a hora real (ainda há quem possa chegar)
            agora = utils.now() if d >= utils.today() else datetime.combine(d, datetime.max.time()).replace(microsecond=0)
            n += processar_dia(d, turma_id, agora=agora, avisar=False)["alunos"]
        d += timedelta(days=1)
    return n


_ultimo_processamento = 0.0


def processar_hoje_se_necessario(intervalo_s: int = 120) -> None:
    """Chamado pelas páginas de admin/professor: garante que as faltas do dia são detetadas e avisadas
    mesmo que o porteiro não esteja a correr (no máximo uma vez por `intervalo_s`)."""
    global _ultimo_processamento
    if _time.monotonic() - _ultimo_processamento < intervalo_s:
        return
    _ultimo_processamento = _time.monotonic()
    try:
        processar_dia(utils.today())
    except Exception:  # noqa: BLE001  (nunca deve estragar uma página)
        current_app.logger.exception("Falha ao processar presenças de hoje")


# ------------------------------ marcação manual ------------------------------
def definir_estado(aluno_id: int, d: date, estado: str, atraso: int = 0, nota: Optional[str] = None) -> None:
    """Marcação feita por professor/administração. Tem prioridade sobre o automático."""
    if estado not in ESTADOS:
        raise ValueError("Estado inválido.")
    db = get_db()
    aluno = db.execute("SELECT al.*, t.nome AS turma, t.diretor_turma_id FROM alunos al LEFT JOIN turmas t ON t.id = al.turma_id WHERE al.id = ?",
                       (aluno_id,)).fetchone()
    if not aluno:
        raise ValueError("Aluno inexistente.")
    entrada, saida = _entrada_e_saida(aluno_id, d)
    hor = horario_service.horario_do_dia(aluno["turma_id"], d.weekday())
    atraso = max(0, int(atraso or 0)) if estado == "atraso" else 0
    ts = utils.iso(utils.now())
    h_ent = entrada.strftime("%H:%M") if entrada else None
    h_sai = saida.strftime("%H:%M") if saida else None
    atual = db.execute("SELECT id FROM presencas WHERE aluno_id = ? AND data = ?", (aluno_id, d.isoformat())).fetchone()
    if atual:
        db.execute("UPDATE presencas SET estado=?, atraso_minutos=?, nota=?, origem='manual', hora_entrada=COALESCE(?, hora_entrada), "
                   "hora_saida=COALESCE(?, hora_saida), updated_at=? WHERE id=?", (estado, atraso, nota, h_ent, h_sai, ts, atual["id"]))
    else:
        db.execute("INSERT INTO presencas (aluno_id, data, estado, hora_entrada, hora_saida, atraso_minutos, origem, nota, updated_at) "
                   "VALUES (?,?,?,?,?,?, 'manual', ?, ?)", (aluno_id, d.isoformat(), estado, h_ent, h_sai, atraso, nota, ts))
    db.commit()
    if d == utils.today() and hor:
        _avisos(aluno, d, estado, h_ent, hor["hora_entrada"], atraso, 0, h_sai, hor["hora_saida"])


def repor_auto(aluno_id: int, d: date) -> None:
    """Apaga a marcação manual e deixa o cálculo automático voltar a decidir."""
    db = get_db()
    db.execute("DELETE FROM presencas WHERE aluno_id = ? AND data = ? AND origem = 'manual'", (aluno_id, d.isoformat()))
    db.commit()
    atualizar_dia_aluno(aluno_id, d, avisar=False)


def aplicar_justificacao(aluno_id: int, data_inicio: str, data_fim: str) -> int:
    db = get_db()
    cur = db.execute("UPDATE presencas SET estado = 'falta_justificada', updated_at = ? "
                     "WHERE aluno_id = ? AND data BETWEEN ? AND ? AND estado = 'falta'",
                     (utils.iso(utils.now()), aluno_id, data_inicio, data_fim))
    db.commit()
    return cur.rowcount


# ------------------------------ consultas ------------------------------
def dia_turma(turma_id: int, d: date):
    """Todos os alunos ativos da turma com o estado nesse dia (estado None = ainda sem decisão)."""
    return get_db().execute(
        """SELECT al.id AS aluno_id, al.numero_processo, al.nome_completo, al.foto_perfil, al.encarregado_email,
                  p.estado, p.hora_entrada, p.hora_saida, p.atraso_minutos, p.saida_antecipada_min, p.origem, p.nota
             FROM alunos al LEFT JOIN presencas p ON p.aluno_id = al.id AND p.data = ?
            WHERE al.turma_id = ? AND al.ativo = 1 ORDER BY al.nome_completo""", (d.isoformat(), turma_id)).fetchall()


def contagens(aluno_id: int, de: Optional[str] = None, ate: Optional[str] = None) -> dict:
    sql = "SELECT estado, COUNT(*) c FROM presencas WHERE aluno_id = ?"
    args: list = [aluno_id]
    if de:
        sql += " AND data >= ?"
        args.append(de)
    if ate:
        sql += " AND data <= ?"
        args.append(ate)
    r = {e: 0 for e in ESTADOS}
    for row in get_db().execute(sql + " GROUP BY estado", args):
        r[row["estado"]] = row["c"]
    r["dias"] = sum(r[e] for e in ESTADOS)
    return r


def mes_do_aluno(aluno_id: int, ano: int, mes: int) -> dict[str, dict]:
    pref = f"{ano:04d}-{mes:02d}"
    return {r["data"]: dict(r) for r in get_db().execute(
        "SELECT * FROM presencas WHERE aluno_id = ? AND substr(data,1,7) = ?", (aluno_id, pref))}


def resumo_turma(turma_id: int, de: str, ate: str) -> list[dict]:
    rows = get_db().execute(
        """SELECT al.id, al.numero_processo, al.nome_completo,
                  COALESCE(SUM(p.estado = 'presente'), 0) AS presentes, COALESCE(SUM(p.estado = 'atraso'), 0) AS atrasos,
                  COALESCE(SUM(p.estado = 'falta'), 0) AS faltas, COALESCE(SUM(p.estado = 'falta_justificada'), 0) AS justificadas,
                  COALESCE(SUM(p.atraso_minutos), 0) AS min_atraso
             FROM alunos al LEFT JOIN presencas p ON p.aluno_id = al.id AND p.data BETWEEN ? AND ?
            WHERE al.turma_id = ? AND al.ativo = 1 GROUP BY al.id ORDER BY al.nome_completo""", (de, ate, turma_id)).fetchall()
    return [dict(r) for r in rows]
