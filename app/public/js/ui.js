// Componenti riusabili: anello, barre, foglio a comparsa, mappa del corpo, grafico, coriandoli.

import { h, s, icona, foto, dec, intero } from './dom.js';
import { P, S, aggiorna } from './store.js';

// ---------- anello e barre (ricordano il valore precedente per animarsi tra un ridisegno e l'altro) ----------
const memoria = new Map();
let conta = 0;

// Fa partire una transizione su un elemento appena creato: prima fissa lo stile iniziale, poi applica quello finale.
// Niente requestAnimationFrame: quando la pagina non e' in primo piano non scatta.
function poi(el, fn) {
  setTimeout(() => { if (el.isConnected) void el.getBoundingClientRect(); fn(); }, 0);
}

export function anello({ id, val, max, lato = 132, spessore = 12, colori = ['var(--anello-a)', 'var(--anello-b)'], dentro }) {
  const r = (lato - spessore) / 2;
  const giro = 2 * Math.PI * r;
  const quota = Math.max(0, Math.min(1, max ? val / max : 0));
  const prima = memoria.has(id) ? memoria.get(id) : 0;
  memoria.set(id, quota);
  const gid = `g${++conta}`;
  const cerchio = s('circle', {
    class: 'val', cx: lato / 2, cy: lato / 2, r, 'stroke-width': spessore, stroke: `url(#${gid})`,
    'stroke-dasharray': giro, 'stroke-dashoffset': giro * (1 - prima),
  });
  poi(cerchio, () => cerchio.setAttribute('stroke-dashoffset', giro * (1 - quota)));
  return h('div', { class: 'anello', style: { width: `${lato}px`, height: `${lato}px` } },
    s('svg', { width: lato, height: lato, viewBox: `0 0 ${lato} ${lato}` },
      s('defs', null, s('linearGradient', { id: gid, x1: 0, y1: 0, x2: 1, y2: 1 },
        s('stop', { offset: '0', style: { stopColor: colori[0] } }), s('stop', { offset: '1', style: { stopColor: colori[1] } }))),
      s('circle', { class: 'traccia', cx: lato / 2, cy: lato / 2, r, 'stroke-width': spessore }),
      cerchio),
    dentro ? h('div', { class: 'dentro' }, dentro) : null);
}

export function barra({ id, val, max, colore, alta }) {
  const quota = Math.max(0, Math.min(1, max ? val / max : 0));
  const prima = memoria.has(id) ? memoria.get(id) : 0;
  memoria.set(id, quota);
  const i = h('i', { style: { background: colore, width: `${prima * 100}%` } });
  poi(i, () => { i.style.width = `${quota * 100}%`; });
  return h('div', { class: `barra${alta ? ' alta' : ''}` }, i);
}

export function macroRiga({ id, nome, val, max, colore }) {
  return h('div', { class: 'macro' },
    h('div', { class: 'fra' }, h('span', null, nome), h('b', null, `${intero(val)}`, h('span', null, ` / ${intero(max)} g`))),
    barra({ id, val, max, colore }));
}

export function spunta(on, extra = '') {
  return h('span', { class: `spunta ${on ? 'on' : ''} ${extra}` }, s('svg', { viewBox: '0 0 24 24' }, s('path', { d: 'M5 12.500l4.500 4.500L19 7.500' })));
}

// ---------- foglio a comparsa ----------
const pila = [];
let numeroFoglio = 0;

function isolaFogli() {
  const cima = pila[pila.length - 1];
  document.getElementById('guscio').inert = !!cima;
  for (const f of pila) f.el.inert = f !== cima;
}

