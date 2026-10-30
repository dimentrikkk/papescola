"""Entradas/saídas da escola. É AQUI que está a lógica do "porteiro"; tanto o kiosk web
como o processo do Raspberry Pi chamam estas funções (a lógica não está duplicada)."""
from __future__ import annotations

import uuid
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Optional

import numpy as np
from PIL import Image
from flask import current_app

from ..db import get_db
from .. import utils
from . import face_service, horario_service, presenca_service


@dataclass
class ResultadoAcesso:
    estado: str                      # aceite | repetido | nao_reconhecido | ambiguo | sem_rosto | sem_dados
    tipo: Optional[str] = None       # entrada | saida
    aluno_id: Optional[int] = None
    aluno_nome: Optional[str] = None
    turma: Optional[str] = None
    hora: Optional[str] = None
    atraso_min: int = 0
    abrir: bool = False              # deve abrir o trinco?
    som: str = "erro"                # ok | aviso | erro
    linha1: str = ""                 # texto para o display (já sem acentos, cabe em 16 colunas)
    linha2: str = ""
    mensagem: str = ""               # texto completo para o kiosk web

    @property
    def sucesso(self) -> bool:
        return self.estado in ("aceite", "repetido")

    def as_dict(self) -> dict:
        d = asdict(self)
        d["ok"] = self.sucesso
        return d


def _fit(text: str, cols: int) -> str:
    return utils.ascii_only(text)[:cols]


def _cols() -> int:
    return current_app.config["DISPLAY_COLS"]


def registar_evento(tipo: str, aluno_id: Optional[int] = None, detalhe: Optional[str] = None,
                    dedupe_segundos: int = 0) -> None:
    db = get_db()
    agora = utils.now()
    if dedupe_segundos:
        ultimo = db.execute("SELECT timestamp FROM eventos_porta WHERE tipo = ? ORDER BY id DESC LIMIT 1", (tipo,)).fetchone()
        if ultimo and (agora - utils.parse_dt(ultimo["timestamp"])).total_seconds() < dedupe_segundos:
            return
    db.execute("INSERT INTO eventos_porta (timestamp, tipo, aluno_id, detalhe) VALUES (?,?,?,?)",
               (utils.iso(agora), tipo, aluno_id, detalhe))
    db.commit()


def _proximo_tipo(aluno_id: int, dia) -> str:
    ultimo = get_db().execute(
        "SELECT tipo FROM acessos WHERE aluno_id = ? AND date(timestamp) = ? ORDER BY timestamp DESC, id DESC LIMIT 1",
        (aluno_id, dia.isoformat()),
    ).fetchone()
    return "saida" if ultimo and ultimo["tipo"] == "entrada" else "entrada"


def _atraso_na_entrada(aluno, agora) -> int:
    """Minutos de atraso face à hora de entrada da turma (só a 1.ª entrada do dia conta)."""
    hor = horario_service.horario_do_dia(aluno["turma_id"], agora.weekday())
    if not hor:
        return 0
    ja_entrou = get_db().execute(
        "SELECT 1 FROM acessos WHERE aluno_id = ? AND tipo = 'entrada' AND date(timestamp) = ? LIMIT 1",
        (aluno["id"], agora.date().isoformat())).fetchone()
    if ja_entrou:
        return 0
    delta = (agora - utils.at(agora.date(), hor["hora_entrada"])).total_seconds() / 60
    if agora >= utils.at(agora.date(), hor["hora_saida"]) or delta <= current_app.config["TOLERANCIA_ATRASO_MIN"]:
        return 0
    return int(delta)


def _saida_antecipada(aluno, agora) -> int:
    hor = horario_service.horario_do_dia(aluno["turma_id"], agora.weekday())
    if not hor:
        return 0
    falta = (utils.at(agora.date(), hor["hora_saida"]) - agora).total_seconds() / 60
    return int(falta) if falta > current_app.config["SAIDA_ANTECIPADA_TOL_MIN"] else 0


def _guardar_foto(rgb: np.ndarray, aluno_id: int) -> str:
    pasta = Path(current_app.config["UPLOAD_DIR"])
    pasta.mkdir(parents=True, exist_ok=True)
    nome = f"acesso_{aluno_id}_{utils.now():%Y%m%d_%H%M%S}_{uuid.uuid4().hex[:6]}.jpg"
    Image.fromarray(rgb).save(pasta / nome, "JPEG", quality=80)
    return nome


