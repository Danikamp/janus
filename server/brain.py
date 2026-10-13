"""Capa multi-cerebro: Claude o GPT, misma interfaz.

Cada adaptador recibe el historial y va emitiendo eventos a medida que el modelo
responde. El bucle de herramientas lo llevamos nosotros (no el helper del SDK)
porque tiene que funcionar igual con los dos proveedores.

Eventos emitidos:
    {"type": "pensando", "texto": str}   resumen del razonamiento
    {"type": "texto",    "texto": str}   fragmento de la respuesta
    {"type": "tool",     "nombre": str, "args": dict}
    {"type": "tool_fin", "nombre": str, "resultado": Any}
    {"type": "fin",      "uso": dict}
    {"type": "error",    "mensaje": str}
"""
from __future__ import annotations

import json
from typing import Any, AsyncIterator

from . import config, tools
from .prompts import system_prompt

MAX_TURNOS = 12  # tope de vueltas del bucle de herramientas


# --------------------------------------------------------------------------
# Traduccion de esquemas
# --------------------------------------------------------------------------

def _claude_tools() -> list[dict[str, Any]]:
    return [
        {"name": t.name, "description": t.description, "input_schema": t.schema}
        for t in tools.TOOLS
    ]


def _gpt_tools() -> list[dict[str, Any]]:
    return [
        {
            "type": "function",
            "function": {
                "name": t.name,
                "description": t.description,
                "parameters": t.schema,
            },
        }
        for t in tools.TOOLS
    ]


def _as_text(result: Any) -> str:
    return json.dumps(result, ensure_ascii=False, default=str)


# --------------------------------------------------------------------------
# Claude
# --------------------------------------------------------------------------

async def _claude(history: list[dict[str, Any]]) -> AsyncIterator[dict[str, Any]]:
    import anthropic

    client = anthropic.AsyncAnthropic()
    messages = list(history)
    uso: dict[str, int] = {"entrada": 0, "salida": 0, "cache_lectura": 0}

    # El prompt de sistema es estable, asi que lo cacheamos.
    system = [
        {
            "type": "text",
            "text": system_prompt(),
            "cache_control": {"type": "ephemeral"},
        }
    ]

    base: dict[str, Any] = {
        "model": config.CLAUDE_MODEL,
        "max_tokens": 32000,
        "system": system,
        "tools": _claude_tools(),
        "thinking": {"type": "adaptive", "display": "summarized"},
        "output_config": {"effort": "medium"},
    }
    # Fallback de servidor: si un clasificador de seguridad rechaza la peticion,
    # se reencamina sola en vez de devolver un error al usuario.
    beta: dict[str, Any] = {
        "betas": ["server-side-fallback-2026-07-01"],
        "fallbacks": "default",
    }
    usar_beta = True

    for _ in range(MAX_TURNOS):
        kwargs = {**base, "messages": messages}
        try:
            if usar_beta:
                ctx = client.beta.messages.stream(**kwargs, **beta)
            else:
                ctx = client.messages.stream(**kwargs)
            async with ctx as stream:
                async for event in stream:
                    if event.type != "content_block_delta":
                        continue
                    delta = event.delta
                    if delta.type == "text_delta":
                        yield {"type": "texto", "texto": delta.text}
                    elif delta.type == "thinking_delta":
                        yield {"type": "pensando", "texto": delta.thinking}
                final = await stream.get_final_message()
        except anthropic.BadRequestError as exc:
            # El beta de fallback puede no estar habilitado en la cuenta.
            if usar_beta:
                usar_beta = False
                continue
            yield {"type": "error", "mensaje": f"Claude rechazo la peticion: {exc}"}
            return
        except anthropic.APIStatusError as exc:
            yield {"type": "error", "mensaje": f"Error de la API de Claude: {exc}"}
            return
        except anthropic.APIConnectionError as exc:
            yield {"type": "error", "mensaje": f"Sin conexion con Claude: {exc}"}
            return

        u = final.usage
        uso["entrada"] += getattr(u, "input_tokens", 0) or 0
        uso["salida"] += getattr(u, "output_tokens", 0) or 0
        uso["cache_lectura"] += getattr(u, "cache_read_input_tokens", 0) or 0

        if final.stop_reason == "refusal":
            detalle = getattr(final, "stop_details", None)
            motivo = getattr(detalle, "explanation", "") or "sin detalle"
            yield {"type": "error", "mensaje": f"Claude declino responder: {motivo}"}
            return

        # Hay que devolver los bloques tal cual, incluido el razonamiento.
        messages.append({"role": "assistant", "content": final.content})

        if final.stop_reason != "tool_use":
            yield {"type": "fin", "uso": uso}
            return

        resultados = []
        for block in final.content:
            if block.type != "tool_use":
                continue
            args = dict(block.input or {})
            yield {"type": "tool", "nombre": block.name, "args": args}
            resultado = tools.run(block.name, args)
            yield {"type": "tool_fin", "nombre": block.name, "resultado": resultado}
            resultados.append(
                {
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": _as_text(resultado),
                }
            )
        # Todos los resultados en un solo mensaje de usuario.
        messages.append({"role": "user", "content": resultados})

    yield {"type": "error", "mensaje": f"Se alcanzo el tope de {MAX_TURNOS} vueltas."}


