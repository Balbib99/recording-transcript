/* Reuniones - logica de la PWA.
   Sin dependencias: fetch, un poco de DOM y enrutado por hash. */

const $ = (sel) => document.querySelector(sel);

const CLAVE_TOKEN = 'rc_token';
const CLAVE_CACHE = 'rc_ultima_lista';

let token = localStorage.getItem(CLAVE_TOKEN) || '';
let temporizador = null;
let estadoDetalle = null;   // { job, datos } de la reunion abierta
let trabajoAbierto = null;  // el job de la pantalla de detalle, este hecho o no
let seleccion = null;       // Set de ids mientras se eligen grabaciones; null fuera de ese modo
let ultimosDatos = { trabajos: [] };   // lo ultimo que se pinto en la lista
let borradoPendiente = null;           // { ids, desdeDetalle } esperando confirmacion

/* El token se puede pasar en la URL (?token=...) para no teclear 64 caracteres
   en el movil. Se guarda y se borra de la barra de direcciones en el acto, para
   que no quede en el historial ni se comparta sin querer al enviar el enlace. */
(function tokenEnLaUrl() {
  const parametros = new URLSearchParams(location.search);
  const recibido = parametros.get('token');
  if (!recibido) return;
  token = recibido.trim();
  localStorage.setItem(CLAVE_TOKEN, token);
  parametros.delete('token');
  const limpia = location.pathname + (parametros.toString() ? `?${parametros}` : '')
                 + location.hash;
  history.replaceState(null, '', limpia);
})();

// ----------------------------------------------------------------- utiles

const reloj = (s) => {
  s = Math.max(0, Math.floor(s || 0));
  const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), seg = s % 60;
  return h ? `${h}:${String(m).padStart(2, '0')}:${String(seg).padStart(2, '0')}`
           : `${m}:${String(seg).padStart(2, '0')}`;
};

