// Fit: l'app si apre dalla copia tenuta sul dispositivo, subito e anche senza rete. Quando sul server ce n'e' una
// nuova la scarica in sottofondo e la mette al posto della vecchia (main.js decide quando ricaricare la pagina).
//
// VERSIONE e FILE li scrive il server mentre consegna questo file (server.py, guscio): cambia un file dell'app,
// cambia questo, e il browser capisce da solo che c'e' da aggiornare. Non serve tenere un elenco a mano.
const VERSIONE = '__VERSIONE__';
const ELENCO = '__FILE__';
const FILE = Array.isArray(ELENCO) ? ELENCO : ['./'];
const CACHE = `fit-${VERSIONE}`;
const FOTO = 'fit-foto';   // le foto di piatti ed esercizi restano da una versione all'altra
// Mai dalla copia: i dati, la pagina del codice, il manifest (diverso per ogni account) e questo stesso file.
const DI_RETE = ['api/', 'accedi', 'manifest.webmanifest', 'sw.js'];

self.addEventListener('install', (e) => {
  e.waitUntil((async () => {
    const cache = await caches.open(CACHE);
    // "reload": dal server, non dalla memoria del browser. Se anche un solo file manca la copia nuova non parte
    // e resta la vecchia: cosi' non si finisce mai con un'app a meta'.
    await cache.addAll(FILE.map((u) => new Request(u, { cache: 'reload' })));
    // Niente skipWaiting qui: la copia nuova resta in attesa finche' la pagina non dice "attiva" (vedi main.js).
    // Se prendesse il posto della vecchia mentre l'app si sta caricando, la pagina partirebbe meta' vecchia e meta' nuova.
  })());
});

self.addEventListener('activate', (e) => {
  e.waitUntil((async () => {
    for (const nome of await caches.keys()) if (nome !== CACHE && nome !== FOTO) await caches.delete(nome);
    await self.clients.claim();
  })());
});

async function dallaCopia(req, chiave) {
  const cache = await caches.open(CACHE);
  const salvata = await cache.match(chiave || req, { ignoreSearch: true });
  if (salvata) return salvata;
  const r = await fetch(req);
  if (r.ok && r.type === 'basic' && !chiave) cache.put(req, r.clone());
  return r;
}

async function foto(req) {
  const cache = await caches.open(FOTO);
  const salvata = await cache.match(req);
  if (salvata) return salvata;
  const r = await fetch(req);
  if (r.ok) cache.put(req, r.clone());
  return r;
}

self.addEventListener('fetch', (e) => {
  const req = e.request;
  if (req.method !== 'GET') return;
  const url = new URL(req.url);
  if (url.origin !== self.location.origin) return;
  const base = new URL(self.registration.scope).pathname;
  if (!url.pathname.startsWith(base)) return;
  const rel = url.pathname.slice(base.length);
  if (DI_RETE.some((p) => rel === p || (p.endsWith('/') && rel.startsWith(p)))) return;
  if (rel.startsWith('img/')) { e.respondWith(foto(req)); return; }
  if (req.mode === 'navigate') {
    // l'app e' una pagina sola: qualunque altro indirizzo (la pagina del codice, per esempio) va chiesto al server
    if (rel === '' || rel === 'index.html') e.respondWith(dallaCopia(req, './'));
    return;
  }
  e.respondWith(dallaCopia(req));
});

// L'app manda l'elenco delle foto: le mette da parte per usarle senza rete, in palestra.
self.addEventListener('message', (e) => {
  if (e.data?.tipo === 'attiva') { e.waitUntil(self.skipWaiting()); return; }
  if (e.data?.tipo !== 'immagini') return;
  e.waitUntil((async () => {
    const cache = await caches.open(FOTO);
    const lista = e.data.lista || [];
    for (let i = 0; i < lista.length; i += 6) {
      await Promise.all(lista.slice(i, i + 6).map(async (u) => {
        try {
          if (await cache.match(u)) return;
          const r = await fetch(u);
          if (r.ok) await cache.put(u, r);
        } catch { /* si riprova al prossimo avvio */ }
      }));
    }
  })());
});

// ---------- notifiche ----------
// Il server sveglia il telefono senza dire niente (cosi' non c'e' da cifrare nulla): il testo lo si va a prendere
// adesso, con il cookie di chi usa l'app. Una notifica va mostrata comunque, altrimenti il sistema toglie il permesso.
self.addEventListener('push', (e) => {
  e.waitUntil((async () => {
    let voci = [];
    try {
      const r = await fetch('api/notifiche/prossime', { credentials: 'same-origin', cache: 'no-store' });
      if (r.ok) voci = (await r.json()).notifiche || [];
    } catch { /* senza rete: resta quella generica */ }
    if (!voci.length) voci = [{ etichetta: 'fit', titolo: 'EverFit', testo: 'C\'è una novità: apri l\'app.', dove: './' }];
    for (const v of voci) {
      await self.registration.showNotification(v.titolo, { body: v.testo, tag: v.etichetta, icon: 'icons/icon-192.png', badge: 'icons/icon-192.png', data: { dove: v.dove || './' } });
    }
  })());
});

// Il tocco sulla notifica: se l'app e' gia' aperta la si porta davanti (e le si dice dove andare), altrimenti si apre.
self.addEventListener('notificationclick', (e) => {
  e.notification.close();
  const dove = e.notification.data?.dove || './';
  e.waitUntil((async () => {
    const finestre = await self.clients.matchAll({ type: 'window', includeUncontrolled: true });
    for (const c of finestre) {
      if ('focus' in c) { c.postMessage({ tipo: 'notifica', dove }); return c.focus(); }
    }
    return self.clients.openWindow(dove);
  })());
});
