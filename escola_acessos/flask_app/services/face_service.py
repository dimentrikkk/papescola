"""Reconhecimento facial.

A biblioteca `face_recognition` (dlib) só é importada quando é preciso, para a aplicação
poder arrancar (e ser testada) em máquinas sem dlib. Os testes usam um backend falso.
"""
from __future__ import annotations

import base64
import io
import re
from dataclasses import dataclass
from typing import Optional, Protocol

import numpy as np
from PIL import Image
from flask import current_app

from ..db import get_db


class FaceBackend(Protocol):
    def encode(self, rgb: np.ndarray, scale: float = 1.0) -> Optional[np.ndarray]: ...


class DlibBackend:
    """face_recognition (dlib HOG + ResNet). `scale` < 1 acelera no Raspberry Pi."""

    def __init__(self):
        import face_recognition  # import tardio
        self._fr = face_recognition

    def encode(self, rgb: np.ndarray, scale: float = 1.0) -> Optional[np.ndarray]:
        img = rgb
        if scale and scale < 1.0:
            h, w = rgb.shape[:2]
            img = np.array(Image.fromarray(rgb).resize((max(1, int(w * scale)), max(1, int(h * scale)))))
        locs = self._fr.face_locations(img, model="hog")
        if not locs:
            return None
        locs.sort(key=lambda b: (b[2] - b[0]) * (b[1] - b[3]), reverse=True)  # maior rosto
        encs = self._fr.face_encodings(img, [locs[0]])
        return encs[0] if encs else None


_backend: Optional[FaceBackend] = None


def get_backend() -> FaceBackend:
    global _backend
    if _backend is None:
        _backend = DlibBackend()
    return _backend


def set_backend(backend: Optional[FaceBackend]) -> None:
    """Permite injetar um backend alternativo (testes)."""
    global _backend
    _backend = backend
    _cache.update(sig=None)


# ------------------------------ imagens ------------------------------
class ImagemInvalida(ValueError):
    pass


def rgb_from_bytes(raw: bytes) -> np.ndarray:
    try:
        return np.array(Image.open(io.BytesIO(raw)).convert("RGB"))
    except Exception as e:  # noqa: BLE001
        raise ImagemInvalida("Imagem inválida ou corrompida.") from e


def rgb_from_data_url(data_url: str) -> np.ndarray:
    if not data_url:
        raise ImagemInvalida("Imagem em falta.")
    m = re.match(r"^data:image/[a-zA-Z0-9.+-]+;base64,(.+)$", data_url, re.S)
    try:
        raw = base64.b64decode(m.group(1) if m else data_url, validate=False)
    except Exception as e:  # noqa: BLE001
        raise ImagemInvalida("Imagem inválida.") from e
    return rgb_from_bytes(raw)


# ------------------------------ codificações ------------------------------
def _to_blob(enc: np.ndarray) -> bytes:
    return np.asarray(enc, dtype=np.float64).tobytes()


def _from_blob(blob: bytes) -> np.ndarray:
    return np.frombuffer(blob, dtype=np.float64)


_cache: dict = {"sig": None, "ids": None, "encs": None}


def _load_encodings():
    """Carrega (e guarda em memória) as codificações de alunos ativos COM consentimento.
    A assinatura barata evita reler o BLOB inteiro a cada frame."""
    db = get_db()
    sig = tuple(db.execute(
        "SELECT COUNT(*), COALESCE(MAX(fe.id),0) FROM face_encodings fe "
        "JOIN alunos a ON a.id = fe.aluno_id "
        "WHERE a.ativo = 1 AND a.consentimento_biometrico = 1"
    ).fetchone())
    if _cache["sig"] != sig:
        rows = db.execute(
            "SELECT fe.aluno_id, fe.encoding FROM face_encodings fe "
            "JOIN alunos a ON a.id = fe.aluno_id "
            "WHERE a.ativo = 1 AND a.consentimento_biometrico = 1"
        ).fetchall()
        _cache["ids"] = np.array([r["aluno_id"] for r in rows], dtype=np.int64)
        _cache["encs"] = np.vstack([_from_blob(r["encoding"]) for r in rows]) if rows else np.empty((0, 128))
        _cache["sig"] = sig
    return _cache["ids"], _cache["encs"]