def registar_aluno(aluno_id: int, origem: str = "porteiro", rgb: Optional[np.ndarray] = None,
                   tipo_forcado: Optional[str] = None) -> ResultadoAcesso:
    """Regista a entrada/saída de um aluno já identificado."""
    db = get_db()
    cfg = current_app.config
    cols = _cols()
    aluno = db.execute(
        "SELECT al.*, t.nome AS turma FROM alunos al LEFT JOIN turmas t ON t.id = al.turma_id WHERE al.id = ?",
        (aluno_id,),
    ).fetchone()
    if not aluno or not aluno["ativo"]:
        return ResultadoAcesso("nao_reconhecido", linha1=_fit("Aluno inativo", cols), linha2=_fit("Fale c/ secretaria", cols),
                               mensagem="Aluno inativo ou inexistente.")

    agora = utils.now()
    nome1 = utils.first_name(aluno["nome_completo"])

    # Anti-duplicado: a mesma pessoa parada à frente da câmara não pode alternar entrada/saída sem parar
    ultimo = db.execute("SELECT timestamp, tipo FROM acessos WHERE aluno_id = ? ORDER BY timestamp DESC, id DESC LIMIT 1",
                        (aluno_id,)).fetchone()
    if ultimo and not tipo_forcado and (agora - utils.parse_dt(ultimo["timestamp"])).total_seconds() < cfg["COOLDOWN_SEGUNDOS"]:
        return ResultadoAcesso(
            "repetido", tipo=ultimo["tipo"], aluno_id=aluno_id, aluno_nome=aluno["nome_completo"], turma=aluno["turma"],
            hora=utils.parse_dt(ultimo["timestamp"]).strftime("%H:%M"), abrir=True, som="ok",
            linha1=_fit(f"Ola {nome1}", cols), linha2=_fit("Ja registado", cols),
            mensagem=f"{aluno['nome_completo']}: já registado há instantes.",
        )

    tipo = tipo_forcado or _proximo_tipo(aluno_id, agora.date())
    atraso = _atraso_na_entrada(aluno, agora) if tipo == "entrada" else 0
    foto = _guardar_foto(rgb, aluno_id) if (rgb is not None and cfg["GUARDAR_FOTOS_ACESSO"]) else None

    db.execute("INSERT INTO acessos (aluno_id, tipo, timestamp, origem, foto_path) VALUES (?,?,?,?,?)",
               (aluno_id, tipo, utils.iso(agora), origem, foto))
    db.commit()
    registar_evento("reconhecido" if origem != "manual" else "manual", aluno_id, tipo)

    # Atualiza já a presença do dia (e envia o aviso ao EE se for atraso). Nunca pode travar a porta.
    try:
        presenca_service.atualizar_dia_aluno(aluno_id, agora.date(), agora)
    except Exception:  # noqa: BLE001
        current_app.logger.exception("Falha ao atualizar a presença de %s", aluno_id)

    hora = agora.strftime("%H:%M")
    if tipo == "entrada":
        if atraso:
            l2, msg, som = f"Atraso {atraso} min", f"Entrada às {hora} — atraso de {atraso} min.", "aviso"
        else:
            l2, msg, som = f"Entrada {hora}", f"Entrada registada às {hora}.", "ok"
        abrir = True
    else:
        antecip = _saida_antecipada(aluno, agora)
        if antecip:
            l2, msg, som = "Saida antecipada", f"Saída às {hora} ({antecip} min antes do fim do horário).", "aviso"
        else:
            l2, msg, som = f"Saida {hora}", f"Saída registada às {hora}.", "ok"
        abrir = cfg["ABRIR_NA_SAIDA"]

    return ResultadoAcesso(
        "aceite", tipo=tipo, aluno_id=aluno_id, aluno_nome=aluno["nome_completo"], turma=aluno["turma"],
        hora=hora, atraso_min=atraso, abrir=abrir, som=som,
        linha1=_fit(f"Ola {nome1}", cols), linha2=_fit(l2, cols), mensagem=msg,
    )


def processar_imagem(rgb: np.ndarray, origem: str = "porteiro", scale: float = 1.0) -> ResultadoAcesso:
    """Identifica o rosto e regista o acesso. Usado pelo porteiro (Pi) e pelo kiosk web."""
    cols = _cols()
    ident = face_service.identify(rgb, scale)
    if ident.estado == "sem_rosto":
        return ResultadoAcesso("sem_rosto", mensagem="Nenhum rosto detetado.")
    if ident.estado == "sem_dados":
        return ResultadoAcesso("sem_dados", linha1=_fit("Sem alunos", cols), linha2=_fit("registados", cols),
                               mensagem="Ainda não há rostos registados.")
    if ident.estado == "ambiguo":
        registar_evento("ambiguo", None, f"dist={ident.distancia:.2f}", dedupe_segundos=10)
        return ResultadoAcesso("ambiguo", linha1=_fit("Rosto ambiguo", cols), linha2=_fit("Va a portaria", cols),
                               mensagem="Rosto ambíguo — dirija-se à portaria.")
    if ident.estado == "desconhecido":
        registar_evento("nao_reconhecido", None, f"dist={ident.distancia:.2f}", dedupe_segundos=10)
        return ResultadoAcesso("nao_reconhecido", linha1=_fit("Nao reconhecido", cols), linha2=_fit("Tente de novo", cols),
                               mensagem="Rosto não reconhecido.")
    return registar_aluno(ident.aluno_id, origem=origem, rgb=rgb)


def registar_manual(aluno_id: int, tipo: str, quando=None) -> ResultadoAcesso:
    """Registo feito por um administrador (alunos sem consentimento biométrico, esquecimentos, avarias)."""
    if tipo not in ("entrada", "saida"):
        raise ValueError("Tipo inválido.")
    if quando is None:
        return registar_aluno(aluno_id, origem="manual", tipo_forcado=tipo)
    db = get_db()
    db.execute("INSERT INTO acessos (aluno_id, tipo, timestamp, origem) VALUES (?,?,?,'manual')",
               (aluno_id, tipo, utils.iso(quando)))
    db.commit()
    registar_evento("manual", aluno_id, tipo)
    presenca_service.atualizar_dia_aluno(aluno_id, quando.date(), utils.now())
    return ResultadoAcesso("aceite", tipo=tipo, aluno_id=aluno_id, hora=quando.strftime("%H:%M"))
