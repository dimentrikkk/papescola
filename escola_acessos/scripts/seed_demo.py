"""Dados FICTÍCIOS para demonstração (nunca usar dados reais de alunos na demo).

  python -m scripts.seed_demo            # cria a demo (não faz nada se já existirem alunos)
  python -m scripts.seed_demo --forcar   # acrescenta mesmo assim

Contas criadas:  professor1@escola.pt / Professor123   ·   aluno1001@escola.pt / Aluno1234
"""
from __future__ import annotations

import random
import sys
from datetime import datetime, time, timedelta

from flask_app import create_app, utils
from flask_app.db import get_db
from flask_app.services import horario_service, presenca_service
from flask_app.services.passwords import hash_password

NOMES = ["Ana Ribeiro", "Bruno Carvalho", "Carla Mendes", "Diogo Pinto", "Eva Sousa", "Filipe Gomes", "Graça Lopes",
         "Hugo Faria", "Inês Matos", "João Teixeira", "Kátia Rocha", "Luís Moreira", "Marta Nunes", "Nuno Correia",
         "Olga Pires", "Pedro Lima", "Rita Duarte", "Sérgio Azevedo", "Tânia Cardoso", "Vasco Monteiro"]
HORARIOS = {"PGI24": ("08:30", "16:30"), "PGI25": ("09:00", "17:30")}   # entrada, saída (segunda a sexta)


def main():
    app = create_app()
    rnd = random.Random(2026)
    with app.app_context():
        db = get_db()
        if db.execute("SELECT COUNT(*) FROM alunos").fetchone()[0] and "--forcar" not in sys.argv:
            print("Já existem alunos. Use --forcar para acrescentar."); return

        db.execute("INSERT OR IGNORE INTO cursos (nome, descricao) VALUES ('Técnico de Gestão e Programação de Sistemas Informáticos', 'Curso profissional (demo)')")
        curso = db.execute("SELECT id FROM cursos LIMIT 1").fetchone()["id"]
        profs = []
        for i, nome in enumerate(["Prof. Marta Albuquerque", "Prof. Rui Barbosa"], start=1):
            db.execute("INSERT OR IGNORE INTO utilizadores (nome, email, password_hash, papel) VALUES (?,?,?, 'professor')",
                       (nome, f"professor{i}@escola.pt", hash_password("Professor123")))
            profs.append(db.execute("SELECT id FROM utilizadores WHERE email = ?", (f"professor{i}@escola.pt",)).fetchone()["id"])
        for nome, diretor in zip(HORARIOS, profs):
            db.execute("INSERT OR IGNORE INTO turmas (nome, curso_id, ano_letivo, diretor_turma_id) VALUES (?,?, '2026/2027', ?)", (nome, curso, diretor))
        db.commit()
        turmas = {r["nome"]: r["id"] for r in db.execute("SELECT id, nome FROM turmas")}
        for nome, (ent, sai) in HORARIOS.items():
            horario_service.guardar_horario(turmas[nome], {d: (ent, sai) for d in range(5)})

        alunos = []
        for i, nome in enumerate(NOMES):
            n = 1001 + i
            turma = list(HORARIOS)[i % 2]
            sem_consent = i % 9 == 8
            db.execute(
                """INSERT OR IGNORE INTO alunos (numero_processo, nome_completo, email, turma_id, encarregado_nome, encarregado_email,
                       consentimento_biometrico, consentimento_data, password_hash, must_change_password)
                   VALUES (?,?,?,?,?,?,?,?,?,0)""",
                (str(n), nome, f"aluno{n}@escola.pt", turmas[turma], f"Encarregado de {nome.split()[0]}", f"encarregado{n}@exemplo.pt",
                 0 if sem_consent else 1, None if sem_consent else utils.iso(utils.now()), hash_password("Aluno1234")))
            alunos.append(db.execute("SELECT id, turma_id FROM alunos WHERE numero_processo = ?", (str(n),)).fetchone())
        db.commit()

        # Histórico dos últimos 20 dias: chegadas, atrasos e algumas faltas
        hoje = utils.today()
        for delta in range(20, 0, -1):
            d = hoje - timedelta(days=delta)
            if d.weekday() > 4:
                continue
            for al in alunos:
                hor = horario_service.horario_do_dia(al["turma_id"], d.weekday())
                r = rnd.random()
                if not hor or r < 0.06:                       # falta o dia todo
                    continue
                h, m = map(int, hor["hora_entrada"].split(":"))
                inicio = datetime.combine(d, time(h, m))
                chegada = inicio - timedelta(minutes=rnd.randint(2, 25))
                if r < 0.20:                                  # chega atrasado
                    chegada = inicio + timedelta(minutes=rnd.randint(8, 45))
                h, m = map(int, hor["hora_saida"].split(":"))
                saida = datetime.combine(d, time(h, m)) + timedelta(minutes=rnd.randint(1, 12))
                if 0.20 <= r < 0.23:                          # sai mais cedo
                    saida -= timedelta(minutes=rnd.randint(60, 150))
                db.execute("INSERT INTO acessos (aluno_id, tipo, timestamp, origem) VALUES (?, 'entrada', ?, 'porteiro')", (al["id"], utils.iso(chegada)))
                db.execute("INSERT INTO acessos (aluno_id, tipo, timestamp, origem) VALUES (?, 'saida', ?, 'porteiro')", (al["id"], utils.iso(saida)))
            db.commit()
        n = presenca_service.recalcular_periodo(hoje - timedelta(days=20), hoje - timedelta(days=1))
        print(f"Demo criada: {len(alunos)} alunos, {len(turmas)} turmas, {n} presenças calculadas.")
        print("Professor: professor1@escola.pt / Professor123 · Aluno: aluno1001@escola.pt / Aluno1234")


if __name__ == "__main__":
    main()
