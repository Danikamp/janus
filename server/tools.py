"""Las herramientas de Janus.

Un registro unico, independiente del proveedor. Cada herramienta declara su
esquema JSON una sola vez; brain.py lo traduce al formato de Claude o de GPT.
El esquema que se escribe aqui es el que la IA ve, asi que las descripciones
importan tanto como el codigo.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from . import store


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    schema: dict[str, Any]
    handler: Callable[..., Any]
    # Las herramientas sensibles se marcan para que la interfaz las destaque.
    sensitive: bool = False


def _obj(props: dict[str, Any], required: list[str]) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": props,
        "required": required,
        "additionalProperties": False,
    }


_STR = {"type": "string"}
_BOOL = {"type": "boolean"}


# --------------------------------------------------------------------------
# Handlers
# --------------------------------------------------------------------------

def _estado_general() -> dict[str, Any]:
    habits = store.habits_state(days=14)
    return {
        "hoy": habits["hoy"],
        "habitos": habits["habitos"],
        "rachas": habits["rachas"],
        "ultimos_dias": habits["dias"][-7:],
        "proyectos": store.list_projects(),
        "inbox": store.inbox_items(),
        "diario_hoy": store.diary_read() or "(vacio)",
        "tareas_pendientes": store.task_list("pendiente_aprobacion"),
    }


def _registrar_habito(habito: str, hecho: bool, fecha: str = "", nota: str = "") -> dict[str, Any]:
    ids = {h["id"] for h in store.habit_defs()}
    if habito not in ids:
        return {"error": f"No existe el habito {habito!r}. Disponibles: {sorted(ids)}"}
    day = fecha or store.date.today().isoformat()
    row = store.set_habit(day, habito, hecho, nota)
    return {"ok": True, "fecha": day, "fila": row, "racha": store.habits_state()["rachas"][habito]}


def _actualizar_proyecto(
    proyecto: str, seccion: str, contenido: str, modo: str = "reemplazar"
) -> dict[str, Any]:
    try:
        resultado = store.write_section(proyecto, seccion, contenido, modo)
    except FileNotFoundError as exc:
        return {"error": str(exc)}
    return {"ok": True, "seccion": seccion, "contenido": resultado}


def _leer_proyecto(proyecto: str) -> dict[str, Any]:
    try:
        return {"contenido": store.read_project(proyecto)}
    except FileNotFoundError as exc:
        return {"error": str(exc)}


def _anotar_bitacora(proyecto: str, entrada: str) -> dict[str, Any]:
    try:
        store.append_project_log(proyecto, entrada)
    except FileNotFoundError as exc:
        return {"error": str(exc)}
    return {"ok": True}


def _crear_proyecto(id: str, nombre: str, descripcion: str = "") -> dict[str, Any]:
    try:
        return {"ok": True, **store.create_project(id, nombre, descripcion)}
    except FileExistsError as exc:
        return {"error": str(exc)}


def _proponer_tarea_codigo(proyecto: str, descripcion: str, plan: str = "") -> dict[str, Any]:
    projects = {p["id"] for p in store.list_projects()}
    if proyecto not in projects:
        return {"error": f"No existe el proyecto {proyecto!r}. Disponibles: {sorted(projects)}"}
    task = store.task_create(proyecto, descripcion, plan)
    return {
        "ok": True,
        "tarea": task["id"],
        "estado": "pendiente_aprobacion",
        "aviso": (
            "La tarea queda propuesta pero NO ejecutada. El usuario tiene que "
            "aprobarla en la interfaz antes de que toques un solo fichero. "
            "Diselo y resume el plan."
        ),
    }


# --------------------------------------------------------------------------
# Registro
# --------------------------------------------------------------------------

TOOLS: list[Tool] = [
    Tool(
        "estado_general",
        "Foto completa de la situacion: habitos y rachas, proyectos con su siguiente "
        "paso, inbox, diario de hoy y tareas de codigo pendientes. Llamala al empezar "
        "una conversacion o cuando necesites orientarte antes de responder.",
        _obj({}, []),
        _estado_general,
    ),
    Tool(
        "registrar_habito",
        "Marca un habito como hecho o no hecho en una fecha. Usa el id corto del "
        "habito (deporte, lectura, codigo...). Si no se indica fecha, es hoy.",
        _obj(
            {
                "habito": {**_STR, "description": "id corto del habito"},
                "hecho": {**_BOOL, "description": "true si lo cumplio"},
                "fecha": {**_STR, "description": "YYYY-MM-DD; vacio = hoy"},
                "nota": {**_STR, "description": "detalle opcional del dia"},
            },
            ["habito", "hecho"],
        ),
        _registrar_habito,
    ),
    Tool(
        "listar_proyectos",
        "Todos los proyectos con su estado, prioridad, siguiente paso y pendientes.",
        _obj({}, []),
        lambda: {"proyectos": store.list_projects()},
    ),
    Tool(
        "leer_proyecto",
        "El fichero completo de un proyecto: estado, decisiones, pendientes y bitacora. "
        "Leelo antes de proponer cambios sobre ese proyecto.",
        _obj({"proyecto": {**_STR, "description": "id del proyecto"}}, ["proyecto"]),
        _leer_proyecto,
    ),
    Tool(
        "actualizar_proyecto",
        "Reescribe o amplia una seccion de un proyecto. Secciones habituales: "
        "'Siguiente paso', 'Estado actual', 'Decisiones', 'Pendientes'. "
        "modo='reemplazar' sustituye la seccion; modo='añadir' la amplia.",
        _obj(
            {
                "proyecto": _STR,
                "seccion": _STR,
                "contenido": {**_STR, "description": "markdown"},
                "modo": {"type": "string", "enum": ["reemplazar", "añadir"]},
            },
            ["proyecto", "seccion", "contenido"],
        ),
        _actualizar_proyecto,
    ),
    Tool(
        "anotar_bitacora",
        "Anade una linea fechada a la bitacora de un proyecto. Para registrar lo que "
        "se hizo o se decidio en una sesion.",
        _obj({"proyecto": _STR, "entrada": _STR}, ["proyecto", "entrada"]),
        _anotar_bitacora,
    ),
    Tool(
        "crear_proyecto",
        "Crea un proyecto nuevo. El id va en kebab-case y sin acentos.",
        _obj(
            {
                "id": {**_STR, "description": "kebab-case, p.ej. 'tienda-online'"},
                "nombre": _STR,
                "descripcion": _STR,
            },
            ["id", "nombre"],
        ),
        _crear_proyecto,
    ),
    Tool(
        "capturar_inbox",
        "Guarda una idea o pendiente en el inbox, sin clasificar. Para cuando el "
        "usuario suelta algo de pasada que no toca ahora.",
        _obj({"texto": _STR}, ["texto"]),
        lambda texto: {"ok": True, "total": store.inbox_add(texto)},
    ),
    Tool(
        "leer_inbox",
        "Todo lo que hay sin clasificar en el inbox.",
        _obj({}, []),
        lambda: {"inbox": store.inbox_items()},
    ),
    Tool(
        "quitar_inbox",
        "Quita una entrada del inbox cuando ya la has movido a un proyecto, un habito "
        "o el diario. Basta con parte del texto.",
        _obj({"texto": _STR}, ["texto"]),
        lambda texto: {"ok": store.inbox_remove(texto)},
    ),
    Tool(
        "escribir_diario",
        "Anade una entrada fechada al diario del dia. Para lo que paso, como fue, que "
        "sintio. No para pendientes: eso va al inbox o a un proyecto.",
        _obj(
            {"texto": _STR, "fecha": {**_STR, "description": "YYYY-MM-DD; vacio = hoy"}},
            ["texto"],
        ),
        lambda texto, fecha="": {"ok": True, "fecha": store.diary_append(texto, fecha or None)},
    ),
    Tool(
        "leer_diario",
        "Las entradas del diario de los ultimos N dias. Para buscar patrones o "
        "recordar que paso.",
        _obj({"dias": {"type": "integer", "description": "por defecto 7"}}, []),
        lambda dias=7: {"entradas": store.diary_recent(int(dias))},
    ),
    Tool(
        "proponer_tarea_codigo",
        "Propone una tarea de programacion sobre un proyecto. NO escribe codigo: deja "
        "la tarea pendiente de que el usuario la apruebe en la interfaz. Incluye "
        "siempre un plan concreto de que ficheros tocarias y como.",
        _obj(
            {
                "proyecto": _STR,
                "descripcion": {**_STR, "description": "que hay que hacer, en una frase"},
                "plan": {**_STR, "description": "pasos y ficheros previstos"},
            },
            ["proyecto", "descripcion"],
        ),
        _proponer_tarea_codigo,
        sensitive=True,
    ),
]

BY_NAME = {tool.name: tool for tool in TOOLS}


def run(name: str, args: dict[str, Any]) -> Any:
    """Ejecuta una herramienta. Nunca lanza: los errores vuelven como dato."""
    tool = BY_NAME.get(name)
    if tool is None:
        return {"error": f"Herramienta desconocida: {name!r}"}
    try:
        return tool.handler(**args)
    except TypeError as exc:
        return {"error": f"Argumentos invalidos para {name}: {exc}"}
    except Exception as exc:  # noqa: BLE001 - la IA debe poder leer el fallo
        return {"error": f"{type(exc).__name__}: {exc}"}
