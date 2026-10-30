"""Envia a fila de emails aos encarregados (precisa das variáveis SMTP_*).

  python -m scripts.enviar_emails          # uma vez (para cron)
  python -m scripts.enviar_emails --loop   # fica a correr e envia de minuto a minuto
(O porteiro no Raspberry Pi já faz isto sozinho quando o SMTP está configurado.)"""
import sys
import time

from flask_app import create_app
from flask_app.services import notification_service


def main():
    app = create_app()
    while True:
        with app.app_context():
            print(notification_service.enviar_pendentes(), flush=True)
        if "--loop" not in sys.argv:
            break
        time.sleep(60)


if __name__ == "__main__":
    main()