document.addEventListener('keydown', (e) => {
  const f = pila[pila.length - 1];
  if (!f || e.defaultPrevented) return;
  if (e.key === 'Escape') { e.preventDefault(); f.chiudi(); }
  if (e.key !== 'Tab') return;
  const tasti = [...f.el.querySelectorAll('button, input, select, textarea, a[href], iframe, [tabindex]')]
    .filter((x) => x.tabIndex >= 0 && !x.matches(':disabled') && x.getClientRects().length && getComputedStyle(x).visibility === 'visible');
  const primo = tasti[0], ultimo = tasti[tasti.length - 1];
  if (!tasti.includes(document.activeElement) || (e.shiftKey ? document.activeElement === primo : document.activeElement === ultimo)) {
    e.preventDefault();
    ((e.shiftKey ? ultimo : primo) || f.el).focus();
  }
});

export function foglio(disegna, { copertina = false, alChiudere = null, classe = '' } = {}) {
  const origine = document.activeElement;
  const titoloId = `titolo-foglio-${++numeroFoglio}`;
  const velo = h('div', { class: 'velo' });
  const corpo = h('div', { class: `corpo${copertina ? ' senza' : ''}` });
  const el = h('div', { class: `foglio ${classe}`, role: 'dialog', 'aria-modal': 'true', tabindex: -1 },
    h('div', { class: 'maniglia' }, h('i')),
    h('button', { class: `tondo chiudi${copertina ? ' vetro' : ''}`, 'aria-label': 'Chiudi', onclick: () => api.chiudi() }, icona('x')),
    corpo);
  velo.style.zIndex = 50 + pila.length * 2;
  el.style.zIndex = 51 + pila.length * 2;
  let chiuso = false;

  const api = {
    el,
    ridisegna() {
      if (chiuso) return;
      // se chi usa l'app sta scrivendo in un campo del foglio, ridisegnarlo gli toglierebbe il fuoco
      const attivo = document.activeElement;
      if (attivo && corpo.contains(attivo) && /^(INPUT|SELECT|TEXTAREA)$/.test(attivo.tagName)) return;
      const y = corpo.scrollTop;
      corpo.replaceChildren(...[].concat(disegna(api)).flat(Infinity).filter((x) => x && x.nodeType));
      corpo.scrollTop = y;
      const titolo = corpo.querySelector('h2');
      if (titolo) {
        titolo.id ||= titoloId;
        el.setAttribute('aria-labelledby', titolo.id);
        el.removeAttribute('aria-label');
      } else {
        el.removeAttribute('aria-labelledby');
        el.setAttribute('aria-label', 'Finestra EverFit');
      }
      if (pila[pila.length - 1] === api && attivo && !attivo.isConnected) el.focus({ preventScroll: true });
    },
    chiudi() {
      if (chiuso) return;
      chiuso = true;
      const i = pila.indexOf(api);
      const inCima = i === pila.length - 1;
      if (i >= 0) pila.splice(i, 1);
      el.inert = true;
      velo.classList.remove('su');
      el.classList.remove('su');
      el.style.transform = '';
      setTimeout(() => { velo.remove(); el.remove(); }, 480);
      if (!pila.length) document.documentElement.classList.remove('lock');
      isolaFogli();
      if (inCima) {
        const destinazione = origine?.isConnected && origine.getClientRects().length && !origine.closest('[inert]')
          ? origine : pila[pila.length - 1]?.el || document.getElementById('app');
        destinazione.focus({ preventScroll: true });
      }
      el.setAttribute('aria-hidden', 'true');
      alChiudere?.();
    },
  };

  // trascina verso il basso per chiudere
  let y0 = null, dy = 0, inCima = false, attivo = false;
  el.addEventListener('touchstart', (e) => { y0 = e.touches[0].clientY; dy = 0; inCima = corpo.scrollTop <= 0; attivo = false; }, { passive: true });
  el.addEventListener('touchmove', (e) => {
    if (y0 == null || !inCima) return;
    dy = e.touches[0].clientY - y0;
    if (!attivo && dy > 8) { attivo = true; el.classList.add('trascina'); }
    if (attivo) { if (e.cancelable) e.preventDefault(); el.style.transform = `translateY(${Math.max(0, dy)}px)`; }
  }, { passive: false });
  el.addEventListener('touchend', () => {
    if (attivo) {
      el.classList.remove('trascina');
      if (dy > 120) api.chiudi(); else el.style.transform = '';
    }
    y0 = null; attivo = false;
  });
  velo.addEventListener('click', () => api.chiudi());

  document.body.append(velo, el);
  document.documentElement.classList.add('lock');
  pila.push(api);
  api.ridisegna();
  void el.getBoundingClientRect();
  velo.classList.add('su');
  el.classList.add('su');
  el.focus({ preventScroll: true });
  isolaFogli();
  return api;
}

