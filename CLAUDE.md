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
python\python.exe -m server.main     # servidor en :8700
python\python.exe -m pytest          # tests (requirements-dev.txt)
python\python.exe -X utf8 -c "from server import tools; print(tools.run('estado_general', {}))"
```

`tests/conftest.py` redirige **todas** las rutas de `data/` a una carpeta
temporal (autouse). Un test nuevo que escriba datos tiene que pasar por ahí: un
test que llamó a `/api/sesion/reiniciar` contra el `data/` real ya vació una
sesión de chat una vez.

`python\` es un Python 3.13 portable (paquete NuGet `python`) dentro del USB,
con las dependencias instaladas en él. Nada de `.venv`: un venv queda atado a
la máquina y la letra de unidad donde se creó.

`-X utf8` hace falta en la consola de Windows: sin él, los acentos de los datos
revientan al imprimir.

`data/` **no está en git** (el repo es público). `data-ejemplo/` tiene la
estructura mínima. No commitear nunca nada de `data/`.

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

- **Escribir siempre con `store.escribir()`** (atómico: `.tmp` + `os.replace`).
  Nunca `write_text` ni `open("a")` sobre `data/`: el USB se puede sacar a
  mitad de una escritura.
- **Fechas con `store.hoy()` / `store.ahora()`**, no `date.today()`: respetan
  `JANUS_TZ` aunque el USB esté en un PC con otra zona.
- **El registro de hábitos conserva columnas** de hábitos ya quitados y el
  texto escrito a mano alrededor de la tabla (`_write_log` + `replace_table`).
- **El servidor solo atiende a sí mismo:** el middleware `solo_local` en
  `main.py` rechaza `Host` y `Origin` ajenos. Si algún día se quiere abrir a la
  red local, hay que añadir el host ahí, no quitar el middleware.

- **Secciones con acento.** `## Bitácora` y `## Bitacora` tienen que ser la
  misma sección, o se duplican. Lo resuelve `_clave()` en `store.py`
  normalizando acentos y mayúsculas. No volver a comparar títulos con `==`.
- **Tareas colgadas.** Si el navegador corta el stream a mitad de una tarea de
  código, `asyncio.CancelledError` la deja en `interrumpida` para que se pueda
  reintentar. Sin ese `except`, se queda en `en_curso` para siempre.
- **`CanUseToolShadowedWarning`** al arrancar el modo programador es esperado:
  las herramientas de `allowed_tools` se auto-aprueban antes del callback. Eso
  es lo que queremos; `can_use_tool` solo tiene que atrapar lo demás (Bash).
- **Git en el USB** necesita `git config --global --add safe.directory <unidad>:/janus`
  en cada máquina (y por cada letra de unidad), porque el sistema de ficheros
  no guarda permisos.

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
