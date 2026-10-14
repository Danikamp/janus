"""El servidor solo atiende a la propia interfaz de Janus."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from server import config, main

LOCAL = f"http://127.0.0.1:{config.PORT}"


@pytest.fixture
def cliente():
    return TestClient(main.app, base_url=LOCAL)


def test_un_host_ajeno_se_rechaza(cliente):
    # DNS rebinding: un dominio externo que resuelve a 127.0.0.1.
    r = cliente.get("/api/tareas", headers={"Host": f"malo.example:{config.PORT}"})
    assert r.status_code == 403


def test_un_post_desde_otra_web_se_rechaza(cliente):
    r = cliente.post(
        "/api/inbox", json={"texto": "x"}, headers={"Origin": "https://malo.example"}
    )
    assert r.status_code == 403


def test_la_propia_interfaz_pasa(cliente, data):
    r = cliente.post("/api/sesion/reiniciar", headers={"Origin": LOCAL})
    assert r.status_code == 200
    assert (data / "sesiones" / "principal.json").exists()  # el temporal, no el real


def test_una_peticion_sin_origin_pasa(cliente):
    r = cliente.get("/api/tareas")
    assert r.status_code == 200
