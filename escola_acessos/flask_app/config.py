"""Configuração central. Tudo o que muda entre PC de desenvolvimento e Raspberry Pi
é lido de variáveis de ambiente (ver .env.example)."""
import os
import secrets
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


def _bool(name: str, default: bool) -> bool:
    v = os.environ.get(name)
    return default if v is None else v.strip().lower() in ("1", "true", "yes", "sim", "on")


def _int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except ValueError:
        return default


def _float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, default))
    except ValueError:
        return default


def _load_secret_key(data_dir: Path) -> str:
    """SESSION_SECRET do ambiente, ou um segredo aleatório persistido em data/.secret_key."""
    env = os.environ.get("SESSION_SECRET")
    if env:
        return env
    f = data_dir / ".secret_key"
    if f.exists():
        return f.read_text().strip()
    data_dir.mkdir(parents=True, exist_ok=True)
    key = secrets.token_hex(32)
    f.write_text(key)
    try:
        f.chmod(0o600)
    except OSError:
        pass
    return key


_DATA = Path(os.environ.get("DATA_DIR", BASE_DIR / "data"))


class Config:
    ESCOLA_NOME = os.environ.get("ESCOLA_NOME", "Escola Profissional Profitecla")
    ESCOLA_CONTACTO = os.environ.get("ESCOLA_CONTACTO", "")   # ex.: secretaria@profitecla.pt · 2xx xxx xxx (vai no fim dos emails)

    # ---- Armazenamento ----
    DATA_DIR = str(_DATA)
    DATABASE_PATH = os.environ.get("DATABASE_PATH", str(_DATA / "escola.db"))
    UPLOAD_DIR = os.environ.get("UPLOAD_DIR", str(_DATA / "uploads"))
    MAX_CONTENT_LENGTH = 8 * 1024 * 1024

    # ---- Sessões / segurança ----
    SECRET_KEY = _load_secret_key(_DATA)
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    SESSION_COOKIE_SECURE = _bool("COOKIE_SECURE", False)  # True se servir por HTTPS
    PERMANENT_SESSION_LIFETIME = 60 * 60 * 8
    MAX_LOGIN_FALHAS = 5
    JANELA_BLOQUEIO_MIN = 15

    # Conta admin inicial (só criada se não existir nenhum admin)
    ADMIN_EMAIL = os.environ.get("ADMIN_EMAIL", "admin@escola.pt")
    ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD")  # None => gera uma aleatória e mostra no arranque
    ADMIN_NOME = "Administrador"

    # ---- Reconhecimento facial ----
    FACE_TOLERANCE = _float("FACE_TOLERANCE", 0.5)   # menor = mais estrito
    FACE_MARGEM = _float("FACE_MARGEM", 0.04)        # diferença mínima para o 2.º candidato
    FACE_SCALE = _float("FACE_SCALE", 0.5)           # redução da imagem no porteiro (velocidade no Pi)
    MIN_FACE_SAMPLES = 3
    MAX_FACE_SAMPLES = 5

    # ---- Regras de assiduidade (por dia: só contam a 1.ª entrada e a última saída) ----
    TOLERANCIA_ATRASO_MIN = _int("TOLERANCIA_ATRASO_MIN", 5)        # minutos após a hora de entrada ainda contados como presença
    FALTA_APOS_MIN = _int("FALTA_APOS_MIN", 30)                      # sem entrada X min após a hora prevista → falta (e aviso ao EE)
    SAIDA_ANTECIPADA_TOL_MIN = _int("SAIDA_ANTECIPADA_TOL_MIN", 5)  # sair mais cedo que isto = saída antecipada
    AVISAR_EE_ATRASO = _bool("AVISAR_EE_ATRASO", True)              # email ao encarregado de educação (EE)
    AVISAR_EE_FALTA = _bool("AVISAR_EE_FALTA", True)
    AVISAR_SAIDA_ANTECIPADA = _bool("AVISAR_SAIDA_ANTECIPADA", False)
    COOLDOWN_SEGUNDOS = _int("COOLDOWN_SEGUNDOS", 30)               # evita alternar entrada/saída em duplicado
    ABRIR_NA_SAIDA = _bool("ABRIR_NA_SAIDA", True)

    # ---- Privacidade (RGPD) ----
    GUARDAR_FOTOS_ACESSO = _bool("GUARDAR_FOTOS_ACESSO", False)     # por defeito NÃO se guardam fotos
    RETENCAO_EVENTOS_DIAS = _int("RETENCAO_EVENTOS_DIAS", 90)
    KIOSK_WEB_ENABLED = _bool("KIOSK_WEB_ENABLED", True)            # pôr a False em produção

    # ---- Email para encarregados de educação ----
    SMTP_HOST = os.environ.get("SMTP_HOST")
    SMTP_PORT = _int("SMTP_PORT", 587)
    SMTP_USER = os.environ.get("SMTP_USER")
    SMTP_PASSWORD = os.environ.get("SMTP_PASSWORD")
    SMTP_FROM = os.environ.get("SMTP_FROM", "no-reply@escola.pt")
    SMTP_TLS = _bool("SMTP_TLS", True)

    # ---- Hardware (Raspberry Pi) ----
    HARDWARE_MODO = os.environ.get("HARDWARE_MODO", "mock")        # mock | real
    CAMARA_INDEX = _int("CAMARA_INDEX", 0)
    CAMARA_LARGURA = _int("CAMARA_LARGURA", 640)
    CAMARA_ALTURA = _int("CAMARA_ALTURA", 480)
    INTERVALO_FRAME_S = _float("INTERVALO_FRAME_S", 0.4)
    MOSTRAR_RESULTADO_S = _float("MOSTRAR_RESULTADO_S", 3.0)

    PIN_LED_VERDE = _int("PIN_LED_VERDE", 17)       # numeração BCM
    PIN_LED_VERMELHO = _int("PIN_LED_VERMELHO", 27)
    PIN_BUZZER = _int("PIN_BUZZER", 22)
    PIN_RELE = _int("PIN_RELE", 23)
    PIN_CHAVE = _int("PIN_CHAVE", 24)               # switch com chave (liga ao GND)
    RELE_ACTIVE_HIGH = _bool("RELE_ACTIVE_HIGH", False)  # muitos módulos relé são ativos em baixo
    TRINCO_MODO = os.environ.get("TRINCO_MODO", "energiza_para_abrir")  # ou energiza_para_trancar (fail-safe)
    TRINCO_SEGUNDOS = _float("TRINCO_SEGUNDOS", 4.0)

    DISPLAY_TIPO = os.environ.get("DISPLAY_TIPO", "lcd")            # lcd | oled | none
    DISPLAY_I2C_PORT = _int("DISPLAY_I2C_PORT", 1)
    DISPLAY_I2C_ADDR = int(os.environ.get("DISPLAY_I2C_ADDR", "0x27"), 16)
    DISPLAY_COLS = _int("DISPLAY_COLS", 16)
    DISPLAY_ROWS = _int("DISPLAY_ROWS", 2)
