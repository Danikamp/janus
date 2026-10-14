# Janus

Asistente personal para hábitos y proyectos. Corre en tu máquina, guarda todo en
markdown y puede programar en tus proyectos con tu permiso.

## Arrancar

Doble clic en **`janus.cmd`**. Arranca con el Python portable de `python\`,
crea `.env` si falta y abre <http://127.0.0.1:8700>.

`python\` no está en el repo (pesa ~60 MB). Si clonas en limpio:

1. Descarga el paquete NuGet [`python`](https://www.nuget.org/packages/python)
   3.13, ábrelo como zip y copia su carpeta `tools\` como `python\`.
2. `python\python.exe -m pip install -r requirements.txt`
3. `xcopy /e /i data-ejemplo data`

Para usar el chat, abre `.env` y pon al menos una clave. Sin claves, Janus
funciona igual como tablero de hábitos, proyectos e inbox:

```
ANTHROPIC_API_KEY=sk-ant-...      # para el cerebro Claude
OPENAI_API_KEY=sk-...             # para el cerebro GPT
```

Para pararlo: `Ctrl+C` en la ventana negra.

## Cómo está montado

```
janus.cmd              lanzador
server/
  config.py            configuración desde .env
  store.py             LA CAPA IMPORTANTE: lee y escribe los markdown
  prompts.py           quién es Janus y cómo trabaja
  tools.py             las 13 cosas que Janus puede hacer
  brain.py             Claude o GPT, misma interfaz
  coder.py             modo programador (Claude Agent SDK)
  main.py              servidor web y API
web/                   interfaz (HTML + CSS + JS, sin build)
data/                  TUS DATOS
  habitos/             definición y registro diario
  proyectos/<id>/      un markdown por proyecto
  diario/<fecha>.md    una nota por día
  inbox.md             captura rápida
```

La regla de oro: **`data/` es la verdad**. El código es reemplazable; esos
ficheros no. Puedes editarlos a mano en cualquier momento, con cualquier editor,
y Janus los leerá igual.

## Los cuatro sitios donde va la información

| Dónde | Para qué |
|---|---|
| `habitos/` | solo cumplimiento diario: hecho / no hecho |
| `diario/` | lo que pasó y cómo fue |
| `proyectos/` | estado, siguiente paso, decisiones y pendientes |
| `inbox.md` | lo que aún no sabes dónde va |

Si Janus guarda algo donde no toca, lo que hay que cambiar es `prompts.py`, no
el código.

## Hábitos

Se definen a mano en `data/habitos/habitos.md`, en una tabla. Añade una fila y
Janus lo recoge en el siguiente arranque. El `id` es lo que usa internamente;
el nombre es lo que ves tú.

El registro mensual vive en `data/habitos/registro/YYYY-MM.md`. Puedes marcar
los hábitos desde la barra lateral o diciéndoselo a Janus.

## Modo programador

Janus nunca escribe código por su cuenta. El circuito es:

1. Le pides que programe algo en un proyecto.
2. Lee el proyecto y **propone** una tarea con un plan: qué ficheros tocaría.
3. Te aparece una tarjeta en la interfaz con el plan y dos botones.
4. Solo si pulsas **Aprobar y ejecutar** entra el agente a escribir.

Dentro de la tarea, el agente está limitado a:

- la carpeta del proyecto y nada más (`cwd`);
- leer y escribir ficheros, nada que ejecute comandos (sin `Bash`).

Por eso, cuando un paso necesite instalar algo o lanzar tests, Janus te lo
escribe como instrucción en vez de hacerlo. Es a propósito.

Al terminar, la tarea queda anotada en la bitácora del proyecto.

### Dónde escribe el código

Por defecto en `data/proyectos/<id>/codigo/`. Si el proyecto ya tiene un repo
en otro sitio, pon la ruta en el frontmatter de su markdown:

```yaml
repo: C:\dev\conduce-hoy
```

### Requisito

El modo programador usa el motor de Claude Code. Se detecta solo si tienes la
extensión de VS Code instalada; si no, instálalo con:

```
npm install -g @anthropic-ai/claude-code
```

Usa tu sesión de Claude Code, así que **esta parte funciona sin clave API**.

## Voz

Por defecto (`JANUS_VOICE=browser`) el dictado y la lectura los hace el
navegador: gratis y sin instalar nada, pero necesita Chrome o Edge y envía el
audio a los servidores del navegador para reconocerlo.

Con `JANUS_VOICE=openai` se transcribe con Whisper y se sintetiza con TTS en el
servidor. Requiere `OPENAI_API_KEY` y tiene coste por uso.

## Cambiar de cerebro

El desplegable de arriba a la izquierda elige entre Claude y GPT. Se puede
cambiar a mitad de conversación: al cruzar, solo pasan los turnos de texto
(el razonamiento interno y los resultados de herramientas son propios de cada
proveedor y no se pueden reenviar al otro).

## Mover Janus al portátil

Está pensado para eso: vive en un USB con su propio Python. Enchúfalo en
cualquier Windows y doble clic en `janus.cmd`. No hay que instalar nada.

El repositorio solo guarda el código. `data/`, `python\` y `.env` no se suben
(`.gitignore`): tus datos son personales y las claves también. **La copia de
seguridad de `data/` es cosa tuya**: cópiala de vez en cuando a otro disco.

## Lo que todavía no hace

- No tiene recordatorios ni nada programado: solo responde cuando le hablas.
- No lee tu calendario ni tu correo.
- Solo un usuario, sin contraseña. Escucha en `127.0.0.1`, así que no es
  accesible desde fuera de la máquina — no lo expongas a internet tal cual.
