"""Acceso a los datos de Janus.

Todo vive en ficheros markdown dentro de data/. Esta capa es la unica que sabe
como estan escritos: si algun dia cambias el formato, solo se toca este fichero.
"""
from __future__ import annotations

import json
import os
import re
import unicodedata
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .config import DATA, TZ

HABITS_FILE = DATA / "habitos" / "habitos.md"
HABITS_LOG_DIR = DATA / "habitos" / "registro"
PROJECTS_DIR = DATA / "proyectos"
DIARY_DIR = DATA / "diario"
INBOX_FILE = DATA / "inbox.md"
TASKS_FILE = DATA / "tareas" / "tareas.json"


# --------------------------------------------------------------------------
# Fecha, escritura y validacion
# --------------------------------------------------------------------------

try:
    _ZONA: ZoneInfo | None = ZoneInfo(TZ)
except (ZoneInfoNotFoundError, ValueError):
    _ZONA = None  # zona mal escrita en .env: se usa la hora del sistema


def ahora() -> datetime:
    """La hora en JANUS_TZ, sin zona adjunta para que los textos no cambien.

    El USB va de maquina en maquina; la hora del sistema puede no ser la tuya.
    """
    momento = datetime.now(_ZONA) if _ZONA else datetime.now()
    return momento.replace(tzinfo=None)


def hoy() -> date:
    return ahora().date()