export function ridisegnaFogli() { for (const f of [...pila]) f.ridisegna(); }
export function chiudiFogli() { for (const f of [...pila].reverse()) f.chiudi(); }

export function conferma({ titolo, testo, azioni }) {
  const f = foglio(() => [
    h('h2', null, titolo),
    testo ? h('p', { class: 'muto' }, testo) : null,
    h('div', { style: { display: 'flex', flexDirection: 'column', gap: '10px', marginTop: '6px' } },
      azioni.map((a) => h('button', { class: `btn ${a.tipo || ''}`, onclick: () => { f.chiudi(); a.fai?.(); } }, a.t))),
  ]);
  return f;
}

// ---------- avvisi ----------
let avvisoOra = null;
// Con `alTocco` l'avviso resta di piu' e si puo' toccare (per esempio: "FitAI ti ha risposto" apre la conversazione).
export function avviso(testo, ic = 'check', alTocco = null) {
  avvisoOra?.remove();
  const el = h('div', { class: `toast${alTocco ? ' tocco' : ''}`, role: 'status' }, icona(ic), testo);
  if (alTocco) el.addEventListener('click', () => { el.remove(); alTocco(); });
  avvisoOra = el;
  document.body.append(el);
  void el.getBoundingClientRect();
  el.classList.add('su');
  setTimeout(() => { el.classList.remove('su'); setTimeout(() => el.remove(), 400); }, alTocco ? 5200 : 2200);
}

// ---------- animazione dell'esercizio: partenza e arrivo che si alternano ----------
export function animazione(es) {
  const el = h('div', { class: 'anim' },
    foto(`img/ex/${es}-0.jpg`, ''),
    h('img', { class: 'b', src: `img/ex/${es}-1.jpg`, alt: P.esercizi[es]?.n || '', decoding: 'async', loading: 'lazy' }),
    h('div', { class: 'fasi' }, h('i'), h('i')));
  return el;
}

// La foto di sfondo di una scheda o di una seduta: quella del primo esercizio che ne ha una.
export function sfondoEsercizi(lista) {
  const es = lista.find((id) => P.esercizi[id]);
  return es ? foto(`img/ex/${es}-1.jpg`) : h('div', { class: 'sfondo-vuoto' }, icona('body'));
}

// L'esercizio in movimento: l'animazione con le due foto oppure, per chi lo preferisce, il video vero.
// La scelta resta (opzioni.video). Il video e' di YouTube e arriva dal loro sito: senza rete resta l'animazione.
export const haVideo = (es) => !!P.esercizi[es]?.video;
export const vuoleVideo = (es) => haVideo(es) && !!S.opzioni.video && navigator.onLine !== false;

export function filmato(es) {
  const e = P.esercizi[es];
  return h('div', { class: 'anim video' }, h('iframe', {
    src: `https://www.youtube-nocookie.com/embed/${e.video}?playsinline=1&rel=0&modestbranding=1`,
    title: `Video: ${e.n}`, loading: 'lazy', allowfullscreen: '',
    allow: 'accelerometer; encrypted-media; gyroscope; picture-in-picture; fullscreen',
    // la pagina di suo non dice a nessuno da dove arriva; YouTube pero' senza saperlo non fa partire il video
    referrerpolicy: 'strict-origin-when-cross-origin',
  }));
}

export const mostraEsercizio = (es) => (vuoleVideo(es) ? filmato(es) : animazione(es));

