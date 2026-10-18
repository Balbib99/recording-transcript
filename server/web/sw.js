/* Service worker: la app abre sin red, conserva lo ultimo leido y recibe las
   grabaciones que se comparten desde la Grabadora del movil. */

const VERSION = 'reuniones-v2';
const COMPARTIDOS = 'reuniones-compartidos';

const ESQUELETO = [
  './',
  './index.html',
  './estilos.css',
  './app.js',
  './manifest.webmanifest',
  './iconos/icono-192.png',
  './iconos/icono-512.png',
];

self.addEventListener('install', (evento) => {
  evento.waitUntil(
    caches.open(VERSION).then((cache) => cache.addAll(ESQUELETO))
      .then(() => self.skipWaiting())
  );
});

self.addEventListener('activate', (evento) => {
  evento.waitUntil(
    caches.keys()
      .then((claves) => Promise.all(
        claves.filter((c) => c !== VERSION && c !== COMPARTIDOS)
              .map((c) => caches.delete(c))))
      .then(() => self.clients.claim())
  );
});

/* Android entrega el audio compartido como un POST a /compartir. Aqui no hay
   token (lo manda el sistema, no la app), asi que el fichero se guarda en una
   cache y se redirige a la aplicacion, que lo sube ya autenticada. */
async function recibirCompartido(peticion) {
  try {
    const datos = await peticion.formData();
    const fichero = datos.get('file');
    const titulo = (datos.get('titulo') || datos.get('texto') || '').toString();

    if (!fichero || typeof fichero === 'string') {
      return Response.redirect('./?compartido=vacio', 303);
    }

    const clave = `/compartido-${Date.now()}`;
    const cache = await caches.open(COMPARTIDOS);
    await cache.put(clave, new Response(fichero, {
      headers: {
        'Content-Type': fichero.type || 'application/octet-stream',
        'X-Nombre': encodeURIComponent(fichero.name || 'grabacion'),
        'X-Titulo': encodeURIComponent(titulo),
      },
    }));

    return Response.redirect(`./?compartido=${encodeURIComponent(clave)}`, 303);
  } catch (e) {
    return Response.redirect('./?compartido=error', 303);
  }
}

self.addEventListener('fetch', (evento) => {
  const peticion = evento.request;
  const url = new URL(peticion.url);

  if (peticion.method === 'POST' && url.pathname.endsWith('/compartir')) {
    evento.respondWith(recibirCompartido(peticion));
    return;
  }

  if (peticion.method !== 'GET') return;          // las subidas no se cachean
  if (url.origin !== location.origin) return;

  if (url.pathname.includes('/api/')) {
    // Red primero: los datos de la cola tienen que estar al dia.
    evento.respondWith(
      fetch(peticion)
        .then((respuesta) => {
          const copia = respuesta.clone();
          caches.open(VERSION).then((cache) => cache.put(peticion, copia));
          return respuesta;
        })
        .catch(() => caches.match(peticion))
    );
    return;
  }

  // El esqueleto de la app: cache primero, que no cambia entre despliegues.
  evento.respondWith(
    caches.match(peticion).then((guardado) => guardado || fetch(peticion))
  );
});