def escribir(path: Path, texto: str) -> None:
    """Escribe de forma atomica: a un .tmp y luego se sustituye de golpe.

    Si el USB se desconecta a mitad, queda el fichero viejo entero o el nuevo
    entero, nunca uno cortado.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    with tmp.open("w", encoding="utf-8") as fh:
        fh.write(texto)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, path)


def validar_fecha(day: str) -> str:
    """Devuelve la fecha en YYYY-MM-DD o lanza ValueError."""
    try:
        return date.fromisoformat(day.strip()).isoformat()
    except (ValueError, AttributeError):
        raise ValueError(f"Fecha no valida: {day!r}. Usa el formato YYYY-MM-DD.") from None


_ID = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


def _validar_id(pid: str) -> str:
    """Id de proyecto nuevo: kebab-case, sin acentos ni espacios."""
    if not _ID.match(pid or ""):
        raise ValueError(
            f"Id de proyecto no valido: {pid!r}. Usa kebab-case sin acentos, "
            "p.ej. 'tienda-online'."
        )
    return pid


# --------------------------------------------------------------------------
# Frontmatter
# --------------------------------------------------------------------------

_FM = re.compile(r"\A---\r?\n(.*?)\r?\n---\r?\n?", re.DOTALL)


def parse_md(text: str) -> tuple[dict[str, str], str]:
    """Separa el frontmatter plano (clave: valor) del cuerpo."""
    match = _FM.match(text)
    if not match:
        return {}, text
    meta: dict[str, str] = {}
    for line in match.group(1).splitlines():
        if ":" in line:
            key, _, value = line.partition(":")
            meta[key.strip()] = value.strip().strip('"').strip("'")
    return meta, text[match.end():]


def dump_md(meta: dict[str, Any], body: str) -> str:
    if not meta:
        return body
    lines = "\n".join(f"{k}: {v}" for k, v in meta.items())
    return f"---\n{lines}\n---\n{body}"


# --------------------------------------------------------------------------
# Tablas markdown
# --------------------------------------------------------------------------

def _is_separator(cells: list[str]) -> bool:
    return bool(cells) and all(set(c) <= set("-: ") and "-" in c for c in cells)


def _split_row(line: str) -> list[str]:
    return [c.strip() for c in line.strip().strip("|").split("|")]


def read_table(text: str) -> tuple[list[str], list[dict[str, str]]]:
    """Devuelve (cabeceras, filas) de la primera tabla markdown del texto."""
    headers: list[str] = []
    rows: list[dict[str, str]] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped.startswith("|"):
            if headers:
                break  # la tabla ya termino
            continue
        cells = _split_row(stripped)
        if _is_separator(cells):
            continue
        if not headers:
            headers = cells
            continue
        rows.append(
            {headers[i]: (cells[i] if i < len(cells) else "") for i in range(len(headers))}
        )
    return headers, rows


def replace_table(text: str, table: str) -> str:
    """Sustituye la primera tabla del texto y deja intacto todo lo demas."""
    lines = text.splitlines(keepends=True)
    inicio = next((i for i, l in enumerate(lines) if l.strip().startswith("|")), None)
    if inicio is None:
        return text.rstrip() + "\n\n" + table + "\n"
    fin = inicio
    while fin < len(lines) and lines[fin].strip().startswith("|"):
        fin += 1
    return "".join(lines[:inicio]) + table + "\n" + "".join(lines[fin:])


def _celda(texto: str) -> str:
    """Un texto que no rompa la tabla: sin barras ni saltos de linea."""
    return " ".join(texto.replace("|", "/").split())


def render_table(headers: list[str], rows: list[dict[str, str]]) -> str:
    widths = [max(len(h), 8) for h in headers]
    for row in rows:
        for i, header in enumerate(headers):
            widths[i] = max(widths[i], len(str(row.get(header, ""))))

    def line(cells: list[str]) -> str:
        padded = (cell.ljust(widths[i]) for i, cell in enumerate(cells))
        return "| " + " | ".join(padded) + " |"

    out = [line(headers), "|" + "|".join("-" * (w + 2) for w in widths) + "|"]
    out += [line([str(row.get(h, "")) for h in headers]) for row in rows]
    return "\n".join(out)


# --------------------------------------------------------------------------
# Habitos
# --------------------------------------------------------------------------

def habit_defs() -> list[dict[str, str]]:
    """Los habitos definidos por el usuario en habitos.md."""
    if not HABITS_FILE.exists():
        return []
    _, body = parse_md(HABITS_FILE.read_text(encoding="utf-8"))
    _, rows = read_table(body)
    return [r for r in rows if r.get("id")]


def _log_path(month: str) -> Path:
    return HABITS_LOG_DIR / f"{month}.md"


def _read_log_full(month: str) -> tuple[list[str], dict[str, dict[str, str]]]:
    """(cabeceras, filas por fecha) del registro de un mes."""
    path = _log_path(month)
    if not path.exists():
        return [], {}
    _, body = parse_md(path.read_text(encoding="utf-8"))
    headers, rows = read_table(body)
    return headers, {r["fecha"]: r for r in rows if r.get("fecha")}


def _read_log(month: str) -> dict[str, dict[str, str]]:
    return _read_log_full(month)[1]


def _write_log(month: str, previas: list[str], by_date: dict[str, dict[str, str]]) -> None:
    """Reescribe la tabla del mes sin perder nada de lo que ya habia.

    Las columnas son los habitos definidos mas cualquiera que ya estuviese en
    el fichero: quitar un habito de habitos.md no borra su historial. El texto
    alrededor de la tabla (y el frontmatter) se conserva tal cual.
    """
    ids = [h["id"] for h in habit_defs()]
    sobrantes = [c for c in previas if c not in ("fecha", "nota", *ids)]
    headers = ["fecha", *ids, *sobrantes, "nota"]
    tabla = render_table(headers, [by_date[day] for day in sorted(by_date)])

    path = _log_path(month)
    if path.exists():
        meta, body = parse_md(path.read_text(encoding="utf-8"))
        body = replace_table(body, tabla)
    else:
        meta = {"mes": month}
        body = (
            f"\n# Registro de habitos - {month}\n\n"
            "Una linea por dia. `x` = hecho, `-` = no hecho, vacio = sin registrar.\n"
            "Janus escribe aqui; tu tambien puedes.\n\n" + tabla + "\n"
        )
    escribir(path, dump_md(meta, body))


def set_habit(day: str, habit_id: str, done: bool, nota: str = "") -> dict[str, str]:
    """Marca un habito en una fecha (YYYY-MM-DD). Devuelve la fila resultante."""
    day = validar_fecha(day)
    ids = {h["id"] for h in habit_defs()}
    if habit_id not in ids:
        raise ValueError(f"No existe el habito {habit_id!r}. Disponibles: {sorted(ids)}")
    month = day[:7]
    previas, by_date = _read_log_full(month)
    row = by_date.get(day, {"fecha": day})
    row[habit_id] = "x" if done else "-"
    nota = _celda(nota)
    if nota:
        existing = row.get("nota", "")
        row["nota"] = f"{existing} {nota}".strip() if existing else nota
    by_date[day] = row
    _write_log(month, previas, by_date)
    return row


def habits_state(days: int = 14) -> dict[str, Any]:
    """Definiciones, ultimos N dias y racha actual de cada habito."""
    defs = habit_defs()
    today = hoy()
    months = {(today - timedelta(days=i)).strftime("%Y-%m") for i in range(days + 40)}
    log: dict[str, dict[str, str]] = {}
    for month in months:
        log.update(_read_log(month))

    recent = []
    for i in range(days - 1, -1, -1):
        day = (today - timedelta(days=i)).isoformat()
        marks = {h["id"]: log.get(day, {}).get(h["id"], "") for h in defs}
        recent.append({"fecha": day, **marks})

    streaks: dict[str, int] = {}
    for habit in defs:
        count = 0
        cursor = today
        # Hoy sin marcar todavia no rompe la racha: se cuenta desde ayer.
        if not log.get(cursor.isoformat(), {}).get(habit["id"]):
            cursor -= timedelta(days=1)
        while log.get(cursor.isoformat(), {}).get(habit["id"]) == "x":
            count += 1
            cursor -= timedelta(days=1)
        streaks[habit["id"]] = count

    return {"habitos": defs, "dias": recent, "rachas": streaks, "hoy": today.isoformat()}


# --------------------------------------------------------------------------
# Proyectos
# --------------------------------------------------------------------------

def _project_file(pid: str) -> Path:
    # Indulgente con carpetas creadas a mano, pero nunca fuera de proyectos/.
    if not pid or pid != Path(pid).name or pid.startswith("."):
        raise FileNotFoundError(f"No existe el proyecto {pid!r}")
    return PROJECTS_DIR / pid / "proyecto.md"


_HEADING = re.compile(r"^##[ \t]+(.+?)[ \t]*$", re.MULTILINE)


def _clave(texto: str) -> str:
    """Normaliza un titulo para comparar: sin acentos, sin mayusculas.

    Asi 'Bitacora', 'Bitácora' y 'BITACORA' son la misma seccion. Hace falta
    porque el titulo puede venir del usuario, de un fichero escrito a mano o de
    la IA, y los tres escriben los acentos de forma distinta.
    """
    return (
        unicodedata.normalize("NFKD", texto.strip().lower())
        .encode("ascii", "ignore")
        .decode("ascii")
    )


def _localizar(body: str, section: str) -> tuple[int, int, int] | None:
    """Devuelve (inicio_titulo, inicio_contenido, fin_contenido) de una seccion."""
    objetivo = _clave(section)
    encabezados = list(_HEADING.finditer(body))
    for i, match in enumerate(encabezados):
        if _clave(match.group(1)) != objetivo:
            continue
        fin = encabezados[i + 1].start() if i + 1 < len(encabezados) else len(body)
        return match.start(), match.end(), fin
    return None


def read_section(body: str, section: str) -> str:
    """El contenido de una seccion `## Titulo` hasta la siguiente del mismo nivel."""
    sitio = _localizar(body, section)
    return body[sitio[1]:sitio[2]].strip() if sitio else ""


def list_projects() -> list[dict[str, Any]]:
    projects = []
    for path in sorted(PROJECTS_DIR.glob("*/proyecto.md")):
        meta, body = parse_md(path.read_text(encoding="utf-8"))
        pendientes = [
            l.strip()[5:].strip()
            for l in body.splitlines()
            if l.strip().startswith("- [ ]")
        ]
        projects.append(
            {
                "id": meta.get("id", path.parent.name),
                "nombre": meta.get("nombre", path.parent.name),
                "estado": meta.get("estado", "activo"),
                "prioridad": meta.get("prioridad", "media"),
                "repo": meta.get("repo", ""),
                "siguiente_paso": read_section(body, "Siguiente paso").strip(),
                "pendientes": pendientes,
            }
        )
    return projects


def read_project(pid: str) -> str:
    path = _project_file(pid)
    if not path.exists():
        raise FileNotFoundError(f"No existe el proyecto {pid!r}")
    return path.read_text(encoding="utf-8")


def write_section(pid: str, section: str, content: str, mode: str = "reemplazar") -> str:
    """Reescribe o amplia una seccion del proyecto. La crea si no existe."""
    path = _project_file(pid)
    meta, body = parse_md(read_project(pid))
    sitio = _localizar(body, section)
    if sitio:
        _, inicio, fin = sitio
        previous = body[inicio:fin].strip()
        if mode == "reemplazar":
            new = content.strip()
        else:
            añadido = content.strip()
            # Dos listas seguidas van pegadas; si no, markdown las ve separadas.
            lista = previous.endswith(("-", ")")) or previous.rsplit("\n", 1)[-1].startswith(
                ("- ", "* ", "1.")
            )
            union = "\n" if lista and añadido.startswith(("- ", "* ")) else "\n\n"
            new = f"{previous}{union}{añadido}".strip()
        body = f"{body[:inicio]}\n\n{new}\n\n{body[fin:].lstrip(chr(10))}"
    else:
        body = body.rstrip() + f"\n\n## {section}\n\n{content.strip()}\n"
    meta["actualizado"] = hoy().isoformat()
    escribir(path, dump_md(meta, body))
    return read_section(body, section)


def append_project_log(pid: str, entry: str) -> None:
    stamp = ahora().strftime("%Y-%m-%d %H:%M")
    write_section(pid, "Bitácora", f"- **{stamp}** - {entry.strip()}", mode="añadir")


def create_project(pid: str, nombre: str, descripcion: str = "") -> dict[str, Any]:
    path = _project_file(_validar_id(pid))
    if path.exists():
        raise FileExistsError(f"El proyecto {pid!r} ya existe")
    today = hoy().isoformat()
    meta = {
        "id": pid,
        "nombre": nombre,
        "estado": "activo",
        "prioridad": "media",
        "repo": "",
        "creado": today,
        "actualizado": today,
    }
    body = (
        f"\n# {nombre}\n\n{descripcion}\n\n"
        "## Siguiente paso\n\n_Sin definir._\n\n"
        "## Estado actual\n\nProyecto recien creado.\n\n"
        "## Decisiones\n\n## Pendientes\n\n## Bitacora\n"
    )
    escribir(path, dump_md(meta, body))
    return {"id": pid, "nombre": nombre}


# --------------------------------------------------------------------------
# Inbox
# --------------------------------------------------------------------------

def inbox_items() -> list[str]:
    if not INBOX_FILE.exists():
        return []
    return [
        l.strip()[2:].strip()
        for l in INBOX_FILE.read_text(encoding="utf-8").splitlines()
        if l.strip().startswith("- ")
    ]


def inbox_add(text: str) -> int:
    stamp = ahora().strftime("%Y-%m-%d %H:%M")
    existing = (
        INBOX_FILE.read_text(encoding="utf-8") if INBOX_FILE.exists() else "# Inbox\n\n"
    )
    linea = " ".join(text.split())  # una entrada = una linea
    escribir(INBOX_FILE, existing.rstrip() + f"\n- {linea}  _({stamp})_\n")
    return len(inbox_items())


def inbox_remove(text: str) -> bool:
    """Quita la primera entrada que contenga `text`. Devuelve si quito algo."""
    if not INBOX_FILE.exists():
        return False
    lines = INBOX_FILE.read_text(encoding="utf-8").splitlines()
    needle = text.strip().lower()
    for i, line in enumerate(lines):
        if line.strip().startswith("- ") and needle in line.lower():
            del lines[i]
            escribir(INBOX_FILE, "\n".join(lines) + "\n")
            return True
    return False


# --------------------------------------------------------------------------
# Diario
# --------------------------------------------------------------------------

def diary_read(day: str | None = None) -> str:
    day = validar_fecha(day) if day else hoy().isoformat()
    path = DIARY_DIR / f"{day}.md"
    return path.read_text(encoding="utf-8") if path.exists() else ""


def diary_append(text: str, day: str | None = None) -> str:
    day = validar_fecha(day) if day else hoy().isoformat()
    path = DIARY_DIR / f"{day}.md"
    stamp = ahora().strftime("%H:%M")
    previo = (
        path.read_text(encoding="utf-8")
        if path.exists()
        else dump_md({"fecha": day}, f"\n# {day}\n\n")
    )
    escribir(path, previo + f"\n**{stamp}** - {text.strip()}\n")
    return day


def diary_recent(days: int = 7) -> list[dict[str, str]]:
    today = hoy()
    out = []
    for i in range(days):
        day = (today - timedelta(days=i)).isoformat()
        content = diary_read(day)
        if content.strip():
            out.append({"fecha": day, "contenido": content})
    return out


# --------------------------------------------------------------------------
# Tareas de codigo pendientes de aprobacion
# --------------------------------------------------------------------------

def _tasks() -> list[dict[str, Any]]:
    if not TASKS_FILE.exists():
        return []
    return json.loads(TASKS_FILE.read_text(encoding="utf-8"))


def _save_tasks(tasks: list[dict[str, Any]]) -> None:
    escribir(TASKS_FILE, json.dumps(tasks, indent=2, ensure_ascii=False))


def task_create(proyecto: str, descripcion: str, plan: str = "") -> dict[str, Any]:
    tasks = _tasks()
    task = {
        "id": f"t{len(tasks) + 1:04d}",
        "proyecto": proyecto,
        "descripcion": descripcion,
        "plan": plan,
        "estado": "pendiente_aprobacion",
        "creada": ahora().isoformat(timespec="seconds"),
        "log": [],
    }
    tasks.append(task)
    _save_tasks(tasks)
    return task


def task_get(task_id: str) -> dict[str, Any] | None:
    return next((t for t in _tasks() if t["id"] == task_id), None)


def task_list(estado: str | None = None) -> list[dict[str, Any]]:
    return [t for t in _tasks() if estado is None or t["estado"] == estado]


def task_update(task_id: str, **fields: Any) -> dict[str, Any] | None:
    tasks = _tasks()
    for task in tasks:
        if task["id"] == task_id:
            task.update(fields)
            _save_tasks(tasks)
            return task
    return None
