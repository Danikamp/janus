"""Modo programador de Janus.

Usa el Claude Agent SDK (el motor de Claude Code como libreria) para que Janus
pueda leer y escribir codigo de verdad en un proyecto. Nunca se entra aqui sin
que el usuario haya aprobado la tarea explicitamente en la interfaz.

Dos cercos de seguridad:
  1. La tarea tiene que estar en estado 'aprobada' antes de llegar aqui.
  2. `cwd` limita al agente al directorio del proyecto, y `can_use_tool` veta
     por defecto todo lo que ejecute comandos.
"""
from __future__ import annotations

import asyncio
import os
from pathlib import Path
from typing import Any, AsyncIterator

from . import config, store

# Herramientas que el agente puede usar sin preguntar: leer y escribir ficheros
# dentro del proyecto. Nada que ejecute procesos.
HERRAMIENTAS_SEGURAS = {
    "Read",
    "Write",
    "Edit",
    "Glob",
    "Grep",
    "NotebookEdit",
    "TodoWrite",
}


def resolver_cli() -> str | None:
    """Localiza el ejecutable de Claude Code.

    Busca por orden: la variable JANUS_CLAUDE_CLI, el PATH, y por ultimo el
    binario que trae la extension de VS Code (cuya ruta cambia en cada
    actualizacion, asi que se coge siempre la version mas alta).
    """
    explicito = os.getenv("JANUS_CLAUDE_CLI")
    if explicito and Path(explicito).exists():
        return explicito

    from shutil import which

    for nombre in ("claude", "claude.cmd", "claude.exe"):
        encontrado = which(nombre)
        if encontrado:
            return encontrado

    extensiones = Path.home() / ".vscode" / "extensions"
    candidatos = sorted(
        extensiones.glob("anthropic.claude-code-*/resources/native-binary/claude.exe")
    )
    return str(candidatos[-1]) if candidatos else None


def directorio_codigo(pid: str) -> Path:
    """Donde vive el codigo de un proyecto.

    Si el proyecto declara `repo:` en su frontmatter, se usa esa ruta. Si no, se
    crea una carpeta `codigo/` junto a su markdown.
    """
    meta, _ = store.parse_md(store.read_project(pid))
    repo = (meta.get("repo") or "").strip()
    if repo:
        ruta = Path(repo).expanduser()
        if ruta.exists():
            return ruta
    destino = store.PROJECTS_DIR / pid / "codigo"
    destino.mkdir(parents=True, exist_ok=True)
    return destino


def _prompt(task: dict[str, Any], carpeta: Path) -> str:
    return f"""\
Trabajas dentro del proyecto '{task["proyecto"]}' de Janus, en {carpeta}.

## Tarea aprobada por el usuario

{task["descripcion"]}

## Plan acordado

{task.get("plan") or "(sin plan detallado; usa tu criterio y explica lo que haces)"}

## Reglas

- Limitate a esta tarea. Si ves otros problemas, mencionalos al final pero no los toques.
- No puedes ejecutar comandos: no tienes Bash. Si un paso lo necesita (instalar
  dependencias, lanzar tests), escribelo como instruccion al final para que el
  usuario lo ejecute el mismo.
- Al terminar, resume en pocas lineas que ficheros has creado o cambiado y por que.
- Escribe en espanol.
"""