const fecha = (iso) => {
  if (!iso) return '';
  const d = new Date(iso);
  if (isNaN(d)) return '';
  const hoy = new Date();
  const mismoDia = d.toDateString() === hoy.toDateString();
  return mismoDia
    ? `hoy ${d.toLocaleTimeString('es', { hour: '2-digit', minute: '2-digit' })}`
    : d.toLocaleDateString('es', { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' });
};

function avisar(texto, malo = false) {
  const el = $('#aviso');
  el.textContent = texto;
  el.classList.toggle('malo', malo);
  el.classList.remove('oculto');
  clearTimeout(avisar._t);
  avisar._t = setTimeout(() => el.classList.add('oculto'), 3500);
}

/* La Pi no tiene un estado propio que consultar: si la peticion ha llegado,
   esta viva. Por eso el indicador de conexion es tambien su celda. */
function enLinea(si) {
  $('#indicador')?.classList.toggle('sin-red', !si);
  const pi = $('#texto-pi');
  if (pi) pi.textContent = si ? 'activa' : 'sin conexión';
}

// -------------------------------------------------------------------- API

async function api(ruta, opciones = {}) {
  const respuesta = await fetch(`api${ruta}`, {
    ...opciones,
    headers: { Authorization: `Bearer ${token}`, ...(opciones.headers || {}) },
  });
  if (respuesta.status === 401) {
    localStorage.removeItem(CLAVE_TOKEN);
    token = '';
    mostrar('token');
    throw new Error('Token rechazado');
  }
  if (!respuesta.ok) throw new Error(`HTTP ${respuesta.status}`);
  return respuesta.json();
}

// ------------------------------------------------------------- navegacion

function mostrar(vista) {
  for (const v of ['token', 'lista', 'detalle']) {
    $(`#vista-${v}`).classList.toggle('oculto', v !== vista);
  }
}

function enrutar() {
  // Un dialogo abierto no se entera de que cambia la pantalla: al volver atras
  // con el boton del movil se quedaba flotando encima de otra reunion.
  for (const dialogo of document.querySelectorAll('dialog[open]')) dialogo.close();
  if (seleccion) {
    seleccion = null;
    $('#vista-lista')?.classList.remove('seleccionando');
  }

  if (!token) { mostrar('token'); return; }
  const ruta = location.hash.slice(1);
  if (ruta.startsWith('/j/')) {
    abrirDetalle(ruta.slice(3));
  } else {
    mostrar('lista');
    cargarLista();
  }
}

// ---------------------------------------------------------------- listado

const ETIQUETA_ESTADO = {
  pendiente: 'En cola',
  procesando: 'Transcribiendo',
  hecho: 'Lista',
  fallido: 'Fallo',
};

function pintarLista(datos) {
  const { trabajos, resumen } = datos;
  ultimosDatos = datos;
  pintarEstadoPC(datos.worker);

  // Si algo elegido ya no esta (se borro desde otro sitio), se descarta.
  if (seleccion) {
    const vivas = new Set(trabajos.map((t) => t.id));
    for (const id of [...seleccion]) if (!vivas.has(id)) seleccion.delete(id);
  }
  const contenedor = $('#lista');
  contenedor.innerHTML = '';

  const total = trabajos.length;
  $('#resumen').textContent = `${total} ${total === 1 ? 'grabación' : 'grabaciones'}`;

  if (resumen) {
    const enEspera = resumen.pendiente + resumen.procesando;
    if (enEspera) {
      $('#resumen').textContent += ` · ${enEspera} en cola`;
    }
    $('#texto-cola').textContent = enEspera
      ? String(enEspera)
      : 'vacía';
  }

  $('#lista-vacia').classList.toggle('oculto', total > 0);

  for (const t of trabajos) contenedor.append(tarjetaDe(t));
  if (seleccion) actualizarSeleccion();
}

function tarjetaDe(t) {
  const roto = t.estado === 'fallido';
  const eligiendo = seleccion !== null;

  // La tarjeta fallida lleva dentro su boton de reintentar, y un boton dentro
  // de otro no es HTML valido: se queda como caja y se entra por el titulo.
  // Al elegir ya no hay nada dentro que pulsar, y vuelve a ser un boton.
  const conControles = roto && !eligiendo;
  const caja = document.createElement(conControles ? 'div' : 'button');
  caja.className = `tarjeta${roto ? ' rota' : ''}`;
  caja.dataset.id = t.id;
  if (!conControles) {
    caja.type = 'button';
    if (eligiendo) {
      const elegida = seleccion.has(t.id);
      caja.classList.toggle('elegida', elegida);
      caja.setAttribute('aria-pressed', String(elegida));
      caja.onclick = () => alternar(t.id);
    } else {
      caja.onclick = () => { location.hash = `/j/${t.id}`; };
    }
  }

  const cabecera = document.createElement('h2');
  if (eligiendo) {
    const marca = document.createElement('span');
    marca.className = 'marca';
    marca.setAttribute('aria-hidden', 'true');
    cabecera.append(marca);
  }
  const titulo = document.createElement(conControles ? 'a' : 'span');
  titulo.className = 'titulo';
  titulo.textContent = t.titulo || t.fichero;
  if (conControles) titulo.href = `#/j/${t.id}`;
  const estado = document.createElement('span');
  estado.className = `estado ${t.estado}`;
  estado.textContent = ETIQUETA_ESTADO[t.estado] || t.estado;
  cabecera.append(titulo, estado);
  caja.append(cabecera);

  const partes = [];
  // La duracion no se sabe hasta que esta transcrita: hasta entonces, el peso
  // del fichero es lo unico que dice si es una reunion larga o una nota.
  if (t.duracion) partes.push(reloj(t.duracion));
  else if (t.bytes) partes.push(`${(t.bytes / 1e6).toFixed(1)} MB`);
  if (t.hablantes) partes.push(`${t.hablantes} ${t.hablantes === 1 ? 'voz' : 'voces'}`);
  if (t.idioma) partes.push(t.idioma);
  partes.push(fecha(t.creado));
  const meta = document.createElement('div');
  meta.className = 'meta-mono';
  meta.textContent = partes.filter(Boolean).join(' · ');
  caja.append(meta);

  if (t.estado === 'procesando') {
    const avance = document.createElement('div');
    avance.className = 'avance';
    avance.append(document.createElement('span'));
    caja.append(avance);
  }

  if (roto) {
    const motivo = document.createElement('div');
    motivo.className = 'motivo';
    motivo.textContent = (t.error || 'motivo desconocido').slice(0, 140);
    caja.append(motivo);
    if (conControles) {
      const reintentar = document.createElement('button');
      reintentar.type = 'button';
      reintentar.className = 'reintentar';
      reintentar.textContent = 'Volver a la cola';
      reintentar.onclick = () => reencolar(t.id);
      caja.append(reintentar);
    }
  } else if (t.voces?.length) {
    caja.append(filaDeVoces(t.voces));
  }

  return caja;
}

/* Las iniciales de cada voz y cuantas siguen sin nombre: desde la lista ya se
   ve que reuniones estan a medio terminar, sin abrirlas una por una. */
function filaDeVoces(voces) {
  const fila = document.createElement('div');
  fila.className = 'voces-mini';

  voces.forEach((nombre, i) => {
    const circulo = document.createElement('span');
    circulo.className = nombre ? `inicial voz-${i % 6}` : 'inicial';
    circulo.textContent = nombre ? (nombre.trim()[0] || '?').toUpperCase() : '?';
    fila.append(circulo);
  });

  const sinNombre = voces.filter((n) => !n).length;
  const cuenta = document.createElement('span');
  cuenta.className = 'voces-cuenta';
  cuenta.textContent = sinNombre ? `${sinNombre} sin nombre` : 'todas nombradas';
  fila.append(cuenta);

  return fila;
}

async function reencolar(id) {
  try {
    await api(`/jobs/${id}/reencolar`, { method: 'POST' });
    avisar('De vuelta en la cola');
    cargarLista(true);
  } catch (e) {
    avisar('No se pudo devolver a la cola', true);
  }
}

async function cargarLista(silencioso = false) {
  try {
    const [lista, estado] = await Promise.all([
      api('/jobs?limite=100'),
      api('/estado'),
    ]);
    const datos = { trabajos: lista.trabajos, resumen: estado.trabajos,
                    worker: estado.worker };
    localStorage.setItem(CLAVE_CACHE, JSON.stringify(datos));
    pintarLista(datos);
    enLinea(true);
    programarRefresco(lista.trabajos);
  } catch (e) {
    enLinea(false);
    const guardado = localStorage.getItem(CLAVE_CACHE);
    if (guardado) {
      pintarLista(JSON.parse(guardado));
      if (!silencioso) avisar('Sin conexión: mostrando lo último guardado');
    } else if (!silencioso) {
      avisar('No se pudo conectar con el servidor', true);
    }
  }
}

/* Mientras haya algo en marcha se refresca solo; si no, se deja quieto. */
function programarRefresco(trabajos) {
  clearTimeout(temporizador);
  const hayMovimiento = trabajos.some(
    (t) => t.estado === 'pendiente' || t.estado === 'procesando');
  if (hayMovimiento && !document.hidden && !seleccion) {
    temporizador = setTimeout(() => cargarLista(true), 8000);
  }
}

// --------------------------------------------- ajustes de la grabacion

let ajustesPendientes = null;   // { fichero } al subir, o { job } al editar

function pedirAjustes(fichero = null, job = null) {
  const dialogo = $('#dialogo-ajustes');
  ajustesPendientes = { fichero, job };

  const subiendo = Boolean(fichero);
  $('#ajustes-titulo').textContent = subiendo ? 'Antes de subir' : 'Ajustes';
  $('#ajustes-fichero').textContent = subiendo
    ? `${fichero.name} · ${(fichero.size / 1e6).toFixed(1)} MB`
    : 'Se aplicarán cuando el worker la coja';
  $('#ajustes-aceptar').textContent = subiendo ? 'Subir' : 'Guardar';

  $('#campo-titulo').value = subiendo
    ? fichero.name.replace(/\.[^.]+$/, '')
    : (job.titulo || '');
  $('#campo-hablantes').value = job?.esperados || '';
  $('#campo-vocabulario').value = job?.vocabulario || vocabularioRecordado();

  dialogo.showModal();
}

/* El vocabulario suele repetirse entre reuniones del mismo tema, asi que se
   propone el ultimo usado. Se queda en el dispositivo. */
function vocabularioRecordado() {
  try { return localStorage.getItem('rc_vocabulario') || ''; } catch { return ''; }
}

function recordarVocabulario(valor) {
  try {
    if (valor) localStorage.setItem('rc_vocabulario', valor);
    else localStorage.removeItem('rc_vocabulario');
  } catch { /* modo privado */ }
}

async function confirmarAjustes() {
  if (!ajustesPendientes) return;
  const { fichero, job } = ajustesPendientes;
  const titulo = $('#campo-titulo').value.trim();
  const hablantes = $('#campo-hablantes').value.trim();
  const vocabulario = $('#campo-vocabulario').value.trim();
  recordarVocabulario(vocabulario);
  ajustesPendientes = null;

  if (fichero) {
    subir(fichero, titulo || null, { hablantes, vocabulario });
    return;
  }

  try {
    await api(`/jobs/${job.id}/ajustes`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ titulo, vocabulario, esperados: hablantes || 0 }),
    });
    avisar('Ajustes guardados');
    if (location.hash) abrirDetalle(job.id); else cargarLista(true);
  } catch (e) {
    avisar('No se pudieron guardar', true);
  }
}