// Animazione o video: due lati, quello scelto resta acceso, e cambia subito.
// `dopo` ridisegna chi lo contiene (il foglio dell'esercizio, o la seduta).
export function levaVideo(es, dopo) {
  if (!haVideo(es)) return null;
  const acceso = vuoleVideo(es);
  const lato = (video, ic, nome) => h('button', { class: video === acceso ? 'on' : '', 'aria-pressed': video === acceso,
    onclick: () => { if (video === acceso) return; aggiorna((st) => { st.opzioni.video = video; }, true); dopo(); } }, icona(ic), nome);
  return h('div', { class: 'seg mini scelta-video', role: 'group', 'aria-label': 'Animazione o video' }, lato(false, 'frames', 'Animazione'), lato(true, 'video', 'Video'));
}

// ---------- mappa del corpo ----------
const DAVANTI = [
  ['spalle_lat', 'M30 37q-8 1-9.500 13 3.500 3 6.500 0 0-8 4-10z'],
  ['spalle_ant', 'M31.500 37.500q5-1.500 7 1.500-3.500 7-10.500 12-.500-8 3.500-13.500z'],
  ['petto_alto', 'M39.500 38.500 49.200 38v7.700q-8-.500-14.200 1.500 1.800-5 4.500-8.700z'],
  ['petto', 'M34.500 48.800q7-2.300 14.700-1.800V58.500q-8.200 3-14-2.300-1.200-3.700-.700-7.400z'],
  ['bicipiti', 'M22.500 53.500q5.500-.500 6.200 4.500L27 74q-4 3-6.800-1z'],
  ['avambracci', 'M19.800 79q3.800 2 6.800 0L21.500 102q-3.500 2-6-1z'],
  ['addome', 'M43.200 61.500h6v6.500h-6zM43.200 69.500h6V76h-6zM43.200 77.500h6V84h-6zM43.200 85.500h6V103q-4.200-2-5.400-8z'],
  ['obliqui', 'M34.500 60q3.500 3 7 2l.300 34q-4.800-2-7.300-8-2-14 0-28z'],
  ['quadricipiti', 'M33.500 108.500q7.500 4 15 4.500L45 150q-6 4-12.500-1-2-20.500 1-40.500z'],
  ['adduttori', 'M43.800 113.500l4.700 .500-1.100 30q-2.300-.600-3.800-3-1-14 .200-27.500z'],
  ['polpacci', 'M33 156q5-3 10.500 0L42 186q-4 3-7.500 0z'],
];
const DIETRO = [
  ['spalle_post', 'M31 37.500q-7-.500-10 10.500 4 5 9 1 3-5 6-8z'],
  ['dorsali', 'M33 46q8 6 12.500 18L47 84q-7 2-11-4-4-16-3-34z'],
  ['lombari', 'M44.500 86h4.700v18h-5.700q0-10 1-18z'],
  ['tricipiti', 'M22.500 52.500q5.500-.500 6.500 5.500L27.500 74q-4.500 3-7-1z'],
  ['avambracci', 'M19.800 79q3.800 2 6.800 0L21.500 102q-3.500 2-6-1z'],
  ['glutei', 'M35 105q7-4 14.200-.500V119q-8 4-15.200-2-1-6 1-12z'],
  ['femorali', 'M33 121.500q8 5 15.500 2L45 152q-6 3-12.500-2z'],
  ['polpacci', 'M32.500 156q5.500-4 11.500 0L42.500 184q-4.500 6-8.500 0z'],
];
const CENTRO_DIETRO = [['dorso_alto', 'M50 30.500l6.500 5 12.500 3q-9 5.500-15 23.500l-4 4-4-4q-6-18-15-23.500l12.500-3z']];
const SAGOMA = 'M50 3.500c5.500 0 9.500 5 9.500 11.500 0 4-1.500 7.300-4 9.300V31l14 4.500c6 1.500 9.500 6.500 10 14.500l1.500 26L86 102c1 5-1 13-3.500 13s-3.500-3-3.500-8l-5-26-2 24c2 15 0 30-1.500 45l-1.500 39c1 4 2 9-2 10h-6c-2-1-2-6-1.500-9l-4-39-5-32-5 32-4 39c.500 3 .500 8-1.500 9h-6c-4-1-3-6-2-10L32 150c-1.500-15-3.500-30-1.500-45l-2-24-5 26c0 5-1 8-3.500 8s-4.500-8-3.500-13l5-26L23 50c.500-8 4-13 10-14.500L47 31v-6.700c-2.500-2-4-5.300-4-9.300C43 8.500 44.500 3.500 50 3.500z';

