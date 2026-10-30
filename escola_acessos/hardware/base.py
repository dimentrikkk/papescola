"""Interface do hardware da portaria. O resto do código só conhece esta classe, por isso
a mesma aplicação corre no PC (MockHardware) e no Raspberry Pi (RealHardware)."""
from __future__ import annotations

from abc import ABC, abstractmethod


class Hardware(ABC):
    # ---- primitivas (cada implementação trata do seu dispositivo) ----
    @abstractmethod
    def mostrar(self, linha1: str, linha2: str = "") -> None:
        """Escreve duas linhas no display."""

    @abstractmethod
    def leds(self, verde: bool, vermelho: bool) -> None: ...

    @abstractmethod
    def beep(self, tipo: str) -> None:
        """tipo: 'ok' (1 beep curto), 'aviso' (2 beeps), 'erro' (beep longo)."""

    @abstractmethod
    def trinco(self, aberto: bool) -> None: ...

    @abstractmethod
    def chave_ativa(self) -> bool:
        """True se o switch com chave está na posição 'porta livre'."""

    def fechar(self) -> None:
        """Liberta os GPIO. Garante o trinco no estado seguro."""

    # ---- comportamentos de alto nível, comuns às duas implementações ----
    def pronto(self, linha1: str = "Escola Segura", linha2: str = "Aproxime-se") -> None:
        self.leds(False, False)
        self.mostrar(linha1, linha2)

    def sinalizar(self, res) -> None:
        """Apresenta o resultado de um acesso (ResultadoAcesso)."""
        if res.sucesso:
            self.leds(True, False)
        else:
            self.leds(False, True)
        self.beep(res.som)
        self.mostrar(res.linha1, res.linha2)
        if res.abrir:
            self.trinco(True)
