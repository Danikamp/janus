"""Ningun test toca el data/ real: todas las rutas apuntan a una carpeta temporal.

Es autouse a proposito. Un test que se olvide de pedirlo seguiria escribiendo
en tus datos (ya paso una vez: se vacio la sesion de chat).
"""
from __future__ import annotations

import pytest

from server import main, store


def definir_habitos(ids: list[str]) -> None:
    filas = "\n".join(f"| {i} | {i.title()} |" for i in ids)
    store.escribir(store.HABITS_FILE, f"# Habitos\n\n| id | nombre |\n|---|---|\n{filas}\n")


@pytest.fixture(autouse=True)
def data(tmp_path, monkeypatch):
    """Un data/ vacio con dos habitos definidos."""
    rutas = {
        "HABITS_FILE": tmp_path / "habitos" / "habitos.md",
        "HABITS_LOG_DIR": tmp_path / "habitos" / "registro",
        "PROJECTS_DIR": tmp_path / "proyectos",
        "DIARY_DIR": tmp_path / "diario",
        "INBOX_FILE": tmp_path / "inbox.md",
        "TASKS_FILE": tmp_path / "tareas" / "tareas.json",
    }
    for nombre, ruta in rutas.items():
        monkeypatch.setattr(store, nombre, ruta)
    monkeypatch.setattr(main, "SESIONES_DIR", tmp_path / "sesiones")
    definir_habitos(["deporte", "lectura"])
    return tmp_path
