"""Painel de administração (direção/secretaria). Dividido por temas, todos no mesmo blueprint."""
from flask import Blueprint

bp = Blueprint("admin", __name__, url_prefix="/admin")

# os módulos registam as suas rotas em `bp` ao serem importados
from . import alunos, estrutura, horarios, assiduidade, relatorios  # noqa: E402,F401
