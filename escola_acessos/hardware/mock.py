"""Hardware simulado: escreve na consola. Permite desenvolver e testar sem o Raspberry Pi."""
from __future__ import annotations

import logging

from .base import Hardware

log = logging.getLogger("hardware.mock")


class MockHardware(Hardware):
    def __init__(self, cols: int = 16, rows: int = 2, verbose: bool = True):
        self.cols, self.rows, self.verbose = cols, rows, verbose
        self.chave = False             # os testes/simulação podem mudar isto
        self.estado_trinco = False
        self.estado_leds = (False, False)
        self.display = ("", "")
        self.eventos: list[tuple] = []  # histórico para os testes

    def _p(self, *a):
        if self.verbose:
            print("[HW]", *a, flush=True)

    def mostrar(self, linha1, linha2=""):
        self.display = (linha1[: self.cols], linha2[: self.cols])
        self.eventos.append(("display", *self.display))
        if self.verbose:
            w = self.cols
            print(f"[HW] ┌{'─' * w}┐\n[HW] │{self.display[0]:<{w}}│\n[HW] │{self.display[1]:<{w}}│\n[HW] └{'─' * w}┘", flush=True)

    def leds(self, verde, vermelho):
        self.estado_leds = (verde, vermelho)
        self.eventos.append(("leds", verde, vermelho))
        self._p(f"LED verde={'ON' if verde else 'off'}  vermelho={'ON' if vermelho else 'off'}")

    def beep(self, tipo):
        self.eventos.append(("beep", tipo))
        self._p(f"BUZZER {tipo}")

    def trinco(self, aberto):
        self.estado_trinco = aberto
        self.eventos.append(("trinco", aberto))
        self._p("TRINCO", "ABERTO" if aberto else "fechado")

    def chave_ativa(self):
        return self.chave
