"""Configuración de Janus. Todo sale de variables de entorno o de .env."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"


def _load_dotenv() -> None:
    """Lee .env sin dependencias. Las variables ya presentes no se sobreescriben."""
    env_file = ROOT / ".env"
    if not env_file.exists():
        return
    for raw in env_file.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


_load_dotenv()

# Identificadores de modelo. Claude Opus 5.5 es el cerebro por defecto.
CLAUDE_MODEL = os.getenv("JANUS_CLAUDE_MODEL", "claude-opus-5-5")
GPT_MODEL = os.getenv("JANUS_GPT_MODEL", "gpt-5.1")

DEFAULT_BRAIN = os.getenv("JANUS_BRAIN", "claude")  # "claude" | "gpt"
HOST = os.getenv("JANUS_HOST", "127.0.0.1")
PORT = int(os.getenv("JANUS_PORT", "8700"))
TZ = os.getenv("JANUS_TZ", "Europe/Madrid")

# Voz: "browser" usa el reconocimiento del navegador (sin coste, sin instalar nada).
# "openai" transcribe con Whisper y sintetiza con TTS en el servidor.
VOICE_MODE = os.getenv("JANUS_VOICE", "browser")


@dataclass(frozen=True)
class Brain:
    """Un cerebro disponible, tal y como lo ve la interfaz."""

    id: str
    label: str
    model: str
    available: bool
    reason: str = ""


def brains() -> list[Brain]:
    """Cerebros que realmente se pueden usar ahora mismo."""
    has_claude = bool(os.getenv("ANTHROPIC_API_KEY") or os.getenv("ANTHROPIC_AUTH_TOKEN"))
    has_gpt = bool(os.getenv("OPENAI_API_KEY"))
    return [
        Brain(
            "claude",
            "Claude",
            CLAUDE_MODEL,
            has_claude,
            "" if has_claude else "Falta ANTHROPIC_API_KEY en .env",
        ),
        Brain(
            "gpt",
            "GPT",
            GPT_MODEL,
            has_gpt,
            "" if has_gpt else "Falta OPENAI_API_KEY en .env",
        ),
    ]
