/* Service worker: la app abre sin red y conserva lo ultimo leido.
   Las peticiones a la API van siempre a la red primero; si falla, se responde
   con lo cacheado para poder releer transcripciones sin cobertura. */

const VERSION = 'reuniones-v1';
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
        claves.filter((c) => c !== VERSION).map((c) => caches.delete(c))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener('fetch', (evento) => {
  const peticion = evento.request;
  if (peticion.method !== 'GET') return;          // las subidas no se cachean

  const url = new URL(peticion.url);
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