@dataclass
class Identificacao:
    estado: str                 # ok | sem_rosto | desconhecido | ambiguo | sem_dados
    aluno_id: Optional[int] = None
    distancia: Optional[float] = None


def identify(rgb: np.ndarray, scale: float = 1.0) -> Identificacao:
    enc = get_backend().encode(rgb, scale)
    if enc is None:
        return Identificacao("sem_rosto")
    ids, encs = _load_encodings()
    if len(ids) == 0:
        return Identificacao("sem_dados")

    dists = np.linalg.norm(encs - enc, axis=1)
    melhor: dict[int, float] = {}
    for aid, d in zip(ids.tolist(), dists.tolist()):
        if aid not in melhor or d < melhor[aid]:
            melhor[aid] = d
    ordenados = sorted(melhor.items(), key=lambda kv: kv[1])
    (aid, d1) = ordenados[0]
    cfg = current_app.config
    if d1 > cfg["FACE_TOLERANCE"]:
        return Identificacao("desconhecido", None, d1)
    # Dois alunos muito parecidos → não arriscar (evita registar a pessoa errada)
    if len(ordenados) > 1 and (ordenados[1][1] - d1) < cfg["FACE_MARGEM"] and ordenados[1][1] <= cfg["FACE_TOLERANCE"]:
        return Identificacao("ambiguo", None, d1)
    return Identificacao("ok", aid, d1)


class ConsentimentoEmFalta(Exception):
    pass


class AmostraRejeitada(Exception):
    pass


def adicionar_amostra(aluno_id: int, rgb: np.ndarray) -> int:
    """Regista uma amostra facial. Só com consentimento registado. Devolve o nº de amostras."""
    db = get_db()
    cfg = current_app.config
    al = db.execute("SELECT id, consentimento_biometrico FROM alunos WHERE id = ?", (aluno_id,)).fetchone()
    if not al:
        raise AmostraRejeitada("Aluno não encontrado.")
    if not al["consentimento_biometrico"]:
        raise ConsentimentoEmFalta("Registe primeiro o consentimento biométrico (encarregado de educação).")
    n = db.execute("SELECT COUNT(*) FROM face_encodings WHERE aluno_id = ?", (aluno_id,)).fetchone()[0]
    if n >= cfg["MAX_FACE_SAMPLES"]:
        raise AmostraRejeitada(f"Já existem {n} amostras (máximo {cfg['MAX_FACE_SAMPLES']}). Apague para recomeçar.")
    enc = get_backend().encode(rgb, 1.0)
    if enc is None:
        raise AmostraRejeitada("Nenhum rosto detetado. Tente outra vez com boa luz.")

    # Impede associar o mesmo rosto a dois alunos
    ids, encs = _load_encodings()
    if len(ids):
        dists = np.linalg.norm(encs - enc, axis=1)
        for aid, d in zip(ids.tolist(), dists.tolist()):
            if aid != aluno_id and d <= cfg["FACE_TOLERANCE"]:
                outro = db.execute("SELECT nome_completo FROM alunos WHERE id = ?", (aid,)).fetchone()
                raise AmostraRejeitada(f"Este rosto é muito parecido com o de {outro['nome_completo']}. Verifique o aluno.")
    db.execute("INSERT INTO face_encodings (aluno_id, encoding) VALUES (?, ?)", (aluno_id, _to_blob(enc)))
    db.commit()
    return n + 1


def apagar_amostras(aluno_id: int) -> None:
    db = get_db()
    db.execute("DELETE FROM face_encodings WHERE aluno_id = ?", (aluno_id,))
    db.commit()


def contar_amostras(aluno_id: int) -> int:
    return get_db().execute("SELECT COUNT(*) FROM face_encodings WHERE aluno_id = ?", (aluno_id,)).fetchone()[0]
