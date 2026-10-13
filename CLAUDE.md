# Janus — notas para trabajar en este repo

Asistente personal de hábitos y proyectos. Python + FastAPI detrás, HTML/CSS/JS
sin build delante, markdown como base de datos.

## Principios

1. **`data/` es la verdad.** Markdown legible y editable a mano. Si un cambio
   obliga a migrar `data/`, hay que pensarlo dos veces: el código se reescribe,
   el historial de hábitos de tres años no.
2. **Sin build en el frontend.** `web/` se sirve tal cual. No introducir React,
   Vite ni `node_modules`: arranca desde un USB y eso se perdería.
3. **El comportamiento se ajusta en `prompts.py`,** no añadiendo ramas al
   código. Si Janus guarda algo donde no toca o responde con un tono raro, la
   causa está casi siempre ahí.
4. **Programar siempre requiere aprobación explícita.** Ver abajo.

## Arrancar y probar

```powershell
.venv\Scripts\python.exe -m server.main     # servidor en :8700
.venv\Scripts\python.exe -X utf8 -c "from server import tools; print(tools.run('estado_general', {}))"
```

`-X utf8` hace falta en la consola de Windows: sin él, los acentos de los datos
revientan al imprimir.

## Dónde está cada cosa

| Fichero | Responsabilidad |
|---|---|
| `server/store.py` | **único** sitio que sabe cómo están escritos los markdown |
| `server/tools.py` | el registro de herramientas; las descripciones son el prompt |
| `server/brain.py` | bucle de herramientas propio, igual para Claude y GPT |
| `server/coder.py` | modo programador vía Claude Agent SDK |
| `server/main.py` | rutas y streaming SSE |

### Añadir una herramienta

Una entrada en `TOOLS` (`server/tools.py`) y su handler. Nada más: `brain.py`
traduce el esquema a los dos proveedores solo. La etiqueta legible para la
interfaz va en `ETIQUETAS` dentro de `web/app.js`.

### Esquemas de herramienta

No poner `strict: true` en las de Claude: varias tienen parámetros opcionales
fuera de `required`, y el modo estricto exige que `required` liste todas las
propiedades.

## Detalles que ya han dado problemas

- **Secciones con acento.** `## Bitácora` y `## Bitacora` tienen que ser la
  misma sección, o se duplican. Lo resuelve `_clave()` en `store.py`
  normalizando acentos y mayúsculas. No volver a comparar títulos con `==`.
- **Tareas colgadas.** Si el navegador corta el stream a mitad de una tarea de
  código, `asyncio.CancelledError` la deja en `interrumpida` para que se pueda
  reintentar. Sin ese `except`, se queda en `en_curso` para siempre.
- **`CanUseToolShadowedWarning`** al arrancar el modo programador es esperado:
  las herramientas de `allowed_tools` se auto-aprueban antes del callback. Eso
  es lo que queremos; `can_use_tool` solo tiene que atrapar lo demás (Bash).
- **Git en el USB** necesita `git config --global --add safe.directory E:/janus`
  porque el sistema de ficheros no guarda permisos.

## Modelos

Claude por defecto: `claude-opus-5-5`, con thinking adaptativo y `effort`
medium para el chat, alto en modo programador. El id de GPT en `.env` hay que
confirmarlo contra la lista de modelos de OpenAI; el que está puesto es una
suposición razonable, no un dato verificado.

Las peticiones a Claude incluyen el `fallbacks` de servidor; si la cuenta no
tiene ese beta habilitado, `brain.py` reintenta sin él automáticamente.

## Seguridad del modo programador

Dos cercos, y los dos importan:

1. La tarea tiene que estar `aprobada` — y la aprobación es el usuario pulsando
   el botón, que es lo que llama a `POST /api/tareas/{id}/ejecutar`.
2. `cwd` limita al agente a la carpeta del proyecto, y `allowed_tools` no
   incluye `Bash`, así que el agente no puede ejecutar nada.

No relajar ninguno de los dos sin que el usuario lo pida explícitamente.
