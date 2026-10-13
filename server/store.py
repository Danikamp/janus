"""Acceso a los datos de Janus.

Todo vive en ficheros markdown dentro de data/. Esta capa es la unica que sabe
como estan escritos: si algun dia cambias el formato, solo se toca este fichero.
"""
from __future__ import annotations

import json
import re
import unicodedata
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from .config import DATA

HABITS_FILE = DATA / "habitos" / "habitos.md"
HABITS_LOG_DIR = DATA / "habitos" / "registro"
PROJECTS_DIR = DATA / "proyectos"
DIARY_DIR = DATA / "diario"
INBOX_FILE = DATA / "inbox.md"
TASKS_FILE = DATA / "tareas" / "tareas.json"


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


def _read_log(month: str) -> dict[str, dict[str, str]]:
    path = _log_path(month)
    if not path.exists():
        return {}
    _, body = parse_md(path.read_text(encoding="utf-8"))
    _, rows = read_table(body)
    return {r["fecha"]: r for r in rows if r.get("fecha")}


def _write_log(month: str, by_date: dict[str, dict[str, str]]) -> None:
    ids = [h["id"] for h in habit_defs()]
    headers = ["fecha", *ids, "nota"]
    rows = [by_date[day] for day in sorted(by_date)]
    HABITS_LOG_DIR.mkdir(parents=True, exist_ok=True)
    body = (
        f"\n# Registro de habitos - {month}\n\n"
        "Una linea por dia. `x` = hecho, `-` = no hecho, vacio = sin registrar.\n"
        "Janus escribe aqui; tu tambien puedes.\n\n"
        + render_table(headers, rows)
        + "\n"
    )
    _log_path(month).write_text(dump_md({"mes": month}, body), encoding="utf-8")


def set_habit(day: str, habit_id: str, done: bool, nota: str = "") -> dict[str, str]:
    """Marca un habito en una fecha (YYYY-MM-DD). Devuelve la fila resultante."""
    month = day[:7]
    by_date = _read_log(month)
    row = by_date.get(day, {"fecha": day})
    row[habit_id] = "x" if done else "-"
    if nota:
        existing = row.get("nota", "")
        row["nota"] = f"{existing} {nota}".strip() if existing else nota
    by_date[day] = row
    _write_log(month, by_date)
    return row


def habits_state(days: int = 14) -> dict[str, Any]:
    """Definiciones, ultimos N dias y racha actual de cada habito."""
    defs = habit_defs()
    today = date.today()
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
        while log.get(cursor.isoformat(), {}).get(habit["id"]) == "x":
            count += 1
            cursor -= timedelta(days=1)
        streaks[habit["id"]] = count

    return {"habitos": defs, "dias": recent, "rachas": streaks, "hoy": today.isoformat()}


# --------------------------------------------------------------------------
# Proyectos
# --------------------------------------------------------------------------

def _project_file(pid: str) -> Path:
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
    meta["actualizado"] = date.today().isoformat()
    path.write_text(dump_md(meta, body), encoding="utf-8")
    return read_section(body, section)


def append_project_log(pid: str, entry: str) -> None:
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    write_section(pid, "Bitácora", f"- **{stamp}** - {entry.strip()}", mode="añadir")


def create_project(pid: str, nombre: str, descripcion: str = "") -> dict[str, Any]:
    path = _project_file(pid)
    if path.exists():
        raise FileExistsError(f"El proyecto {pid!r} ya existe")
    path.parent.mkdir(parents=True, exist_ok=True)
    today = date.today().isoformat()
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
    path.write_text(dump_md(meta, body), encoding="utf-8")
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
    INBOX_FILE.parent.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    existing = (
        INBOX_FILE.read_text(encoding="utf-8") if INBOX_FILE.exists() else "# Inbox\n\n"
    )
    INBOX_FILE.write_text(
        existing.rstrip() + f"\n- {text.strip()}  _({stamp})_\n", encoding="utf-8"
    )
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
            INBOX_FILE.write_text("\n".join(lines) + "\n", encoding="utf-8")
            return True
    return False


# --------------------------------------------------------------------------
# Diario
# --------------------------------------------------------------------------

def diary_read(day: str | None = None) -> str:
    day = day or date.today().isoformat()
    path = DIARY_DIR / f"{day}.md"
    return path.read_text(encoding="utf-8") if path.exists() else ""


def diary_append(text: str, day: str | None = None) -> str:
    day = day or date.today().isoformat()
    DIARY_DIR.mkdir(parents=True, exist_ok=True)
    path = DIARY_DIR / f"{day}.md"
    stamp = datetime.now().strftime("%H:%M")
    if not path.exists():
        path.write_text(dump_md({"fecha": day}, f"\n# {day}\n\n"), encoding="utf-8")
    with path.open("a", encoding="utf-8") as fh:
        fh.write(f"\n**{stamp}** - {text.strip()}\n")
    return day


def diary_recent(days: int = 7) -> list[dict[str, str]]:
    today = date.today()
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
    TASKS_FILE.parent.mkdir(parents=True, exist_ok=True)
    TASKS_FILE.write_text(
        json.dumps(tasks, indent=2, ensure_ascii=False), encoding="utf-8"
    )


def task_create(proyecto: str, descripcion: str, plan: str = "") -> dict[str, Any]:
    tasks = _tasks()
    task = {
        "id": f"t{len(tasks) + 1:04d}",
        "proyecto": proyecto,
        "descripcion": descripcion,
        "plan": plan,
        "estado": "pendiente_aprobacion",
        "creada": datetime.now().isoformat(timespec="seconds"),
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
