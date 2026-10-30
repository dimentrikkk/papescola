"""Hardware real do Raspberry Pi 4 (gpiozero + display I2C).

Ligações por defeito (numeração BCM, ver README):
  LED verde GPIO17 · LED vermelho GPIO27 · Buzzer GPIO22 · Relé IN GPIO23 · Chave GPIO24→GND
  Display I2C: SDA GPIO2, SCL GPIO3 (endereço normalmente 0x27 num LCD, 0x3C num OLED)
"""
from __future__ import annotations

import logging
import time

from .base import Hardware

log = logging.getLogger("hardware.real")


# ------------------------------ displays ------------------------------
class _SemDisplay:
    def escrever(self, l1: str, l2: str): ...
    def fechar(self): ...


class _LcdI2C:
    """LCD de caracteres (HD44780 com 'mochila' PCF8574). Biblioteca: RPLCD."""

    def __init__(self, cfg):
        from RPLCD.i2c import CharLCD
        self.cols, self.rows = cfg["DISPLAY_COLS"], cfg["DISPLAY_ROWS"]
        self.lcd = CharLCD("PCF8574", cfg["DISPLAY_I2C_ADDR"], port=cfg["DISPLAY_I2C_PORT"],
                           cols=self.cols, rows=self.rows, charmap="A00", auto_linebreaks=False)
        self.lcd.clear()

    def escrever(self, l1, l2):
        self.lcd.clear()
        self.lcd.cursor_pos = (0, 0)
        self.lcd.write_string(l1[: self.cols].ljust(self.cols))
        if self.rows > 1:
            self.lcd.cursor_pos = (1, 0)
            self.lcd.write_string(l2[: self.cols].ljust(self.cols))

    def fechar(self):
        try:
            self.lcd.clear()
            self.lcd.close(clear=True)
        except Exception:  # noqa: BLE001
            pass


class _OledI2C:
    """OLED gráfico SSD1306 128x64 (ou 128x32). Biblioteca: luma.oled."""

    def __init__(self, cfg):
        from luma.core.interface.serial import i2c
        from luma.oled.device import ssd1306
        self.device = ssd1306(i2c(port=cfg["DISPLAY_I2C_PORT"], address=cfg["DISPLAY_I2C_ADDR"]))

    def escrever(self, l1, l2):
        from luma.core.render import canvas
        from PIL import ImageFont
        font = ImageFont.load_default()
        with canvas(self.device) as draw:
            draw.text((2, 4), l1, font=font, fill="white")
            draw.text((2, 26), l2, font=font, fill="white")

    def fechar(self):
        try:
            self.device.cleanup()
        except Exception:  # noqa: BLE001
            pass


def _criar_display(cfg):
    tipo = cfg["DISPLAY_TIPO"]
    try:
        if tipo == "lcd":
            return _LcdI2C(cfg)
        if tipo == "oled":
            return _OledI2C(cfg)
    except Exception as e:  # noqa: BLE001
        # Um display avariado não deve impedir a porta de funcionar
        log.error("Display I2C indisponível (%s). A continuar sem display. Verifique `i2cdetect -y 1`.", e)
    return _SemDisplay()


# ------------------------------ hardware ------------------------------
class RealHardware(Hardware):
    def __init__(self, cfg):
        from gpiozero import LED, Buzzer, OutputDevice, Button

        self.cfg = cfg
        self.fail_safe = cfg["TRINCO_MODO"] == "energiza_para_trancar"
        self._verde = LED(cfg["PIN_LED_VERDE"])
        self._vermelho = LED(cfg["PIN_LED_VERMELHO"])
        self._buzzer = Buzzer(cfg["PIN_BUZZER"])
        # initial_value: trinco TRANCADO ao arrancar
        self._rele = OutputDevice(cfg["PIN_RELE"], active_high=cfg["RELE_ACTIVE_HIGH"], initial_value=self.fail_safe)
        self._chave = Button(cfg["PIN_CHAVE"], pull_up=True)   # fechado = ligado ao GND = pressionado
        self._display = _criar_display(cfg)
        self._ultimo_texto = None
        self.trinco(False)

    def mostrar(self, linha1, linha2=""):
        if (linha1, linha2) == self._ultimo_texto:  # evita piscar o LCD
            return
        self._ultimo_texto = (linha1, linha2)
        try:
            self._display.escrever(linha1, linha2)
        except Exception as e:  # noqa: BLE001
            log.error("Falha a escrever no display: %s", e)

    def leds(self, verde, vermelho):
        self._verde.value = 1 if verde else 0
        self._vermelho.value = 1 if vermelho else 0

    def beep(self, tipo):
        if tipo == "ok":
            self._buzzer.beep(on_time=0.12, off_time=0.05, n=1, background=True)
        elif tipo == "aviso":
            self._buzzer.beep(on_time=0.12, off_time=0.12, n=2, background=True)
        else:
            self._buzzer.beep(on_time=0.7, off_time=0.1, n=1, background=True)

    def trinco(self, aberto):
        # energiza_para_abrir : relé ligado = aberto
        # energiza_para_trancar (fail-safe): relé ligado = trancado; sem corrente o trinco abre
        ligar = (not aberto) if self.fail_safe else aberto
        self._rele.on() if ligar else self._rele.off()

    def chave_ativa(self):
        return bool(self._chave.is_pressed)

    def fechar(self):
        try:
            self.trinco(False)
            self.leds(False, False)
        finally:
            self._display.fechar()
            for dev in (self._verde, self._vermelho, self._buzzer, self._rele, self._chave):
                try:
                    dev.close()
                except Exception:  # noqa: BLE001
                    pass
