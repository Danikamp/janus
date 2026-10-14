"""El servidor de Janus.

Sirve la interfaz web y expone la API. El historial de conversacion vive en el
servidor (no en el navegador) porque los bloques de Claude tienen que volver
intactos al modelo; la interfaz solo necesita el texto.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, AsyncIterator

from fastapi import FastAPI, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles

from . import brain, coder, config, store, tools

WEB = config.ROOT / "web"
SESIONES_DIR = config.DATA / "sesiones"

app = FastAPI(title="Janus", docs_url=None, redoc_url=None)


# --------------------------------------------------------------------------
# Solo desde esta maquina
# --------------------------------------------------------------------------

HOSTS_PERMITIDOS = {f"{h}:{config.PORT}" for h in ("127.0.0.1", "localhost", config.HOST)}
ORIGENES_PERMITIDOS = {f"http://{h}" for h in HOSTS_PERMITIDOS}
METODOS_SEGUROS = {"GET", "HEAD", "OPTIONS"}


@app.middleware("http")
async def solo_local(request: Request, call_next):
    """Cierra la puerta a otras webs abiertas en el mismo navegador.

    - `Host` ajeno: alguien apunto un dominio suyo a 127.0.0.1 (DNS rebinding).
    - `Origin` ajeno en un POST/DELETE: una pagina cualquiera intentando hablar
      con Janus por detras. Sin `Origin` (curl, scripts locales) se deja pasar.
    """
    if request.headers.get("host", "") not in HOSTS_PERMITIDOS:
        return JSONResponse({"detail": "Host no permitido"}, status_code=403)
    origen = request.headers.get("origin")
    if request.method not in METODOS_SEGUROS and origen and origen not in ORIGENES_PERMITIDOS:
        return JSONResponse({"detail": "Origen no permitido"}, status_code=403)
    return await call_next(request)


# --------------------------------------------------------------------------
# Sesiones
# --------------------------------------------------------------------------

def _ruta_sesion(sid: str) -> Path:
    return SESIONES_DIR / f"{sid}.json"


def cargar_sesion(sid: str = "principal") -> list[dict[str, Any]]:
    ruta = _ruta_sesion(sid)
    if not ruta.exists():
        return []
    try:
        return json.loads(ruta.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []


def guardar_sesion(historial: list[dict[str, Any]], sid: str = "principal") -> None:
    store.escribir(
        _ruta_sesion(sid), json.dumps(historial, ensure_ascii=False, indent=1, default=str)
    )


def _solo_texto(historial: list[dict[str, Any]]) -> list[dict[str, str]]:
    """El historial como lo necesita la interfaz: turnos de texto y nada mas."""
    salida = []
    for msg in historial:
        content = msg.get("content")
        if isinstance(content, str):
            texto = content
        else:
            texto = "\n".join(
                b.get("text", "")
                for b in (content or [])
                if isinstance(b, dict) and b.get("type") == "text"
            )
        if texto.strip():
            salida.append({"rol": msg["role"], "texto": texto.strip()})
    return salida


# --------------------------------------------------------------------------
# SSE
# --------------------------------------------------------------------------

def _sse(evento: dict[str, Any]) -> str:
    return f"data: {json.dumps(evento, ensure_ascii=False, default=str)}\n\n"


CABECERAS_SSE = {
    "Cache-Control": "no-cache",
    "Connection": "keep-alive",
    "X-Accel-Buffering": "no",
}


# --------------------------------------------------------------------------
# Estado e interfaz
# --------------------------------------------------------------------------

@app.get("/api/estado")
def estado() -> dict[str, Any]:
    habitos = store.habits_state(days=14)
    return {
        "cerebros": [
            {
                "id": b.id,
                "label": b.label,
                "modelo": b.model,
                "disponible": b.available,
                "motivo": b.reason,
            }
            for b in config.brains()
        ],
        "cerebro_actual": config.DEFAULT_BRAIN,
        "voz": config.VOICE_MODE,
        "habitos": habitos,
        "proyectos": store.list_projects(),
        "inbox": store.inbox_items(),
        "tareas": store.task_list(),
        "diario_hoy": store.diary_read(),
        "historial": _solo_texto(cargar_sesion()),
    }


@app.post("/api/habito")
async def marcar_habito(request: Request) -> dict[str, Any]:
    cuerpo = await request.json()
    habito = cuerpo.get("habito")
    if not habito:
        raise HTTPException(400, "Falta 'habito'")
    try:
        store.set_habit(
            cuerpo.get("fecha") or store.hoy().isoformat(),
            habito,
            bool(cuerpo.get("hecho", True)),
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from None
    return {"ok": True, "habitos": store.habits_state(days=14)}


@app.post("/api/inbox")
async def capturar(request: Request) -> dict[str, Any]:
    cuerpo = await request.json()
    texto = (cuerpo.get("texto") or "").strip()
    if not texto:
        raise HTTPException(400, "Falta 'texto'")
    store.inbox_add(texto)
    return {"ok": True, "inbox": store.inbox_items()}


@app.delete("/api/inbox")
async def quitar_inbox(request: Request) -> dict[str, Any]:
    cuerpo = await request.json()
    store.inbox_remove(cuerpo.get("texto", ""))
    return {"ok": True, "inbox": store.inbox_items()}


@app.post("/api/sesion/reiniciar")
def reiniciar_sesion() -> dict[str, Any]:
    guardar_sesion([])
    return {"ok": True}


# --------------------------------------------------------------------------
# Chat
# --------------------------------------------------------------------------

@app.post("/api/chat")
async def chat(request: Request) -> StreamingResponse:
    cuerpo = await request.json()
    mensaje = (cuerpo.get("mensaje") or "").strip()
    cerebro = cuerpo.get("cerebro") or config.DEFAULT_BRAIN
    if not mensaje:
        raise HTTPException(400, "Falta 'mensaje'")

    elegido = next((b for b in config.brains() if b.id == cerebro), None)
    if elegido is None:
        raise HTTPException(400, f"Cerebro desconocido: {cerebro}")
    if not elegido.available:
        async def aviso() -> AsyncIterator[str]:
            yield _sse({"type": "error", "mensaje": elegido.reason})
        return StreamingResponse(aviso(), media_type="text/event-stream", headers=CABECERAS_SSE)

    historial = cargar_sesion()
    historial.append({"role": "user", "content": [{"type": "text", "text": mensaje}]})

    async def generar() -> AsyncIterator[str]:
        respuesta = ""
        try:
            async for evento in brain.stream(historial, cerebro):
                if evento["type"] == "texto":
                    respuesta += evento["texto"]
                yield _sse(evento)
        except Exception as exc:  # noqa: BLE001
            yield _sse({"type": "error", "mensaje": f"{type(exc).__name__}: {exc}"})
        finally:
            if respuesta.strip():
                historial.append(
                    {"role": "assistant", "content": [{"type": "text", "text": respuesta}]}
                )
            guardar_sesion(historial)
            yield _sse({"type": "estado", "datos": _estado_ligero()})

    return StreamingResponse(generar(), media_type="text/event-stream", headers=CABECERAS_SSE)


def _estado_ligero() -> dict[str, Any]:
    """Lo que la interfaz tiene que refrescar tras un turno."""
    return {
        "habitos": store.habits_state(days=14),
        "proyectos": store.list_projects(),
        "inbox": store.inbox_items(),
        "tareas": store.task_list(),
    }


# --------------------------------------------------------------------------
# Tareas de codigo
# --------------------------------------------------------------------------

@app.get("/api/tareas")
def listar_tareas() -> dict[str, Any]:
    return {"tareas": store.task_list()}


@app.post("/api/tareas/{task_id}/rechazar")
def rechazar(task_id: str) -> dict[str, Any]:
    if store.task_update(task_id, estado="rechazada") is None:
        raise HTTPException(404, "Tarea no encontrada")
    return {"ok": True, "tareas": store.task_list()}


@app.post("/api/tareas/{task_id}/ejecutar")
async def ejecutar_tarea(task_id: str) -> StreamingResponse:
    """Aprueba y ejecuta. Este endpoint ES la aprobacion explicita del usuario."""
    tarea = store.task_get(task_id)
    if tarea is None:
        raise HTTPException(404, "Tarea no encontrada")
    # 'aprobada' tambien: si fallo antes de empezar (sin CLI, sin carpeta), se
    # quedaba ahi sin forma de reintentarla.
    if tarea["estado"] not in ("pendiente_aprobacion", "aprobada", "fallida", "interrumpida"):
        raise HTTPException(409, f"La tarea esta en estado '{tarea['estado']}'")

    store.task_update(task_id, estado="aprobada")

    async def generar() -> AsyncIterator[str]:
        historial = cargar_sesion()
        resumen = ""
        try:
            # Bash nunca se activa desde la API: cualquiera que llegue a este
            # endpoint podria pedirlo. Ver "Seguridad" en CLAUDE.md.
            async for evento in coder.ejecutar(task_id, permitir_bash=False):
                if evento["type"] == "texto":
                    resumen += evento["texto"]
                yield _sse(evento)
        except Exception as exc:  # noqa: BLE001
            yield _sse({"type": "error", "mensaje": f"{type(exc).__name__}: {exc}"})
        finally:
            if resumen.strip():
                historial.append(
                    {
                        "role": "assistant",
                        "content": [
                            {"type": "text", "text": f"[tarea {task_id}]\n\n{resumen}"}
                        ],
                    }
                )
                guardar_sesion(historial)
            yield _sse({"type": "estado", "datos": _estado_ligero()})

    return StreamingResponse(generar(), media_type="text/event-stream", headers=CABECERAS_SSE)


# --------------------------------------------------------------------------
# Voz (solo en modo 'openai'; en modo 'browser' lo hace el navegador)
# --------------------------------------------------------------------------

@app.post("/api/voz/transcribir")
async def transcribir(audio: UploadFile) -> dict[str, str]:
    if config.VOICE_MODE != "openai":
        raise HTTPException(400, "La transcripcion en servidor requiere JANUS_VOICE=openai")
    import openai

    cliente = openai.AsyncOpenAI()
    datos = await audio.read()
    resultado = await cliente.audio.transcriptions.create(
        model="whisper-1",
        file=(audio.filename or "audio.webm", datos),
        language="es",
    )
    return {"texto": resultado.text}


@app.post("/api/voz/hablar")
async def hablar(request: Request) -> Response:
    if config.VOICE_MODE != "openai":
        raise HTTPException(400, "La sintesis en servidor requiere JANUS_VOICE=openai")
    import openai

    cuerpo = await request.json()
    texto = (cuerpo.get("texto") or "").strip()
    if not texto:
        raise HTTPException(400, "Falta 'texto'")
    cliente = openai.AsyncOpenAI()
    audio = await cliente.audio.speech.create(
        model="gpt-4o-mini-tts", voice="alloy", input=texto[:4000]
    )
    return Response(content=audio.read(), media_type="audio/mpeg")


# --------------------------------------------------------------------------
# Estaticos
# --------------------------------------------------------------------------

@app.get("/")
def raiz() -> FileResponse:
    return FileResponse(WEB / "index.html")


app.mount("/", StaticFiles(directory=WEB), name="web")


def main() -> None:
    import uvicorn

    print(f"\n  Janus escuchando en http://{config.HOST}:{config.PORT}\n")
    uvicorn.run(app, host=config.HOST, port=config.PORT, log_level="warning")


if __name__ == "__main__":
    main()
