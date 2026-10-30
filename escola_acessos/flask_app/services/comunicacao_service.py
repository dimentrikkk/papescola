"""Emails aos encarregados de educação (EE). Os textos ficam aqui; o envio é feito pela fila (outbox)."""
from __future__ import annotations

from flask import current_app

from . import notification_service as notif

_DIAS = ["segunda-feira", "terça-feira", "quarta-feira", "quinta-feira", "sexta-feira", "sábado", "domingo"]


def _data_pt(d) -> str:
    return f"{_DIAS[d.weekday()]}, {d.strftime('%d/%m/%Y')}"


def _assinatura() -> str:
    cfg = current_app.config
    extra = f"\n{cfg['ESCOLA_CONTACTO']}" if cfg.get("ESCOLA_CONTACTO") else ""
    return (f"\n\nCom os melhores cumprimentos,\n{cfg['ESCOLA_NOME']}{extra}\n\n"
            "(Mensagem automática do sistema de controlo de assiduidade.)")


def _saudacao(aluno) -> str:
    nome = (aluno["encarregado_nome"] or "").strip()
    return f"Exmo(a). Sr(a). {nome}," if nome else "Exmo(a). Encarregado(a) de Educação,"


def avisar(tipo: str, aluno, d, *, prevista: str = "", real: str = "", atraso: int = 0, turma: str = "", saida_antecipada: int = 0) -> bool:
    """tipo: falta | atraso | correcao | saida_antecipada. Devolve True se ficou na fila."""
    cfg = current_app.config
    nome, turma_txt = aluno["nome_completo"], (f" ({turma})" if turma else "")
    quando = _data_pt(d)

    if tipo == "falta":
        if not cfg["AVISAR_EE_FALTA"]:
            return False
        assunto = f"{cfg['ESCOLA_NOME']} — Falta de {nome} ({d.strftime('%d/%m')})"
        corpo = (f"{_saudacao(aluno)}\n\nInformamos que o(a) aluno(a) {nome}{turma_txt} não registou entrada na escola "
                 f"hoje, {quando}. A hora de entrada prevista era às {prevista}.\n\n"
                 "Se a ausência tem justificação, solicitamos que a comunique à direção de turma ou à secretaria, "
                 "ou que o aluno submeta o pedido de justificação na plataforma.")
    elif tipo == "atraso":
        if not cfg["AVISAR_EE_ATRASO"]:
            return False
        assunto = f"{cfg['ESCOLA_NOME']} — Atraso de {nome} ({d.strftime('%d/%m')})"
        corpo = (f"{_saudacao(aluno)}\n\nInformamos que o(a) aluno(a) {nome}{turma_txt} entrou na escola hoje, {quando}, "
                 f"às {real}, com {atraso} minuto(s) de atraso (hora de entrada prevista: {prevista}).")
    elif tipo == "saida_antecipada":
        if not cfg["AVISAR_SAIDA_ANTECIPADA"]:
            return False
        assunto = f"{cfg['ESCOLA_NOME']} — Saída antecipada de {nome} ({d.strftime('%d/%m')})"
        corpo = (f"{_saudacao(aluno)}\n\nInformamos que o(a) aluno(a) {nome}{turma_txt} saiu da escola hoje, {quando}, "
                 f"às {real}, {saida_antecipada} minuto(s) antes da hora de saída prevista ({prevista}).")
    elif tipo == "correcao":
        assunto = f"{cfg['ESCOLA_NOME']} — Atualização sobre {nome} ({d.strftime('%d/%m')})"
        corpo = (f"{_saudacao(aluno)}\n\nCorrigimos a informação enviada anteriormente: o(a) aluno(a) {nome}{turma_txt} "
                 f"tem a presença registada como regular no dia {quando}. Pedimos desculpa por qualquer incómodo.")
    else:
        raise ValueError(tipo)
    return notif.enfileirar_email_encarregado(aluno, assunto, corpo + _assinatura())