function figura(lati, centro, uno, due, titolo) {
  const cls = (m) => `mm${uno.has(m) ? ' uno' : due.has(m) ? ' due' : ''}`;
  const meta = () => lati.map(([m, d]) => s('path', { class: cls(m), d }));
  return h('figure', null,
    s('svg', { viewBox: '8 0 84 204', role: 'img', 'aria-label': titolo },
      s('path', { class: 'base', d: SAGOMA }),
      s('g', null, meta()),
      s('g', { transform: 'translate(100 0) scale(-1 1)' }, meta()),
      centro.map(([m, d]) => s('path', { class: cls(m), d }))),
    h('figcaption', null, titolo));
}

export function mappaCorpo(primari = [], secondari = [], extra = '') {
  const uno = new Set(primari), due = new Set(secondari);
  return h('div', { class: `corpo-mappa ${extra}` },
    figura(DAVANTI, [], uno, due, 'Davanti'),
    figura(DIETRO, CENTRO_DIETRO, uno, due, 'Dietro'));
}

// ---------- grafico a linea ----------
export function grafico(punti, { meta = null, unita = '' } = {}) {
  const W = 320, H = 150, sx = 30, dx = 10, su = 12, giu = 22;
  let min = Math.min(...punti.map((p) => p.y)), max = Math.max(...punti.map((p) => p.y));
  if (meta != null) { min = Math.min(min, meta); max = Math.max(max, meta); }
  const margine = Math.max((max - min) * 0.18, 0.4);
  min -= margine; max += margine;
  const t0 = punti[0].x, t1 = punti[punti.length - 1].x;
  const X = (x) => (t1 === t0 ? (W - dx + sx) / 2 : sx + ((x - t0) / (t1 - t0)) * (W - sx - dx));
  const Y = (y) => su + (1 - (y - min) / (max - min)) * (H - su - giu);
  const pts = punti.map((p) => [X(p.x), Y(p.y)]);
  const linea = pts.map((p, i) => `${i ? 'L' : 'M'}${p[0].toFixed(1)} ${p[1].toFixed(1)}`).join(' ');
  const area = `${linea} L${pts[pts.length - 1][0].toFixed(1)} ${H - giu} L${pts[0][0].toFixed(1)} ${H - giu} Z`;
  const gid = `a${++conta}`;
  const tacche = [min + margine, (min + max) / 2, max - margine];
  const data = (ms) => new Date(ms).toLocaleDateString('it-IT', { day: 'numeric', month: 'short' });
  return s('svg', { class: 'grafico', viewBox: `0 0 ${W} ${H}` },
    s('defs', null, s('linearGradient', { id: gid, x1: 0, y1: 0, x2: 0, y2: 1 },
      s('stop', { offset: '0', style: { stopColor: 'var(--acc-tx)' }, 'stop-opacity': '.28' }), s('stop', { offset: '1', style: { stopColor: 'var(--acc-tx)' }, 'stop-opacity': '0' }))),
    tacche.map((v) => [s('line', { class: 'griglia', x1: sx, x2: W - dx, y1: Y(v), y2: Y(v) }), s('text', { x: sx - 6, y: Y(v) + 3.500, 'text-anchor': 'end' }, dec(v))]),
    meta != null ? [s('line', { class: 'meta', x1: sx, x2: W - dx, y1: Y(meta), y2: Y(meta) }), s('text', { x: W - dx, y: Y(meta) - 5, 'text-anchor': 'end', style: { fill: 'var(--acc-tx)' } }, `obiettivo ${dec(meta)} ${unita}`)] : null,
    pts.length > 1 ? s('path', { class: 'area', d: area, fill: `url(#${gid})` }) : null,
    pts.length > 1 ? s('path', { class: 'linea', d: linea, pathLength: 1 }) : null,
    pts.map((p, i) => (i === pts.length - 1 || pts.length <= 12 ? s('circle', { class: 'punto', cx: p[0], cy: p[1], r: i === pts.length - 1 ? 4.500 : 3 }) : null)),
    s('text', { x: sx, y: H - 5 }, data(t0)),
    t1 !== t0 ? s('text', { x: W - dx, y: H - 5, 'text-anchor': 'end' }, data(t1)) : null);
}

