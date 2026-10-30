"""Captura de imagem. Usa OpenCV (V4L2 no Raspberry Pi). Devolve frames RGB (numpy)."""
from __future__ import annotations

import logging
import os
import sys

import numpy as np

log = logging.getLogger("hardware.camera")


class Camera:
    """`fonte` pode ser: índice da webcam (0), caminho de um vídeo ou de uma imagem (para ensaios no PC)."""

    def __init__(self, fonte=0, largura: int = 640, altura: int = 480):
        self.fonte, self.largura, self.altura = fonte, largura, altura
        self._cap = None
        self._imagem = None

    def abrir(self) -> bool:
        import cv2
        self.fechar()
        if isinstance(self.fonte, str) and os.path.isfile(self.fonte) and self.fonte.lower().endswith((".jpg", ".jpeg", ".png")):
            img = cv2.imread(self.fonte)
            if img is None:
                return False
            self._imagem = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
            return True
        backend = cv2.CAP_V4L2 if sys.platform.startswith("linux") and isinstance(self.fonte, int) else cv2.CAP_ANY
        self._cap = cv2.VideoCapture(self.fonte, backend)
        if not self._cap.isOpened():
            log.error("Não foi possível abrir a câmara %s", self.fonte)
            self._cap = None
            return False
        if isinstance(self.fonte, int):
            self._cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.largura)
            self._cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.altura)
            self._cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)   # frames "frescos", sem atraso acumulado
        return True

    def ler_rgb(self):
        import cv2
        if self._imagem is not None:
            return self._imagem.copy()
        if self._cap is None:
            return None
        ok, frame = self._cap.read()
        if not ok or frame is None:
            return None
        return cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)

    def descartar(self, n: int = 3) -> None:
        """Deita fora frames antigos acumulados no buffer enquanto o programa esteve ocupado."""
        if self._cap is not None:
            for _ in range(n):
                self._cap.grab()

    def fechar(self) -> None:
        if self._cap is not None:
            self._cap.release()
            self._cap = None
        self._imagem = None
