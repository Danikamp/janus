/* Janus — cliente. Sin dependencias: solo modulos ES nativos. */

const $ = (id) => document.getElementById(id);

const el = {
  conversacion: $("conversacion"),
  vacio: $("vacio"),
  entrada: $("entrada"),
  redactor: $("redactor"),
  enviar: $("enviar"),
  cerebro: $("cerebro"),
  habitos: $("habitos"),
  proyectos: $("proyectos"),
  inbox: $("inbox"),
  inboxN: $("inbox-n"),
  formInbox: $("form-inbox"),
  inboxTexto: $("inbox-texto"),
  tareas: $("tareas"),
  fechaHoy: $("fecha-hoy"),
  subModelo: $("sub-modelo"),
  pie: $("pie"),
  voz: $("boton-voz"),
};

let estado = null;
let ocupado = false;

/* ------------------------------------------------------------ markdown */

const escapar = (t) =>
  t.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");

/** Markdown minimo y seguro: se escapa primero, se marca despues. */
function marcar(texto) {
  const bloques = [];
  // Los bloques de codigo se apartan para que el resto no los toque.
  let t = escapar(texto).replace(/```(\w*)\n([\s\S]*?)```/g, (_, lang, codigo) => {
    bloques.push(`<pre><code data-lang="${lang}">${codigo.replace(/\n$/, "")}</code></pre>`);
    return `\u0000${bloques.length - 1}\u0000`;
  });

  t = t
    .replace(/`([^`\n]+)`/g, "<code>$1</code>")
    .replace(/\*\*([^*\n]+)\*\*/g, "<strong>$1</strong>")
    .replace(/(^|[\s(])\*([^*\n]+)\*/g, "$1<em>$2</em>")
    .replace(/^###?\s+(.+)$/gm, "<h3>$1</h3>");

  // Parrafos y listas.
  const salida = [];
  let lista = null;
  for (const linea of t.split("\n")) {
    const l = linea.trim();
    const punto = l.match(/^[-*]\s+(.*)$/);
    const numero = l.match(/^(\d+)\.\s+(.*)$/);
    if (punto || numero) {
      const tipo = punto ? "ul" : "ol";
      if (lista !== tipo) {
        if (lista) salida.push(`</${lista}>`);
        salida.push(`<${tipo}>`);
        lista = tipo;
      }
      salida.push(`<li>${punto ? punto[1] : numero[2]}</li>`);
      continue;
    }
    if (lista) { salida.push(`</${lista}>`); lista = null; }
    if (!l) continue;
    salida.push(l.startsWith("<h3>") || l.startsWith("\u0000") ? l : `<p>${l}</p>`);
  }
  if (lista) salida.push(`</${lista}>`);

  return salida.join("\n").replace(/\u0000(\d+)\u0000/g, (_, i) => bloques[Number(i)]);
}

/* --------------------------------------------------------------- panel */

function pintarPanel() {
  const { habitos, proyectos, inbox, cerebros, cerebro_actual, voz } = estado;

  if (!el.cerebro.options.length) {
    el.cerebro.innerHTML = cerebros
      .map(
        (c) =>
          `<option value="${c.id}" ${c.disponible ? "" : "disabled"}>` +
          `${c.label} — ${c.modelo}${c.disponible ? "" : " (sin clave)"}</option>`
      )
      .join("");
    const activo = cerebros.find((c) => c.id === cerebro_actual && c.disponible)
      || cerebros.find((c) => c.disponible);
    if (activo) el.cerebro.value = activo.id;
    const faltan = cerebros.filter((c) => !c.disponible);
    el.subModelo.textContent = faltan.length === cerebros.length
      ? "sin claves API"
      : `voz: ${voz}`;
    if (faltan.length === cerebros.length) {
      aviso("No hay ninguna clave API configurada. Copia .env.example a .env y rellénala.");
    }
  }

  el.fechaHoy.textContent = habitos.hoy;
  const ayer = habitos.dias.at(-1) || {};
  el.habitos.innerHTML = habitos.habitos
    .map((h) => {
      const marca = ayer[h.id] || "";
      const racha = habitos.rachas[h.id] || 0;
      return `<li><button class="habito" data-habito="${h.id}" data-hecho="${marca}">
        <span class="casilla">${marca === "x" ? "✓" : ""}</span>
        <span class="nombre">${escapar(h.nombre || h.id)}</span>
        <span class="racha" data-cero="${racha === 0}">${racha}d</span>
      </button></li>`;
    })
    .join("");

  el.proyectos.innerHTML = proyectos
    .map(
      (p) => `<li class="proyecto" data-prioridad="${p.prioridad}">
        <div class="proyecto-nombre">${escapar(p.nombre)}</div>
        <div class="proyecto-paso">${escapar(limpiar(p.siguiente_paso) || "sin siguiente paso")}</div>
      </li>`
    )
    .join("");

  el.inboxN.textContent = inbox.length;
  el.inbox.innerHTML = inbox
    .map((i) => `<li>${escapar(i.replace(/\s*_\(.*?\)_\s*$/, ""))}</li>`)
    .join("");

  pintarTareas();
}

const limpiar = (t) => (t || "").replace(/^_|_$/g, "").trim();

/* Estados en los que la tarea sigue esperando una decision del usuario. */
const NOTA_ESTADO = {
  pendiente_aprobacion: "Janus escribirá ficheros en el proyecto",
  aprobada: "aprobada, pero no llegó a empezar",
  fallida: "falló el intento anterior",
  interrumpida: "se cortó a mitad",
};

function pintarTareas() {
  const abiertas = (estado.tareas || []).filter((t) => t.estado in NOTA_ESTADO);
  el.tareas.innerHTML = abiertas
    .map(
      (t) => `<div class="tarea" data-tarea="${t.id}">
        <div class="tarea-cabecera">
          <span class="tarea-titulo">${escapar(t.descripcion)}</span>
          <span class="tarea-proyecto">${escapar(t.proyecto)}</span>
        </div>
        <div class="tarea-plan">${escapar(t.plan || "(sin plan detallado)")}</div>
        <div class="tarea-botones">
          <button class="btn btn-si" data-accion="aprobar">${
            t.estado === "pendiente_aprobacion" ? "Aprobar y ejecutar" : "Reintentar"
          }</button>
          <button class="btn" data-accion="rechazar">Descartar</button>
          <span class="tarea-nota">${NOTA_ESTADO[t.estado]}</span>
        </div>
      </div>`
    )
    .join("");
}

/* ----------------------------------------------------------- conversacion */

function turno(rol) {
  el.vacio?.remove();
  const nodo = document.createElement("div");
  nodo.className = "turno";
  nodo.dataset.rol = rol;
  nodo.innerHTML = `<div class="quien">${rol === "user" ? "Tú" : "Janus"}</div><div class="cuerpo"></div>`;
  el.conversacion.append(nodo);
  abajo();
  return nodo.querySelector(".cuerpo");
}

function abajo() {
  el.conversacion.scrollTop = el.conversacion.scrollHeight;
}

function aviso(mensaje) {
  const cuerpo = turno("assistant");
  cuerpo.innerHTML = `<div class="error">${escapar(mensaje)}</div>`;
}

/** Lee un stream SSE de fetch y llama a `alEvento` con cada objeto. */
async function leerSSE(respuesta, alEvento) {
  const lector = respuesta.body.getReader();
  const decodificador = new TextDecoder();
  let resto = "";
  while (true) {
    const { done, value } = await lector.read();
    if (done) break;
    resto += decodificador.decode(value, { stream: true });
    const partes = resto.split("\n\n");
    resto = partes.pop() ?? "";
    for (const parte of partes) {
      const linea = parte.split("\n").find((l) => l.startsWith("data: "));
      if (!linea) continue;
      try {
        alEvento(JSON.parse(linea.slice(6)));
      } catch {
        /* fragmento incompleto: se ignora */
      }
    }
  }
}

/** Consume un stream de eventos y los va pintando en un turno. */
async function consumir(respuesta) {
  const cuerpo = turno("assistant");
  const texto = document.createElement("div");
  let acumulado = "";
  let pensamiento = null;

  await leerSSE(respuesta, (ev) => {
    switch (ev.type) {
      case "pensando": {
        if (!pensamiento) {
          pensamiento = document.createElement("div");
          pensamiento.className = "pensando";
          cuerpo.append(pensamiento);
        }
        pensamiento.textContent = ev.texto.slice(-240);
        break;
      }
      case "texto": {
        if (!texto.isConnected) cuerpo.append(texto);
        acumulado += ev.texto;
        texto.innerHTML = marcar(acumulado);
        texto.classList.add("cursor");
        break;
      }
      case "tool": {
        const fila = document.createElement("div");
        fila.className = "accion";
        fila.dataset.herramienta = ev.nombre;
        fila.textContent = etiquetaAccion(ev.nombre, ev.args);
        cuerpo.append(fila);
        break;
      }
      case "tool_fin": {
        const filas = cuerpo.querySelectorAll(`.accion[data-herramienta="${ev.nombre}"]`);
        const ultima = filas[filas.length - 1];
        if (ultima) ultima.dataset.estado = "hecho";
        if (ev.resultado?.error) {
          const error = document.createElement("div");
          error.className = "error";
          error.textContent = ev.resultado.error;
          cuerpo.append(error);
        }
        break;
      }
      case "error": {
        const error = document.createElement("div");
        error.className = "error";
        error.textContent = ev.mensaje;
        cuerpo.append(error);
        break;
      }
      case "estado": {
        Object.assign(estado, ev.datos);
        pintarPanel();
        break;
      }
      case "fin": {
        el.pie.textContent = ev.uso?.entrada
          ? `${ev.uso.entrada} tokens entrada · ${ev.uso.salida} salida` +
            (ev.uso.cache_lectura ? ` · ${ev.uso.cache_lectura} de caché` : "")
          : "";
        break;
      }
    }
    abajo();
  });

  texto.classList.remove("cursor");
  pensamiento?.remove();
  if (acumulado.trim() && esperandoVoz) hablar(acumulado);
  esperandoVoz = false;
}

const ETIQUETAS = {
  estado_general: "consultando tu situación",
  registrar_habito: "registrando hábito",
  listar_proyectos: "revisando proyectos",
  leer_proyecto: "leyendo proyecto",
  actualizar_proyecto: "actualizando proyecto",
  anotar_bitacora: "anotando en la bitácora",
  crear_proyecto: "creando proyecto",
  capturar_inbox: "guardando en el inbox",
  leer_inbox: "leyendo el inbox",
  quitar_inbox: "limpiando el inbox",
  escribir_diario: "escribiendo en el diario",
  leer_diario: "leyendo el diario",
  proponer_tarea_codigo: "preparando una tarea de código",
  programar: "programando",
};

function etiquetaAccion(nombre, args) {
  const base = ETIQUETAS[nombre] || nombre;
  const detalle = args?.proyecto || args?.habito || args?.file_path || args?.carpeta;
  return detalle ? `${base} · ${detalle}` : base;
}

/* --------------------------------------------------------------- acciones */

async function enviar(mensaje) {
  if (ocupado || !mensaje.trim()) return;
  ocupado = true;
  el.enviar.disabled = true;
  turno("user").innerHTML = marcar(mensaje);
  el.pie.textContent = "pensando…";

  try {
    const respuesta = await fetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ mensaje, cerebro: el.cerebro.value }),
    });
    if (!respuesta.ok) {
      aviso(`El servidor respondió ${respuesta.status}: ${await respuesta.text()}`);
    } else {
      await consumir(respuesta);
    }
  } catch (error) {
    aviso(`No pude hablar con el servidor: ${error.message}`);
  } finally {
    ocupado = false;
    el.enviar.disabled = false;
    if (el.pie.textContent === "pensando…") el.pie.textContent = "";
    el.entrada.focus();
  }
}

async function ejecutarTarea(id) {
  if (ocupado) return;
  ocupado = true;
  el.pie.textContent = "programando…";
  document.querySelector(`.tarea[data-tarea="${id}"]`)?.remove();
  try {
    const respuesta = await fetch(`/api/tareas/${id}/ejecutar`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ permitir_bash: false }),
    });
    if (!respuesta.ok) aviso(`No se pudo ejecutar: ${await respuesta.text()}`);
    else await consumir(respuesta);
  } finally {
    ocupado = false;
    el.pie.textContent = "";
  }
}

async function recargar() {
  const respuesta = await fetch("/api/estado");
  estado = await respuesta.json();
  pintarPanel();
  for (const t of estado.historial || []) {
    turno(t.rol).innerHTML = marcar(t.texto);
  }
}

/* ------------------------------------------------------------------- voz */

let reconocedor = null;
let esperandoVoz = false;

function iniciarVoz() {
  const Motor = window.SpeechRecognition || window.webkitSpeechRecognition;
  if (!Motor) {
    el.voz.disabled = true;
    el.voz.title = "Este navegador no reconoce voz. Usa Chrome o Edge.";
    return;
  }
  reconocedor = new Motor();
  reconocedor.lang = "es-ES";
  reconocedor.continuous = false;
  reconocedor.interimResults = true;

  reconocedor.addEventListener("result", (evento) => {
    const texto = Array.from(evento.results).map((r) => r[0].transcript).join("");
    el.entrada.value = texto;
    ajustarAltura();
    if (evento.results[evento.results.length - 1].isFinal) {
      esperandoVoz = true;
      el.redactor.requestSubmit();
    }
  });
  reconocedor.addEventListener("end", () => (el.voz.dataset.escuchando = "false"));
  reconocedor.addEventListener("error", (evento) => {
    el.voz.dataset.escuchando = "false";
    el.pie.textContent =
      evento.error === "not-allowed"
        ? "micrófono bloqueado: dale permiso al sitio"
        : `voz: ${evento.error}`;
  });
}

function alternarVoz() {
  if (!reconocedor) return;
  if (el.voz.dataset.escuchando === "true") {
    reconocedor.stop();
    return;
  }
  el.entrada.value = "";
  el.voz.dataset.escuchando = "true";
  el.pie.textContent = "escuchando…";
  reconocedor.start();
}

/** Lee la respuesta en voz alta, sin el markdown. */
function hablar(texto) {
  if (!window.speechSynthesis) return;
  const limpio = texto
    .replace(/```[\s\S]*?```/g, " bloque de código ")
    .replace(/[*_`#>]/g, "")
    .slice(0, 1200);
  const voz = new SpeechSynthesisUtterance(limpio);
  voz.lang = "es-ES";
  voz.rate = 1.05;
  speechSynthesis.cancel();
  speechSynthesis.speak(voz);
}