$('#form-ajustes')?.addEventListener('submit', (e) => {
  if (e.submitter?.value !== 'guardar') { ajustesPendientes = null; return; }
  confirmarAjustes();
});

// ------------------------------------------------------- estado del PC

function hace(segundos) {
  if (segundos == null) return 'nunca visto';
  if (segundos < 90) return 'hace un momento';
  const m = Math.round(segundos / 60);
  if (m < 60) return `hace ${m} min`;
  const h = Math.round(m / 60);
  return h < 48 ? `hace ${h} h` : `hace ${Math.round(h / 24)} días`;
}

function pintarEstadoPC(worker) {
  const punto = $('#punto-pc');
  const texto = $('#texto-pc');
  if (!punto || !texto) return;

  if (!worker) {
    punto.className = 'punto-pc';
    texto.textContent = 'sin datos';
    return;
  }

  // La celda es estrecha, asi que cuando el PC no responde dice desde cuando,
  // que es el dato util: el punto ambar y el boton de abajo ya dicen el resto.
  punto.className = `punto-pc ${worker.vivo ? 'vivo' : 'dormido'}`;
  texto.textContent = worker.vivo ? 'en marcha' : hace(worker.segundos);
  texto.title = worker.vivo
    ? `El worker ${worker.nombre || ''} esta pidiendo trabajo`.trim()
    : 'El worker no da señales de vida';

  // El boton solo aparece si hace falta y si la Pi sabe a quien despertar.
  $('#boton-despertar')?.classList.toggle(
    'oculto', worker.vivo || !worker.puede_despertarse);
}

