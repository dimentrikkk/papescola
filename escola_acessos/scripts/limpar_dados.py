"""Retenção de dados (RGPD): apaga eventos da porta antigos e fotos de acesso expiradas.
Agendar diariamente (cron/systemd timer):   python -m scripts.limpar_dados"""
from datetime import timedelta
from pathlib import Path

from flask_app import create_app, utils
from flask_app.db import get_db


def main():
    app = create_app()
    with app.app_context():
        db = get_db()
        limite = utils.iso(utils.now() - timedelta(days=app.config["RETENCAO_EVENTOS_DIAS"]))
        n = db.execute("DELETE FROM eventos_porta WHERE timestamp < ?", (limite,)).rowcount
        fotos = db.execute("SELECT id, foto_path FROM acessos WHERE foto_path IS NOT NULL AND timestamp < ?", (limite,)).fetchall()
        for f in fotos:
            (Path(app.config["UPLOAD_DIR"]) / f["foto_path"]).unlink(missing_ok=True)
            db.execute("UPDATE acessos SET foto_path = NULL WHERE id = ?", (f["id"],))
        db.execute("DELETE FROM login_attempts WHERE created_at < datetime('now', '-30 days')")
        db.commit()
        print(f"Eventos apagados: {n} · Fotos apagadas: {len(fotos)}")


if __name__ == "__main__":
    main()