// ---------- coriandoli ----------
export function coriandoli() {
  if (matchMedia('(prefers-reduced-motion: reduce)').matches) return;
  const c = h('canvas', { class: 'coriandoli' });
  document.body.append(c);
  const dpr = Math.min(devicePixelRatio || 1, 2);
  const W = c.width = innerWidth * dpr, H = c.height = innerHeight * dpr;
  const ctx = c.getContext('2d');
  const colori = ['#c8ff4d', '#6dffa0', '#5cc8ff', '#ffc34d', '#ff7a93', '#ffffff'];
  const pezzi = Array.from({ length: 120 }, () => ({
    x: W / 2 + (Math.random() - 0.5) * W * 0.3, y: H * 0.42,
    vx: (Math.random() - 0.5) * 22 * dpr, vy: (-Math.random() * 20 - 6) * dpr,
    l: (5 + Math.random() * 7) * dpr, r: Math.random() * 6.280, vr: (Math.random() - 0.5) * 0.4,
    c: colori[Math.floor(Math.random() * colori.length)],
  }));
  const t0 = performance.now();
  (function passo(t) {
    const vita = (t - t0) / 2600;
    ctx.clearRect(0, 0, W, H);
    for (const p of pezzi) {
      p.vy += 0.55 * dpr; p.vx *= 0.985; p.x += p.vx; p.y += p.vy; p.r += p.vr;
      ctx.save(); ctx.translate(p.x, p.y); ctx.rotate(p.r);
      ctx.globalAlpha = Math.max(0, 1 - vita * vita);
      ctx.fillStyle = p.c; ctx.fillRect(-p.l / 2, -p.l / 4, p.l, p.l / 2);
      ctx.restore();
    }
    if (vita < 1) requestAnimationFrame(passo); else c.remove();
  })(t0);
}

// ---------- suono di fine recupero ----------
let audio = null;
export function sbloccaAudio() {
  try { audio = audio || new (window.AudioContext || window.webkitAudioContext)(); if (audio.state === 'suspended') audio.resume(); } catch { /* audio non disponibile */ }
}
export function bip() {
  if (!audio) return;
  try {
    [0, 0.22].forEach((quando, i) => {
      const o = audio.createOscillator(), g = audio.createGain();
      o.type = 'sine'; o.frequency.value = i ? 1175 : 880;
      g.gain.setValueAtTime(0.0001, audio.currentTime + quando);
      g.gain.exponentialRampToValueAtTime(0.35, audio.currentTime + quando + 0.02);
      g.gain.exponentialRampToValueAtTime(0.0001, audio.currentTime + quando + 0.2);
      o.connect(g).connect(audio.destination);
      o.start(audio.currentTime + quando); o.stop(audio.currentTime + quando + 0.22);
    });
  } catch { /* niente suono */ }
  navigator.vibrate?.([120, 80, 120]);
}

export const ICONA_COTTURA = { 'Cuociriso': 'pot', 'Friggitrice ad aria': 'wind', 'Senza cottura': 'snow', 'Padella': 'pan', 'Pentola': 'pot', 'Pentolino': 'pot', 'Fuori o a casa': 'star' };