async function despertarPC() {
  const boton = $('#boton-despertar');
  const etiqueta = $('#etiqueta-despertar');
  boton.disabled = true;
  if (etiqueta) etiqueta.textContent = 'Enviando...';
  try {
    const r = await api('/despertar', { method: 'POST' });
    if (r.enviado) {
      avisar('Paquete enviado. El PC debería encenderse en un minuto');
      esperarAlPC();
    } else {
      avisar(r.motivo || 'No hizo falta');
      cargarLista(true);
    }
  } catch (e) {
    avisar('No se pudo enviar la señal', true);
  } finally {
    boton.disabled = false;
    if (etiqueta) etiqueta.textContent = 'Despertar el PC';
  }
}

/* Tras pulsar, se consulta mas a menudo durante dos minutos: la gracia del
   mando es ver confirmado que el PC ha despertado, no fiarse del envio. */
function esperarAlPC(intentos = 24) {
  if (intentos <= 0) return;
  setTimeout(async () => {
    try {
      const estado = await api('/estado');
      pintarEstadoPC(estado.worker);
      if (estado.worker?.vivo) {
        avisar('El PC ya está en marcha');
        cargarLista(true);
        return;
      }
    } catch (e) { /* sin red: se reintenta */ }
    esperarAlPC(intentos - 1);
  }, 5000);
}

// ----------------------------------------------------------------- subida

function subir(fichero, titulo = null, extras = {}) {
  if (!fichero) return;

  const datos = new FormData();
  datos.append('file', fichero);
  datos.append('titulo', titulo || fichero.name.replace(/\.[^.]+$/, ''));
  if (extras.vocabulario) datos.append('vocabulario', extras.vocabulario);
  if (extras.hablantes) datos.append('esperados', extras.hablantes);

  const peticion = new XMLHttpRequest();
  peticion.open('POST', 'api/jobs');
  peticion.setRequestHeader('Authorization', `Bearer ${token}`);

  $('#progreso').classList.remove('oculto');
  $('#progreso-nombre').textContent = fichero.name;

  peticion.upload.onprogress = (e) => {
    if (!e.lengthComputable) return;
    const pct = Math.round((e.loaded / e.total) * 100);
    $('#progreso-pct').textContent = `${pct}%`;
    $('#progreso-relleno').style.width = `${pct}%`;
  };

  peticion.onload = () => {
    $('#progreso').classList.add('oculto');
    $('#progreso-relleno').style.width = '0';
    if (peticion.status === 201) {
      const job = JSON.parse(peticion.responseText);
      avisar(job.duplicado ? 'Esa grabación ya estaba subida' : 'Subida. Esperando al worker');
      cargarLista(true);
    } else if (peticion.status === 401) {
      localStorage.removeItem(CLAVE_TOKEN); token = ''; mostrar('token');
    } else {
      let detalle = `Error ${peticion.status}`;
      try { detalle = JSON.parse(peticion.responseText).detail || detalle; } catch {}
      avisar(detalle, true);
    }
  };

  peticion.onerror = () => {
    $('#progreso').classList.add('oculto');
    avisar('Fallo la subida', true);
  };

  peticion.send(datos);
}

// ---------------------------------------------------------------- detalle

async function abrirDetalle(id) {
  mostrar('detalle');
  trabajoAbierto = null;
  const caja = $('#detalle');
  caja.innerHTML = '<p class="apagado">Cargando...</p>';

  let job;
  try {
    job = await api(`/jobs/${id}`);
  } catch {
    caja.innerHTML = '<p class="error">No se pudo cargar</p>';
    return;
  }
  trabajoAbierto = job;

  $('#detalle-titulo').textContent = job.titulo || job.fichero;

  if (job.estado !== 'hecho') {
    caja.innerHTML = '';
    caja.append(...encabezado(job));

    const mensajes = {
      pendiente: 'En cola. Se transcribirá cuando el worker esté encendido.',
      procesando: 'Transcribiendo ahora mismo...',
      fallido: `Fallo: ${job.error || 'motivo desconocido'}`,
    };
    const parrafo = document.createElement('p');
    parrafo.className = job.estado === 'fallido' ? 'error' : 'apagado';
    parrafo.textContent = mensajes[job.estado] || job.estado;
    caja.append(parrafo);

    // Mientras espera todavia se puede afinar: cuanta gente habla y que
    // palabras raras van a salir. Despues ya no sirve de nada.
    if (job.estado === 'pendiente') {
      const resumen = document.createElement('dl');
      resumen.className = 'ficha';
      for (const [clave, valor] of [
        ['Personas', job.esperados || 'las que detecte'],
        ['Vocabulario', job.vocabulario || 'el general del config.toml'],
      ]) {
        const dt = document.createElement('dt'); dt.textContent = clave;
        const dd = document.createElement('dd'); dd.textContent = valor;
        resumen.append(dt, dd);
      }
      const boton = document.createElement('button');
      boton.className = 'principal';
      boton.textContent = 'Ajustar antes de transcribir';
      boton.onclick = () => pedirAjustes(null, job);
      caja.append(resumen, boton);
    }

    if (job.estado === 'fallido') {
      const boton = document.createElement('button');
      boton.className = 'principal';
      boton.style.marginTop = '16px';
      boton.textContent = 'Volver a la cola';
      boton.onclick = () => { reencolar(job.id); location.hash = ''; };
      caja.append(boton);
    }
    return;
  }

  let datos;
  try {
    datos = await api(`/jobs/${id}/transcripcion`);
  } catch {
    caja.innerHTML = '<p class="error">No se pudo cargar la transcripción</p>';
    return;
  }
  caja.dataset.texto = datos.texto || '';
  estadoDetalle = { job, datos };
  pintarDetalle(caja, job, datos);
}

