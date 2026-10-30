"""Testa cada componente SEPARADAMENTE ao montar o circuito (antes de ligar o resto).

  python -m hardware.teste_hardware leds
  python -m hardware.teste_hardware buzzer
  python -m hardware.teste_hardware display
  python -m hardware.teste_hardware rele        # ouve-se um "clique"; SEM o trinco ligado na primeira vez
  python -m hardware.teste_hardware chave       # roda a chave e vê as mudanças (Ctrl+C para sair)
  python -m hardware.teste_hardware camara      # grava teste_camara.jpg
  python -m hardware.teste_hardware tudo
"""
from __future__ import annotations

import sys
import time

from flask_app.config import Config

CFG = {k: getattr(Config, k) for k in dir(Config) if k.isupper()}


def leds():
    from hardware.real import RealHardware
    hw = RealHardware(CFG)
    for v, r in ((1, 0), (0, 1), (1, 1), (0, 0)):
        print(f"verde={v} vermelho={r}")
        hw.leds(bool(v), bool(r)); time.sleep(1)
    hw.fechar()


def buzzer():
    from hardware.real import RealHardware
    hw = RealHardware(CFG)
    for t in ("ok", "aviso", "erro"):
        print("beep", t); hw.beep(t); time.sleep(1.5)
    hw.fechar()


def display():
    from hardware.real import RealHardware
    hw = RealHardware(CFG)
    hw.mostrar("Teste display", "Linha 2 OK"); time.sleep(3)
    hw.mostrar("Ola Maria", "Entrada 08:12"); time.sleep(3)
    hw.fechar()


def rele():
    from hardware.real import RealHardware
    hw = RealHardware(CFG)
    print(f"Relé no GPIO{CFG['PIN_RELE']} (active_high={CFG['RELE_ACTIVE_HIGH']}). Deve ouvir 2 cliques.")
    hw.trinco(True); print("trinco ABERTO"); time.sleep(2)
    hw.trinco(False); print("trinco FECHADO"); time.sleep(1)
    hw.fechar()


def chave():
    from hardware.real import RealHardware
    hw = RealHardware(CFG)
    anterior = None
    print("Rode a chave. Ctrl+C para sair.")
    try:
        while True:
            a = hw.chave_ativa()
            if a != anterior:
                print("chave:", "PORTA LIVRE" if a else "normal"); anterior = a
            time.sleep(0.1)
    except KeyboardInterrupt:
        pass
    hw.fechar()


def camara():
    import cv2
    from hardware.camera import Camera
    cam = Camera(CFG["CAMARA_INDEX"], CFG["CAMARA_LARGURA"], CFG["CAMARA_ALTURA"])
    if not cam.abrir():
        print("Câmara não abriu. Ver `lsusb` e `ls /dev/video*`."); return
    time.sleep(1); cam.descartar(5)
    rgb = cam.ler_rgb()
    cam.fechar()
    if rgb is None:
        print("Sem imagem."); return
    cv2.imwrite("teste_camara.jpg", cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR))
    print("Guardado teste_camara.jpg", rgb.shape)


TESTES = {"leds": leds, "buzzer": buzzer, "display": display, "rele": rele, "chave": chave, "camara": camara}

if __name__ == "__main__":
    alvo = sys.argv[1] if len(sys.argv) > 1 else ""
    if alvo == "tudo":
        for f in (leds, buzzer, display, rele, camara):
            print(f"\n=== {f.__name__} ==="); f()
    elif alvo in TESTES:
        TESTES[alvo]()
    else:
        print(__doc__)
