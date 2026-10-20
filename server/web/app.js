/* Reuniones - logica de la PWA.
   Sin dependencias: fetch, un poco de DOM y enrutado por hash. */

const $ = (sel) => document.querySelector(sel);

const CLAVE_TOKEN = 'rc_token';
const CLAVE_CACHE = 'rc_ultima_lista';

let token = localStorage.getItem(CLAVE_TOKEN) || '';
let temporizador = null;
let estadoDetalle = null;   // { job, datos } de la reunion abierta

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

const duracion = (s) => {
  if (!s) return '';
  const m = Math.round(s / 60);
  return m >= 60 ? `${Math.floor(m / 60)} h ${m % 60} min` : `${m} min`;
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

function enLinea(si) {
  $('#indicador').classList.toggle('sin-red', !si);
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

function pintarLista(datos) {
  const { trabajos, resumen } = datos;
  pintarEstadoPC(datos.worker);
  const contenedor = $('#lista');
  contenedor.innerHTML = '';

  if (resumen) {
    const pendientes = resumen.pendiente + resumen.procesando;
    $('#resumen').textContent = pendientes
      ? `${pendientes} en cola · ${resumen.hecho} listas`
      : `${resumen.hecho} transcripcion${resumen.hecho === 1 ? '' : 'es'}`;
  }

  $('#lista-vacia').classList.toggle('oculto', trabajos.length > 0);

  for (const t of trabajos) {
    const tarjeta = document.createElement('button');
    tarjeta.className = 'tarjeta';
    tarjeta.onclick = () => { location.hash = `/j/${t.id}`; };

    const partes = [fecha(t.creado)];
    if (t.duracion) partes.push(duracion(t.duracion));
    if (t.hablantes) partes.push(`${t.hablantes} ${t.hablantes === 1 ? 'voz' : 'voces'}`);
    if (t.estado === 'fallido' && t.error) partes.push(t.error.slice(0, 60));

    tarjeta.innerHTML = `
      <h2>
        <span class="titulo"></span>
        <span class="estado ${t.estado}">${t.estado}</span>
      </h2>
      <div class="meta"></div>`;
    tarjeta.querySelector('.titulo').textContent = t.titulo || t.fichero;
    for (const p of partes) {
      const span = document.createElement('span');
      span.textContent = p;
      tarjeta.querySelector('.meta').append(span);
    }
    contenedor.append(tarjeta);
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
      if (!silencioso) avisar('Sin conexion: mostrando lo ultimo guardado');
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
  if (hayMovimiento && !document.hidden) {
    temporizador = setTimeout(() => cargarLista(true), 8000);
  }
}

// ------------------------------------------------------- estado del PC

function hace(segundos) {
  if (segundos == null) return 'nunca visto';
  if (segundos < 90) return 'hace un momento';
  const m = Math.round(segundos / 60);
  if (m < 60) return `hace ${m} min`;
  const h = Math.round(m / 60);
  return h < 48 ? `hace ${h} h` : `hace ${Math.round(h / 24)} dias`;
}

function pintarEstadoPC(worker) {
  const barra = $('#barra-pc');
  if (!worker) { barra.classList.add('oculto'); return; }
  barra.classList.remove('oculto');

  const punto = $('#punto-pc');
  punto.className = `punto-pc ${worker.vivo ? 'vivo' : 'dormido'}`;
  $('#texto-pc').textContent = worker.vivo
    ? `PC en marcha${worker.nombre ? ` (${worker.nombre})` : ''}`
    : `PC no disponible · ${hace(worker.segundos)}`;

  // El boton solo aparece si hace falta y si la Pi sabe a quien despertar.
  $('#boton-despertar').classList.toggle(
    'oculto', worker.vivo || !worker.puede_despertarse);
}

async function despertarPC() {
  const boton = $('#boton-despertar');
  boton.disabled = true;
  boton.textContent = 'Enviando...';
  try {
    const r = await api('/despertar', { method: 'POST' });
    if (r.enviado) {
      avisar('Paquete enviado. El PC deberia encenderse en un minuto');
      esperarAlPC();
    } else {
      avisar(r.motivo || 'No hizo falta');
      cargarLista(true);
    }
  } catch (e) {
    avisar('No se pudo enviar la senal', true);
  } finally {
    boton.disabled = false;
    boton.textContent = 'Despertar';
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
        avisar('El PC ya esta en marcha');
        cargarLista(true);
        return;
      }
    } catch (e) { /* sin red: se reintenta */ }
    esperarAlPC(intentos - 1);
  }, 5000);
}

// ----------------------------------------------------------------- subida

function subir(fichero, titulo = null) {
  if (!fichero) return;

  const datos = new FormData();
  datos.append('file', fichero);
  datos.append('titulo', titulo || fichero.name.replace(/\.[^.]+$/, ''));

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
      avisar(job.duplicado ? 'Esa grabacion ya estaba subida' : 'Subida. Esperando al worker');
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
  const caja = $('#detalle');
  caja.innerHTML = '<p class="apagado">Cargando...</p>';

  let job;
  try {
    job = await api(`/jobs/${id}`);
  } catch {
    caja.innerHTML = '<p class="error">No se pudo cargar</p>';
    return;
  }

  $('#detalle-titulo').textContent = job.titulo || job.fichero;

  if (job.estado !== 'hecho') {
    const mensajes = {
      pendiente: 'En cola. Se transcribira cuando el worker este encendido.',
      procesando: 'Transcribiendo ahora mismo...',
      fallido: `Fallo: ${job.error || 'motivo desconocido'}`,
    };
    caja.innerHTML = `<p class="${job.estado === 'fallido' ? 'error' : 'apagado'}"></p>`;
    caja.querySelector('p').textContent = mensajes[job.estado] || job.estado;
    return;
  }

  let datos;
  try {
    datos = await api(`/jobs/${id}/transcripcion`);
  } catch {
    caja.innerHTML = '<p class="error">No se pudo cargar la transcripcion</p>';
    return;
  }
  caja.dataset.texto = datos.texto || '';
  estadoDetalle = { job, datos };
  pintarDetalle(caja, job, datos);
}