/* Titulo grande y fecha, lo mismo para una reunion hecha que para una que
   todavia espera. En la barra de arriba solo cabe el titulo recortado. */
function encabezado(job) {
  const titulo = document.createElement('h2');
  titulo.className = 'detalle-titulo';
  titulo.textContent = job.titulo || job.fichero;
  const cuando = document.createElement('div');
  cuando.className = 'detalle-fecha';
  cuando.textContent = fecha(job.creado);
  return [titulo, cuando];
}

/* La ficha tecnica: con que se transcribio y cuanto costo. Al final, el
   vocabulario que se aplico, que explica por que salio lo que salio. */
function fichaTecnica(job, datos) {
  const ficha = document.createElement('div');
  ficha.className = 'datos';

  const rejilla = document.createElement('div');
  rejilla.className = 'datos-rejilla';
  const celdas = [
    ['Duración', reloj(datos.duracion) || '-'],
    ['Voces', String((datos.hablantes || []).length || '-')],
    ['Idioma', datos.idioma || '-'],
    ['Modelo', datos.modelo || '-'],
    ['Proceso', datos.segundos_de_proceso ? reloj(datos.segundos_de_proceso) : '-'],
    ['Equipo', datos.procesado_por || '-'],
  ];
  for (const [clave, valor] of celdas) {
    const celda = document.createElement('div');
    celda.className = 'dato';
    const nombre = document.createElement('span');
    nombre.className = 'dato-clave';
    nombre.textContent = clave;
    const caja = document.createElement('span');
    caja.className = 'dato-valor';
    const dentro = document.createElement('span');
    dentro.textContent = valor;
    caja.append(dentro);
    celda.append(nombre, caja);
    rejilla.append(celda);
  }

  const vocabulario = document.createElement('div');
  vocabulario.className = 'dato-ancho';
  const clave = document.createElement('span');
  clave.className = 'dato-clave';
  clave.textContent = 'Vocabulario';
  const valor = document.createElement('span');
  valor.className = 'dato-valor';
  const terminos = (job.vocabulario || '').split(',').map((t) => t.trim()).filter(Boolean);
  valor.textContent = terminos.length
    ? terminos.join(' · ')
    : 'solo el general del config.toml';
  vocabulario.append(clave, valor);

  ficha.append(rejilla, vocabulario);
  return ficha;
}

function pintarDetalle(caja, job, datos) {
  caja.innerHTML = '';
  caja.append(...encabezado(job), fichaTecnica(job, datos));

  // Un color estable por voz, segun su orden en la reunion
  const colorDe = new Map();
  (datos.hablantes || []).forEach((h, i) => colorDe.set(h.etiqueta, i % 6));

  if (datos.hablantes?.length) {
    const fila = document.createElement('div');
    fila.className = 'hablantes';
    for (const h of datos.hablantes) {
      const sinNombrar = h.nombre === h.etiqueta;
      const chip = document.createElement('button');
      chip.type = 'button';
      chip.className = `chip editable${sinNombrar ? ' sin-nombrar' : ''}`;
      chip.title = 'Tocar para poner el nombre';

      const inicial = document.createElement('span');
      inicial.className = sinNombrar
        ? 'inicial' : `inicial voz-${colorDe.get(h.etiqueta) ?? 0}`;
      inicial.textContent = sinNombrar
        ? '?' : (h.nombre.trim()[0] || '?').toUpperCase();

      const nombre = document.createElement('span');
      nombre.textContent = sinNombrar ? 'Ponle nombre' : h.nombre;

      const tiempo = document.createElement('span');
      tiempo.className = 'tiempo';
      tiempo.textContent = reloj(h.segundos);

      chip.append(inicial, nombre, tiempo);
      chip.onclick = () => pedirNombre(h);
      fila.append(chip);
    }
    caja.append(fila);
  }

  const transcripcion = document.createElement('div');
  transcripcion.className = 'transcripcion';
  for (const t of datos.turnos || []) {
    const bloque = document.createElement('article');
    bloque.className = 'turno';

    const cuando = document.createElement('div');
    cuando.className = 'turno-tiempo';
    cuando.textContent = reloj(t.inicio);

    const cuerpo = document.createElement('div');
    const quien = document.createElement('div');
    quien.className = `turno-hablante hablante-${colorDe.get(t.hablante) ?? 0}`;
    quien.textContent = (datos.hablantes || []).find((h) => h.etiqueta === t.hablante)?.nombre
                        || t.hablante;
    const parrafo = document.createElement('p');
    parrafo.textContent = t.texto;
    cuerpo.append(quien, parrafo);

    bloque.append(cuando, cuerpo);
    transcripcion.append(bloque);
  }
  caja.append(transcripcion);
}

