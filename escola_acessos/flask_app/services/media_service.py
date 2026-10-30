"""Fotos de perfil: validadas com PIL, redimensionadas e reguardadas como JPEG (remove EXIF)."""
from __future__ import annotations

import io
import uuid
from pathlib import Path

from PIL import Image
from flask import current_app

from .face_service import ImagemInvalida


def guardar_avatar(aluno_id: int, raw: bytes) -> str:
    try:
        img = Image.open(io.BytesIO(raw))
        img.verify()
        img = Image.open(io.BytesIO(raw)).convert("RGB")
    except Exception as e:  # noqa: BLE001
        raise ImagemInvalida("Ficheiro não é uma imagem válida.") from e
    img.thumbnail((512, 512))
    pasta = Path(current_app.config["UPLOAD_DIR"])
    pasta.mkdir(parents=True, exist_ok=True)
    nome = f"avatar_{aluno_id}_{uuid.uuid4().hex[:8]}.jpg"
    img.save(pasta / nome, "JPEG", quality=85)
    return nome


def apagar_ficheiro(nome: str | None) -> None:
    if not nome or "/" in nome or "\\" in nome:
        return
    try:
        (Path(current_app.config["UPLOAD_DIR"]) / nome).unlink(missing_ok=True)
    except OSError:
        pass
