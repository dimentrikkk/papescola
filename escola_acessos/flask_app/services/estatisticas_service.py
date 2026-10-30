"""Consultas agregadas para dashboards e relatórios."""
from __future__ import annotations

from datetime import timedelta

from ..db import get_db
from .. import utils


def kpis_hoje() -> dict:
    db = get_db()
    hoje = utils.today().isoformat()

    def n(sql, *a):
        return db.execute(sql, a).fetchone()[0]

    return {
        "alunos_ativos": n("SELECT COUNT(*) FROM alunos WHERE ativo = 1"),
        "na_escola": n("""SELECT COUNT(*) FROM alunos al WHERE al.ativo = 1 AND
              (SELECT tipo FROM acessos x WHERE x.aluno_id = al.id AND date(x.timestamp) = ?
                ORDER BY x.timestamp DESC, x.id DESC LIMIT 1) = 'entrada'""", hoje),
        "presentes_hoje": n("SELECT COUNT(*) FROM presencas WHERE data = ? AND estado = 'presente'", hoje),
        "atrasos_hoje": n("SELECT COUNT(*) FROM presencas WHERE data = ? AND estado = 'atraso'", hoje),
        "faltas_hoje": n("SELECT COUNT(*) FROM presencas WHERE data = ? AND estado IN ('falta','falta_justificada')", hoje),
        "justificacoes_pendentes": n("SELECT COUNT(*) FROM justificacoes WHERE estado = 'pendente'"),
        "sem_consentimento": n("SELECT COUNT(*) FROM alunos WHERE ativo = 1 AND consentimento_biometrico = 0"),
        "sem_email_ee": n("SELECT COUNT(*) FROM alunos WHERE ativo = 1 AND COALESCE(TRIM(encarregado_email), '') = ''"),
        "sem_horario": n("""SELECT COUNT(*) FROM turmas t WHERE NOT EXISTS (SELECT 1 FROM horarios_turma h WHERE h.turma_id = t.id)"""),
        "emails_pendentes": n("SELECT COUNT(*) FROM outbox_email WHERE estado = 'pendente'"),
        "emails_erro": n("SELECT COUNT(*) FROM outbox_email WHERE estado = 'erro'"),
    }


def estados_de_hoje() -> dict:
    rows = get_db().execute("SELECT estado, COUNT(*) c FROM presencas WHERE data = ? GROUP BY estado", (utils.today().isoformat(),))
    r = {"presente": 0, "atraso": 0, "falta": 0, "falta_justificada": 0}
    for x in rows:
        r[x["estado"]] = x["c"]
    return r


def entradas_por_dia(dias: int = 7) -> list[dict]:
    db = get_db()
    hoje = utils.today()
    out = []
    for i in range(dias - 1, -1, -1):
        d = (hoje - timedelta(days=i)).isoformat()
        n = db.execute("SELECT COUNT(DISTINCT aluno_id) FROM acessos WHERE tipo='entrada' AND date(timestamp)=?", (d,)).fetchone()[0]
        out.append({"data": d, "alunos": n})
    return out


def _desde(dias: int) -> str:
    return (utils.today() - timedelta(days=dias)).isoformat()


def ocorrencias_por_turma(dias: int = 30) -> list[dict]:
    rows = get_db().execute(
        """SELECT t.nome AS turma, SUM(p.estado = 'atraso') AS atrasos, SUM(p.estado = 'falta') AS faltas
             FROM presencas p JOIN alunos al ON al.id = p.aluno_id JOIN turmas t ON t.id = al.turma_id
            WHERE p.data >= ? GROUP BY t.id ORDER BY t.nome""", (_desde(dias),)).fetchall()
    return [{"turma": r["turma"], "atrasos": r["atrasos"] or 0, "faltas": r["faltas"] or 0} for r in rows]


def chegadas_por_hora(dias: int = 30) -> list[dict]:
    """Quantas entradas por intervalo de 15 minutos (para ver os picos de chegada)."""
    rows = get_db().execute(
        """SELECT substr(hora_entrada,1,2) AS h, CAST(substr(hora_entrada,4,2) AS INTEGER) / 15 AS q, COUNT(*) c
             FROM presencas WHERE hora_entrada IS NOT NULL AND data >= ? GROUP BY h, q ORDER BY h, q""", (_desde(dias),)).fetchall()
    return [{"hora": f"{r['h']}:{r['q'] * 15:02d}", "c": r["c"]} for r in rows]


def ranking(estado: str, dias: int = 30, limite: int = 8) -> list[dict]:
    rows = get_db().execute(
        """SELECT al.id, al.nome_completo, t.nome AS turma, COUNT(*) AS n, COALESCE(SUM(p.atraso_minutos), 0) AS minutos
             FROM presencas p JOIN alunos al ON al.id = p.aluno_id LEFT JOIN turmas t ON t.id = al.turma_id
            WHERE p.estado = ? AND p.data >= ? AND al.ativo = 1 GROUP BY al.id ORDER BY n DESC, minutos DESC LIMIT ?""",
        (estado, _desde(dias), limite)).fetchall()
    return [dict(r) for r in rows]