// --------------------------------- cambiar el nombre y eliminar grabaciones

function abrirMenu() {
  if (!trabajoAbierto) return avisar('Espera a que cargue la grabación');
  $('#acciones-titulo').textContent = trabajoAbierto.titulo || trabajoAbierto.fichero;
  $('#dialogo-acciones').showModal();
}

function pedirTitulo() {
  const campo = $('#campo-nuevo-titulo');
  $('#nombre-pista').textContent = trabajoAbierto.fichero;
  campo.value = trabajoAbierto.titulo || '';
  $('#dialogo-nombre').showModal();
  campo.focus();
  campo.select();
}

async function guardarTitulo(titulo) {
  const job = trabajoAbierto;
  if (!job || !titulo || titulo === job.titulo) return;
  try {
    await api(`/jobs/${job.id}/ajustes`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ titulo }),
    });
    avisar('Nombre cambiado');
    abrirDetalle(job.id);
  } catch (e) {
    avisar('No se pudo cambiar el nombre', true);
  }
}

/* Sirve igual para una (desde el detalle) que para varias (desde la lista). */
function pedirBorradoDe(trabajos, desdeDetalle) {
  borradoPendiente = { ids: trabajos.map((t) => t.id), desdeDetalle };
  const varias = trabajos.length > 1;
  const enMarcha = trabajos.filter((t) => t.estado === 'procesando').length;

  $('#borrar-pregunta').textContent = varias
    ? `¿Eliminar ${trabajos.length} grabaciones?`
    : '¿Eliminar esta grabación?';
  $('#borrar-aceptar').textContent = varias ? `Eliminar ${trabajos.length}` : 'Eliminar';

  // Los nombres, para comprobar antes de confirmar. Con muchas, los primeros.
  const caja = $('#borrar-titulo');
  caja.textContent = '';
  const nombres = trabajos.map((t) => t.titulo || t.fichero);
  for (const nombre of nombres.slice(0, 5)) {
    const linea = document.createElement('div');
    linea.textContent = nombre;
    caja.append(linea);
  }
  if (nombres.length > 5) {
    const resto = document.createElement('div');
    resto.className = 'apagado';
    resto.textContent = `y ${nombres.length - 5} más`;
    caja.append(resto);
  }

  // Un trabajo en marcha se puede borrar (hace falta cuando el PC murio a
  // medias y no se va a mover solo), pero conviene saber que pasa con el PC.
  let aviso;
  if (!varias) {
    aviso = enMarcha
      ? 'Se está transcribiendo ahora: el PC terminará el trabajo y lo descartará. Se borra también el audio. No se puede deshacer.'
      : 'Se borran el audio y la transcripción de la Pi. No se puede deshacer.';
  } else {
    aviso = 'Se borran los audios y las transcripciones de la Pi. No se puede deshacer.';
    if (enMarcha) {
      aviso += enMarcha === 1
        ? ' Una se está transcribiendo ahora: el PC terminará ese trabajo y lo descartará.'
        : ` ${enMarcha} se están transcribiendo ahora: el PC terminará esos trabajos y los descartará.`;
    }
  }
  $('#borrar-aviso').textContent = aviso;
  $('#dialogo-borrar').showModal();
}

async function confirmarBorrado() {
  const pendiente = borradoPendiente;
  borradoPendiente = null;
  if (!pendiente) return;

  const borradas = [];
  let fallos = 0;
  for (const id of pendiente.ids) {
    try {
      await api(`/jobs/${id}`, { method: 'DELETE' });
      borradas.push(id);
    } catch (e) {
      // Ya no estaba (se borro desde otro sitio): el objetivo esta cumplido.
      if (e.message === 'HTTP 404') borradas.push(id); else fallos++;
    }
  }

  if (pendiente.desdeDetalle) {
    if (fallos) return avisar('No se pudo eliminar', true);
    trabajoAbierto = null;
    estadoDetalle = null;
    avisar('Grabación eliminada');
    location.hash = '';   // vuelve a la lista, que se recarga sola
    return;
  }

  // Desde la lista: se quitan ya de lo pintado, sin esperar a la recarga.
  ultimosDatos = {
    ...ultimosDatos,
    trabajos: ultimosDatos.trabajos.filter((t) => !borradas.includes(t.id)),
  };
  salirDeSeleccion();

  if (!fallos) {
    avisar(borradas.length === 1 ? 'Grabación eliminada'
                                 : `${borradas.length} grabaciones eliminadas`);
  } else {
    avisar(`Eliminadas ${borradas.length} de ${pendiente.ids.length}: ${fallos} no se pudieron borrar`, true);
  }
}

// ------------------------------------------------ modo de seleccion

function entrarEnSeleccion() {
  if (!ultimosDatos.trabajos.length) return avisar('No hay grabaciones que elegir');
  seleccion = new Set();
  clearTimeout(temporizador);   // la lista no se mueve mientras se elige
  $('#vista-lista').classList.add('seleccionando');
  pintarLista(ultimosDatos);
}