/* ----------------------------------------------------------------- eventos */

function ajustarAltura() {
  el.entrada.style.height = "auto";
  el.entrada.style.height = `${Math.min(el.entrada.scrollHeight, 180)}px`;
}

el.redactor.addEventListener("submit", (evento) => {
  evento.preventDefault();
  const texto = el.entrada.value;
  el.entrada.value = "";
  ajustarAltura();
  enviar(texto);
});

el.entrada.addEventListener("input", ajustarAltura);
el.entrada.addEventListener("keydown", (evento) => {
  if (evento.key === "Enter" && !evento.shiftKey) {
    evento.preventDefault();
    el.redactor.requestSubmit();
  }
});

el.voz.addEventListener("click", alternarVoz);

el.habitos.addEventListener("click", async (evento) => {
  const boton = evento.target.closest(".habito");
  if (!boton) return;
  const hecho = boton.dataset.hecho !== "x";
  const respuesta = await fetch("/api/habito", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ habito: boton.dataset.habito, hecho }),
  });
  estado.habitos = (await respuesta.json()).habitos;
  pintarPanel();
});

el.formInbox.addEventListener("submit", async (evento) => {
  evento.preventDefault();
  const texto = el.inboxTexto.value.trim();
  if (!texto) return;
  el.inboxTexto.value = "";
  const respuesta = await fetch("/api/inbox", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ texto }),
  });
  estado.inbox = (await respuesta.json()).inbox;
  pintarPanel();
});

el.tareas.addEventListener("click", async (evento) => {
  const boton = evento.target.closest("[data-accion]");
  if (!boton) return;
  const id = boton.closest(".tarea").dataset.tarea;
  if (boton.dataset.accion === "aprobar") {
    ejecutarTarea(id);
  } else {
    await fetch(`/api/tareas/${id}/rechazar`, { method: "POST" });
    estado.tareas = (await (await fetch("/api/tareas")).json()).tareas;
    pintarTareas();
  }
});

document.addEventListener("click", (evento) => {
  const chip = evento.target.closest(".chip");
  if (chip) enviar(chip.dataset.prompt);
});

iniciarVoz();
recargar().catch((error) => aviso(`No pude cargar el estado: ${error.message}`));
el.entrada.focus();