async def ejecutar(task_id: str, permitir_bash: bool = False) -> AsyncIterator[dict[str, Any]]:
    """Ejecuta una tarea aprobada. Emite los mismos eventos que brain.stream."""
    task = store.task_get(task_id)
    if task is None:
        yield {"type": "error", "mensaje": f"No existe la tarea {task_id!r}"}
        return
    if task["estado"] != "aprobada":
        yield {
            "type": "error",
            "mensaje": f"La tarea {task_id} esta en estado '{task['estado']}', no aprobada.",
        }
        return

    cli = resolver_cli()
    if cli is None:
        yield {
            "type": "error",
            "mensaje": (
                "No encuentro el ejecutable de Claude Code, que es el motor del modo "
                "programador. Instalalo con: npm install -g @anthropic-ai/claude-code "
                "(o pon la ruta en JANUS_CLAUDE_CLI dentro de .env)."
            ),
        }
        return

    try:
        carpeta = directorio_codigo(task["proyecto"])
    except FileNotFoundError as exc:
        yield {"type": "error", "mensaje": str(exc)}
        return

    from claude_agent_sdk import (
        AssistantMessage,
        ClaudeAgentOptions,
        PermissionResultAllow,
        PermissionResultDeny,
        ResultMessage,
        TextBlock,
        ThinkingBlock,
        ToolUseBlock,
        query,
    )

    permitidas = set(HERRAMIENTAS_SEGURAS)
    if permitir_bash:
        permitidas.add("Bash")

    async def puerta(nombre: str, entrada: dict[str, Any], contexto: Any):
        """Red de seguridad: todo lo que no este en la lista blanca se deniega.

        El SDK avisa de que no llama a este callback para las herramientas que
        ya estan en `allowed_tools` (las aprueba antes). Es justo lo que
        queremos: las seguras pasan solas y aqui solo cae lo demas, como Bash.
        """
        if nombre in permitidas:
            return PermissionResultAllow()
        return PermissionResultDeny(
            message=(
                f"La herramienta '{nombre}' no esta permitida en este modo. "
                "Describe el paso en texto y el usuario lo hara a mano."
            )
        )

    opciones = ClaudeAgentOptions(
        cwd=str(carpeta),
        cli_path=cli,
        model=config.CLAUDE_MODEL,
        effort="high",
        allowed_tools=sorted(permitidas),
        permission_mode="acceptEdits",
        can_use_tool=puerta,
        max_turns=40,
        setting_sources=None,  # no heredar CLAUDE.md ni ajustes del usuario
    )

    store.task_update(task_id, estado="en_curso")
    yield {"type": "tool", "nombre": "programar", "args": {"carpeta": str(carpeta)}}

    registro: list[str] = []
    try:
        async for mensaje in query(prompt=_prompt(task, carpeta), options=opciones):
            if isinstance(mensaje, AssistantMessage):
                for bloque in mensaje.content:
                    if isinstance(bloque, TextBlock):
                        yield {"type": "texto", "texto": bloque.text}
                        registro.append(bloque.text)
                    elif isinstance(bloque, ThinkingBlock):
                        yield {"type": "pensando", "texto": bloque.thinking}
                    elif isinstance(bloque, ToolUseBlock):
                        yield {
                            "type": "tool",
                            "nombre": bloque.name,
                            "args": _resumen_args(bloque.input),
                        }
            elif isinstance(mensaje, ResultMessage):
                coste = getattr(mensaje, "total_cost_usd", None)
                yield {
                    "type": "tool_fin",
                    "nombre": "programar",
                    "resultado": {
                        "turnos": getattr(mensaje, "num_turns", None),
                        "coste_usd": coste,
                    },
                }
    except asyncio.CancelledError:
        # El navegador cerro la conexion a mitad. Sin esto la tarea se quedaria
        # en 'en_curso' para siempre y no se podria reintentar.
        store.task_update(task_id, estado="interrumpida")
        raise
    except Exception as exc:  # noqa: BLE001 - el fallo tiene que llegar a la interfaz
        store.task_update(task_id, estado="fallida", error=f"{type(exc).__name__}: {exc}")
        yield {"type": "error", "mensaje": f"El modo programador fallo: {exc}"}
        return

    resumen = "\n".join(registro).strip()
    store.task_update(task_id, estado="hecha", resumen=resumen)
    store.append_project_log(
        task["proyecto"], f"[{task_id}] {task['descripcion']} — hecho por Janus."
    )
    yield {"type": "fin", "uso": {"tarea": task_id, "estado": "hecha"}}


def _resumen_args(entrada: dict[str, Any] | None) -> dict[str, Any]:
    """Acorta los argumentos para la interfaz: el contenido de un fichero no
    aporta nada en una linea de log."""
    resumen = {}
    for clave, valor in (entrada or {}).items():
        texto = str(valor)
        resumen[clave] = texto if len(texto) <= 120 else texto[:120] + "..."
    return resumen