function salirDeSeleccion() {
  seleccion = null;
  $('#vista-lista').classList.remove('seleccionando');
  pintarLista(ultimosDatos);
  cargarLista(true);   // recarga de verdad y retoma el refresco automatico
}

function alternar(id) {
  if (seleccion.has(id)) seleccion.delete(id); else seleccion.add(id);
  sincronizarMarcas();
}

function sincronizarMarcas() {
  for (const caja of document.querySelectorAll('#lista .tarjeta')) {
    const elegida = seleccion.has(caja.dataset.id);
    caja.classList.toggle('elegida', elegida);
    caja.setAttribute('aria-pressed', String(elegida));
  }
  actualizarSeleccion();
}

function actualizarSeleccion() {
  const n = seleccion.size;
  $('#seleccion-cuenta').textContent = n
    ? `${n} seleccionada${n === 1 ? '' : 's'}` : 'Elige grabaciones';
  const borrar = $('#seleccion-borrar');
  borrar.disabled = n === 0;
  borrar.textContent = n ? `Eliminar ${n}` : 'Eliminar';
  const todas = n > 0 && n === ultimosDatos.trabajos.length;
  $('#seleccion-todas').textContent = todas ? 'Ninguna' : 'Todas';
}

$('#boton-seleccionar')?.addEventListener('click', entrarEnSeleccion);
$('#seleccion-cancelar')?.addEventListener('click', salirDeSeleccion);

$('#seleccion-todas')?.addEventListener('click', () => {
  const todas = seleccion.size === ultimosDatos.trabajos.length;
  seleccion = new Set(todas ? [] : ultimosDatos.trabajos.map((t) => t.id));
  sincronizarMarcas();
});

$('#seleccion-borrar')?.addEventListener('click', () => {
  const elegidas = ultimosDatos.trabajos.filter((t) => seleccion.has(t.id));
  if (elegidas.length) pedirBorradoDe(elegidas, false);
});

$('#boton-menu')?.addEventListener('click', abrirMenu);

$('#accion-renombrar')?.addEventListener('click', () => {
  $('#dialogo-acciones').close();
  pedirTitulo();
});

$('#accion-borrar')?.addEventListener('click', () => {
  $('#dialogo-acciones').close();
  pedirBorradoDe([trabajoAbierto], true);
});

$('#form-nombre')?.addEventListener('submit', (e) => {
  if (e.submitter?.value !== 'guardar') return;
  guardarTitulo($('#campo-nuevo-titulo').value.trim());
});

$('#form-borrar')?.addEventListener('submit', (e) => {
  if (e.submitter?.value !== 'borrar') return;
  confirmarBorrado();
});

/* Intro dentro de un campo de texto envia el formulario con su PRIMER boton, y
   en todos los dialogos el primero es Cancelar: escribir un nombre y darle a
   Intro lo tiraba todo. Se dirige a Guardar de forma explicita. */
function introGuarda(campo, formulario, boton) {
  campo?.addEventListener('keydown', (e) => {
    if (e.key !== 'Enter' || e.isComposing) return;
    e.preventDefault();
    formulario.requestSubmit(boton);
  });
}
introGuarda($('#campo-nuevo-titulo'), $('#form-nombre'), $('#nombre-aceptar'));
introGuarda($('#campo-nombre'), $('#form-hablante'), $('#voz-aceptar'));
introGuarda($('#campo-titulo'), $('#form-ajustes'), $('#ajustes-aceptar'));
introGuarda($('#campo-hablantes'), $('#form-ajustes'), $('#ajustes-aceptar'));

// ------------------------------------------------- renombrar hablantes

function primeraFraseDe(etiqueta) {
  const turno = (estadoDetalle?.datos.turnos || []).find((t) => t.hablante === etiqueta);
  if (!turno) return '';
  const frase = turno.texto.slice(0, 90);
  return `"${frase}${turno.texto.length > 90 ? '...' : ''}"`;
}

function pedirNombre(hablante) {
  const dialogo = $('#dialogo-hablante');
  $('#dialogo-titulo').textContent = `¿Quién es ${hablante.etiqueta}?`;
  $('#dialogo-pista').textContent = primeraFraseDe(hablante.etiqueta)
    || `${reloj(hablante.segundos)} hablando, ${hablante.intervenciones} intervenciones`;
  const campo = $('#campo-nombre');
  campo.value = hablante.nombre === hablante.etiqueta ? '' : hablante.nombre;
  dialogo.dataset.etiqueta = hablante.etiqueta;
  dialogo.showModal();
  campo.focus();
}

async function guardarNombre(etiqueta, nombre) {
  if (!estadoDetalle) return;
  const { job } = estadoDetalle;
  try {
    const respuesta = await api(`/jobs/${job.id}/hablantes`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ [etiqueta]: nombre }),
    });
    // El servidor devuelve la lista ya actualizada y rehace el texto.
    estadoDetalle.datos.hablantes = respuesta.hablantes;
    const fresco = await api(`/jobs/${job.id}/transcripcion`);
    estadoDetalle.datos = fresco;
    $('#detalle').dataset.texto = fresco.texto || '';
    pintarDetalle($('#detalle'), job, fresco);
    avisar(nombre ? `Ahora es ${nombre}` : 'Nombre quitado');
  } catch (e) {
    avisar('No se pudo guardar el nombre', true);
  }
}

