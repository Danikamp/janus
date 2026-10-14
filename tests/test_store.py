"""Tests de la capa de datos. El data/ temporal lo pone conftest.py."""
from __future__ import annotations

from datetime import timedelta

import pytest

from server import store

from .conftest import definir_habitos


# --------------------------------------------------------------- escritura


def test_escribir_no_deja_temporales(tmp_path):
    destino = tmp_path / "sub" / "f.md"
    store.escribir(destino, "uno")
    store.escribir(destino, "dos")
    assert destino.read_text(encoding="utf-8") == "dos"
    assert [p.name for p in destino.parent.iterdir()] == ["f.md"]


# ----------------------------------------------------------------- habitos


def test_quitar_un_habito_no_borra_su_historial(data):
    store.set_habit("2026-10-01", "lectura", True)
    definir_habitos(["deporte"])  # el usuario quita 'lectura'
    store.set_habit("2026-10-02", "deporte", True)

    registro = store._read_log("2026-10")
    assert registro["2026-10-01"]["lectura"] == "x"
    assert registro["2026-10-02"]["deporte"] == "x"


def test_el_texto_escrito_a_mano_alrededor_de_la_tabla_se_conserva(data):
    store.set_habit("2026-10-01", "deporte", True)
    ruta = store._log_path("2026-10")
    ruta.write_text(
        ruta.read_text(encoding="utf-8") + "\nNota mia: semana de viaje.\n", encoding="utf-8"
    )
    store.set_habit("2026-10-02", "deporte", False)
    assert "Nota mia: semana de viaje." in ruta.read_text(encoding="utf-8")


def test_una_nota_con_barras_no_rompe_la_tabla(data):
    store.set_habit("2026-10-01", "deporte", True, nota="pierna | brazo\nfuerte")
    fila = store._read_log("2026-10")["2026-10-01"]
    assert fila["nota"] == "pierna / brazo fuerte"
    assert fila["deporte"] == "x"


def test_habito_o_fecha_invalidos(data):
    with pytest.raises(ValueError):
        store.set_habit("2026-10-01", "inventado", True)
    with pytest.raises(ValueError):
        store.set_habit("../../server/x", "deporte", True)
    with pytest.raises(ValueError):
        store.set_habit("13/10/2026", "deporte", True)


def test_la_racha_no_se_rompe_hasta_marcar_hoy(data):
    hoy = store.hoy()
    for dias in (1, 2, 3):
        store.set_habit((hoy - timedelta(days=dias)).isoformat(), "deporte", True)
    assert store.habits_state()["rachas"]["deporte"] == 3

    store.set_habit(hoy.isoformat(), "deporte", True)
    assert store.habits_state()["rachas"]["deporte"] == 4

    store.set_habit(hoy.isoformat(), "deporte", False)
    assert store.habits_state()["rachas"]["deporte"] == 0


# --------------------------------------------------------------- proyectos


@pytest.mark.parametrize("pid", ["../fuera", "..", "a/b", "a\\b", ".oculto", ""])
def test_un_id_no_sale_de_proyectos(data, pid):
    with pytest.raises(FileNotFoundError):
        store.read_project(pid)


@pytest.mark.parametrize("pid", ["Mi Proyecto", "acción", "-x", "a--b", "../x"])
def test_crear_proyecto_exige_kebab_case(data, pid):
    with pytest.raises(ValueError):
        store.create_project(pid, "Nombre")


def test_secciones_con_y_sin_acento_son_la_misma(data):
    store.create_project("demo", "Demo")
    store.append_project_log("demo", "primera")
    store.write_section("demo", "BITÁCORA", "- segunda", mode="añadir")

    texto = store.read_project("demo")
    assert texto.lower().count("## bit") == 1
    assert "primera" in texto and "segunda" in texto


# ----------------------------------------------------------- diario e inbox


def test_diario_rechaza_fechas_raras(data):
    with pytest.raises(ValueError):
        store.diary_append("hola", "../../server/x")
    store.diary_append("uno", "2026-10-01")
    store.diary_append("dos", "2026-10-01")
    texto = store.diary_read("2026-10-01")
    assert texto.index("uno") < texto.index("dos")


def test_una_entrada_del_inbox_es_siempre_una_linea(data):
    store.inbox_add("idea\ncon salto")
    assert store.inbox_items()[0].startswith("idea con salto")