# --------------------------------------------------------------------------
# GPT
# --------------------------------------------------------------------------

async def _gpt(history: list[dict[str, Any]]) -> AsyncIterator[dict[str, Any]]:
    import openai

    client = openai.AsyncOpenAI()
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": system_prompt()},
        *_to_openai(history),
    ]
    uso: dict[str, int] = {"entrada": 0, "salida": 0, "cache_lectura": 0}

    for _ in range(MAX_TURNOS):
        try:
            stream = await client.chat.completions.create(
                model=config.GPT_MODEL,
                messages=messages,
                tools=_gpt_tools(),
                stream=True,
                stream_options={"include_usage": True},
            )
        except openai.APIStatusError as exc:
            yield {"type": "error", "mensaje": f"Error de la API de OpenAI: {exc}"}
            return
        except openai.APIConnectionError as exc:
            yield {"type": "error", "mensaje": f"Sin conexion con OpenAI: {exc}"}
            return

        texto = ""
        # Las llamadas a herramientas llegan a trozos: hay que acumularlas por indice.
        parciales: dict[int, dict[str, str]] = {}
        async for chunk in stream:
            if chunk.usage:
                uso["entrada"] += chunk.usage.prompt_tokens or 0
                uso["salida"] += chunk.usage.completion_tokens or 0
            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta
            if delta.content:
                texto += delta.content
                yield {"type": "texto", "texto": delta.content}
            for call in delta.tool_calls or []:
                slot = parciales.setdefault(call.index, {"id": "", "name": "", "args": ""})
                if call.id:
                    slot["id"] = call.id
                if call.function and call.function.name:
                    slot["name"] = call.function.name
                if call.function and call.function.arguments:
                    slot["args"] += call.function.arguments

        if not parciales:
            messages.append({"role": "assistant", "content": texto})
            yield {"type": "fin", "uso": uso}
            return

        llamadas = [parciales[i] for i in sorted(parciales)]
        messages.append(
            {
                "role": "assistant",
                "content": texto or None,
                "tool_calls": [
                    {
                        "id": c["id"],
                        "type": "function",
                        "function": {"name": c["name"], "arguments": c["args"] or "{}"},
                    }
                    for c in llamadas
                ],
            }
        )
        for call in llamadas:
            try:
                args = json.loads(call["args"] or "{}")
            except json.JSONDecodeError:
                args = {}
            yield {"type": "tool", "nombre": call["name"], "args": args}
            resultado = tools.run(call["name"], args)
            yield {"type": "tool_fin", "nombre": call["name"], "resultado": resultado}
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": call["id"],
                    "content": _as_text(resultado),
                }
            )

    yield {"type": "error", "mensaje": f"Se alcanzo el tope de {MAX_TURNOS} vueltas."}


def _to_openai(history: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """El historial se guarda en formato Claude; para GPT se aplana a texto.

    Solo cruzan los turnos de texto: los bloques de razonamiento y los resultados
    de herramientas son especificos de cada proveedor y no se pueden reenviar al
    otro. Eso permite cambiar de cerebro a mitad de conversacion sin romper nada.
    """
    plano = []
    for msg in history:
        content = msg.get("content")
        if isinstance(content, str):
            plano.append({"role": msg["role"], "content": content})
            continue
        trozos = [
            b.get("text", "")
            for b in (content or [])
            if isinstance(b, dict) and b.get("type") == "text"
        ]
        if any(t.strip() for t in trozos):
            plano.append({"role": msg["role"], "content": "\n".join(trozos)})
    return plano


# --------------------------------------------------------------------------
# Entrada publica
# --------------------------------------------------------------------------

def stream(history: list[dict[str, Any]], cerebro: str) -> AsyncIterator[dict[str, Any]]:
    """Responde con el cerebro elegido. `history` va en formato Claude."""
    if cerebro == "gpt":
        return _gpt(history)
    return _claude(history)