$('#form-hablante')?.addEventListener('submit', (e) => {
  const dialogo = $('#dialogo-hablante');
  if (e.submitter?.value !== 'guardar') return;
  guardarNombre(dialogo.dataset.etiqueta, $('#campo-nombre').value.trim());
});

// ------------------------------------------------------------------ inicio

/* Los manejadores se enganchan con ?. a proposito: si un dia el HTML y el
   JavaScript van desacompasados (una cache a medias, un despliegue parcial),
   falta un elemento y antes eso tumbaba el script entero, dejando la app en
   blanco. Mejor que falte un boton a que no arranque nada. */
$('#form-token')?.addEventListener('submit', async (e) => {
  e.preventDefault();
  const valor = $('#campo-token').value.trim();
  if (!valor) return;
  token = valor;
  try {
    await api('/estado');
    localStorage.setItem(CLAVE_TOKEN, token);
    $('#error-token').classList.add('oculto');
    location.hash = '';
    enrutar();
  } catch {
    token = '';
    $('#error-token').textContent = 'Ese token no vale';
    $('#error-token').classList.remove('oculto');
  }
});

$('#campo-fichero')?.addEventListener('change', (e) => {
  const fichero = e.target.files[0];
  e.target.value = '';
  if (fichero) pedirAjustes(fichero);
});

$('#boton-recargar')?.addEventListener('click', () => cargarLista());
$('#boton-despertar')?.addEventListener('click', despertarPC);
$('#boton-volver')?.addEventListener('click', () => { location.hash = ''; });

$('#boton-copiar')?.addEventListener('click', async () => {
  const texto = $('#detalle').dataset.texto;
  if (!texto) return avisar('Nada que copiar');
  try {
    await navigator.clipboard.writeText(texto);
    avisar('Transcripción copiada');
  } catch {
    avisar('El navegador no deja copiar', true);
  }
});

/* Cuando compartes una grabacion desde la Grabadora, Android la entrega al
   service worker, que la guarda y redirige aqui con ?compartido=<clave>.
   La subimos ya con el token y la borramos de la cache. */
async function recogerCompartido() {
  const parametros = new URLSearchParams(location.search);
  const clave = parametros.get('compartido');
  if (!clave) return;

  parametros.delete('compartido');
  history.replaceState(null, '', location.pathname
    + (parametros.toString() ? `?${parametros}` : '') + location.hash);

  if (clave === 'vacio' || clave === 'error') {
    avisar('No se pudo leer la grabación compartida', true);
    return;
  }
  if (!token) {
    avisar('Entra con el token y vuelve a compartir', true);
    return;
  }

  try {
    const cache = await caches.open('reuniones-compartidos');
    const guardado = await cache.match(clave);
    if (!guardado) return avisar('La grabación compartida ya no está', true);

    const datos = await guardado.blob();
    const nombre = decodeURIComponent(guardado.headers.get('X-Nombre') || 'grabacion');
    const titulo = decodeURIComponent(guardado.headers.get('X-Titulo') || '');
    await cache.delete(clave);

    subir(new File([datos], conExtension(nombre, datos.type), { type: datos.type }),
          titulo || null);
  } catch (e) {
    avisar('Fallo al recoger la grabación compartida', true);
  }
}

/* La Grabadora comparte con nombres que a veces no traen extension, y la API
   la necesita para saber que es. Se deduce del tipo de contenido. */
function conExtension(nombre, tipo) {
  if (/\.[a-z0-9]{2,4}$/i.test(nombre)) return nombre;
  const porTipo = {
    'audio/mp4': '.m4a', 'audio/x-m4a': '.m4a', 'audio/aac': '.aac',
    'audio/mpeg': '.mp3', 'audio/ogg': '.ogg', 'audio/opus': '.opus',
    'audio/wav': '.wav', 'audio/x-wav': '.wav', 'audio/flac': '.flac',
    'audio/amr': '.amr', 'video/mp4': '.mp4',
  };
  return nombre + (porTipo[(tipo || '').split(';')[0]] || '.m4a');
}

window.addEventListener('hashchange', enrutar);
window.addEventListener('online', () => { enLinea(true); cargarLista(true); });
window.addEventListener('offline', () => enLinea(false));
document.addEventListener('visibilitychange', () => {
  if (!document.hidden && !location.hash) cargarLista(true);
});

if ('serviceWorker' in navigator) {
  navigator.serviceWorker.register('sw.js').then((registro) => {
    // Buscar version nueva en cada arranque, no solo cuando Chrome lo decida.
    registro.update().catch(() => {});

    // Si entra un service worker nuevo mientras la app esta abierta, se recarga
    // una vez para empezar a usarlo. El guardia evita el bucle infinito.
    let recargando = false;
    navigator.serviceWorker.addEventListener('controllerchange', () => {
      if (recargando) return;
      recargando = true;
      location.reload();
    });
  }).catch(() => {});
}

enrutar();
recogerCompartido();