function pintarDetalle(caja, job, datos) {
  caja.innerHTML = '';

  const ficha = document.createElement('dl');
  ficha.className = 'ficha';
  const filas = [
    ['Grabado', fecha(job.creado)],
    ['Duracion', duracion(datos.duracion) || reloj(datos.duracion)],
    ['Idioma', datos.idioma || '-'],
    ['Modelo', datos.modelo || '-'],
  ];
  for (const [clave, valor] of filas) {
    const dt = document.createElement('dt'); dt.textContent = clave;
    const dd = document.createElement('dd'); dd.textContent = valor;
    ficha.append(dt, dd);
  }
  caja.append(ficha);

  // Asignar un color estable a cada hablante segun su orden
  const colorDe = new Map();
  (datos.hablantes || []).forEach((h, i) => colorDe.set(h.etiqueta, `hablante-${i % 6}`));

  if (datos.hablantes?.length) {
    const fila = document.createElement('div');
    fila.className = 'hablantes';
    for (const h of datos.hablantes) {
      const chip = document.createElement('button');
      const sinNombrar = h.nombre === h.etiqueta;
      chip.className = `chip editable${sinNombrar ? ' sin-nombrar' : ''}`;
      chip.title = 'Tocar para poner el nombre';
      const nombre = document.createElement('b');
      nombre.className = colorDe.get(h.etiqueta);
      nombre.textContent = h.nombre;
      chip.append(nombre, ` ${reloj(h.segundos)} · ${h.intervenciones}`);
      chip.onclick = () => pedirNombre(h);
      fila.append(chip);
    }
    caja.append(fila);
  }

  for (const t of datos.turnos || []) {
    const bloque = document.createElement('article');
    bloque.className = 'turno';
    const cabecera = document.createElement('div');
    cabecera.className = 'turno-cabecera';
    const quien = document.createElement('span');
    quien.className = `turno-hablante ${colorDe.get(t.hablante) || ''}`;
    quien.textContent = (datos.hablantes || []).find((h) => h.etiqueta === t.hablante)?.nombre
                        || t.hablante;
    const cuando = document.createElement('span');
    cuando.className = 'turno-tiempo';
    cuando.textContent = reloj(t.inicio);
    cabecera.append(quien, cuando);
    const parrafo = document.createElement('p');
    parrafo.textContent = t.texto;
    bloque.append(cabecera, parrafo);
    caja.append(bloque);
  }
}

// ------------------------------------------------- renombrar hablantes

function primeraFraseDe(etiqueta) {
  const turno = (estadoDetalle?.datos.turnos || []).find((t) => t.hablante === etiqueta);
  if (!turno) return '';
  const frase = turno.texto.slice(0, 90);
  return `"${frase}${turno.texto.length > 90 ? '...' : ''}"`;
}

function pedirNombre(hablante) {
  const dialogo = $('#dialogo-hablante');
  $('#dialogo-titulo').textContent = `Quien es ${hablante.etiqueta}?`;
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

$('#form-hablante').addEventListener('submit', (e) => {
  const dialogo = $('#dialogo-hablante');
  if (e.submitter?.value !== 'guardar') return;
  guardarNombre(dialogo.dataset.etiqueta, $('#campo-nombre').value.trim());
});

// ------------------------------------------------------------------ inicio

$('#form-token').addEventListener('submit', async (e) => {
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

$('#campo-fichero').addEventListener('change', (e) => {
  subir(e.target.files[0]);
  e.target.value = '';
});

$('#boton-recargar').addEventListener('click', () => cargarLista());
$('#boton-despertar').addEventListener('click', despertarPC);
$('#boton-volver').addEventListener('click', () => { location.hash = ''; });

$('#boton-copiar').addEventListener('click', async () => {
  const texto = $('#detalle').dataset.texto;
  if (!texto) return avisar('Nada que copiar');
  try {
    await navigator.clipboard.writeText(texto);
    avisar('Transcripcion copiada');
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
    avisar('No se pudo leer la grabacion compartida', true);
    return;
  }
  if (!token) {
    avisar('Entra con el token y vuelve a compartir', true);
    return;
  }

  try {
    const cache = await caches.open('reuniones-compartidos');
    const guardado = await cache.match(clave);
    if (!guardado) return avisar('La grabacion compartida ya no esta', true);

    const datos = await guardado.blob();
    const nombre = decodeURIComponent(guardado.headers.get('X-Nombre') || 'grabacion');
    const titulo = decodeURIComponent(guardado.headers.get('X-Titulo') || '');
    await cache.delete(clave);

    subir(new File([datos], conExtension(nombre, datos.type), { type: datos.type }),
          titulo || null);
  } catch (e) {
    avisar('Fallo al recoger la grabacion compartida', true);
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
