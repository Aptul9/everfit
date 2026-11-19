// Piccoli attrezzi per costruire il DOM senza framework.

const NS = 'http://www.w3.org/2000/svg';

function metti(el, figli) {
  for (const f of figli.flat(Infinity)) {
    if (f == null || f === false || f === true) continue;
    el.append(f.nodeType ? f : document.createTextNode(String(f)));
  }
}

function attributi(el, attrs) {
  for (const [k, v] of Object.entries(attrs)) {
    if (v == null || v === false) continue;
    if (k === 'class') el.setAttribute('class', v);
    else if (k === 'style' && typeof v === 'object') {
      for (const [p, val] of Object.entries(v)) {
        if (val == null) continue;
        if (p.startsWith('--')) el.style.setProperty(p, val);
        else el.style[p] = val;
      }
    } else if (k === 'html') el.innerHTML = v;
    else if (k === 'data') Object.assign(el.dataset, v);
    else if (k.startsWith('on') && typeof v === 'function') el.addEventListener(k.slice(2), v);
    else el.setAttribute(k, v === true ? '' : v);
  }
}

export function h(tag, attrs, ...figli) {
  const el = document.createElement(tag);
  if (attrs) attributi(el, attrs);
  if (tag !== 'button' && attrs?.role === 'button' && attrs.onclick) {
    if (!el.hasAttribute('tabindex')) el.tabIndex = 0;
    el.addEventListener('keydown', (e) => {
      if (e.target !== el || !['Enter', ' '].includes(e.key)) return;
      e.preventDefault();
      if (!e.repeat) el.click();
    });
  }
  metti(el, figli);
  return el;
}

export function s(tag, attrs, ...figli) {
  const el = document.createElementNS(NS, tag);
  if (attrs) attributi(el, attrs);
  metti(el, figli);
  return el;
}

const ICONE = {
  home: '<path d="M3.5 10.5 12 3.5l8.5 7V19.500a1.500 1.500 0 0 1-1.500 1.500H15v-6H9v6H5a1.500 1.500 0 0 1-1.500-1.500z"/>',
  fork: '<path d="M5 3v4a2.500 2.500 0 0 0 5 0V3M7.500 3v18"/><path d="M17.500 21V3c-2.200 1.200-3.500 3.800-3.500 7.500V13h3.500"/>',
  dumbbell: '<path d="M6.500 6.500v11M3.500 9.500v5M17.500 6.500v11M20.500 9.500v5M6.500 12h11"/>',
  chart: '<path d="M3.500 17l5.500-6 4 3.500 7.500-8.500"/><path d="M15.500 6h5v5"/>',
  grid: '<rect x="3.500" y="3.500" width="7" height="7" rx="2"/><rect x="13.500" y="3.500" width="7" height="7" rx="2"/><rect x="3.500" y="13.500" width="7" height="7" rx="2"/><rect x="13.500" y="13.500" width="7" height="7" rx="2"/>',
  check: '<path d="M5 12.500l4.500 4.500L19 7.500"/>',
  plus: '<path d="M12 5v14M5 12h14"/>',
  minus: '<path d="M5 12h14"/>',
  x: '<path d="M6 6l12 12M18 6L6 18"/>',
  chev: '<path d="M9 5l7 7-7 7"/>',
  back: '<path d="M15 5l-7 7 7 7"/>',
  clock: '<circle cx="12" cy="12" r="8.500"/><path d="M12 7.500V12l3 2"/>',
  flame: '<path d="M12 21a6.500 6.500 0 0 0 6.500-6.500c0-3.500-2.500-5.500-3.500-8.500-2 1-3 3-3 5-1-.500-2-1.600-2.200-3-1.500 1.800-4.300 4-4.300 6.500A6.500 6.500 0 0 0 12 21z"/>',
  drop: '<path d="M12 3.500c3 3.600 6 6.700 6 10.500a6 6 0 0 1-12 0c0-3.800 3-6.900 6-10.500z"/>',
  walk: '<circle cx="13" cy="4.500" r="1.800"/><path d="M9 21l2.500-6.500L9.500 12l1-4.500 3 .500 1.500 3.500L18 13M13.500 14.500l2 2.500 1 4M10.500 7.500l-3 1.500-1 3.500"/>',
  bolt: '<path d="M13 3 5 13.500h6L10 21l8.500-11h-6z"/>',
  swap: '<path d="M4 8h13l-3.500-3.500M20 16H7l3.500 3.500"/>',
  cart: '<path d="M3 4h2.500l2.200 10.500h10.300L20 7H7"/><circle cx="9" cy="19" r="1.500"/><circle cx="17" cy="19" r="1.500"/>',
  timer: '<circle cx="12" cy="13.500" r="7.500"/><path d="M12 9.500v4l2.500 1.500M9.500 3h5"/>',
  play: '<path d="M8 5.500v13l10.500-6.500z"/>',
  pause: '<path d="M8 5.500v13M16 5.500v13"/>',
  info: '<circle cx="12" cy="12" r="8.500"/><path d="M12 11v5.500M12 7.700v.300"/>',
  scale: '<rect x="3.500" y="3.500" width="17" height="17" rx="4"/><path d="M8 9.500a5.500 5.500 0 0 1 8 0L13.500 12h-3z"/>',
  cal: '<rect x="3.500" y="5" width="17" height="15.500" rx="3"/><path d="M3.500 10h17M8 3v4M16 3v4"/>',
  trophy: '<path d="M8 4h8v5a4 4 0 0 1-8 0zM8 6H4.500v1A3.500 3.500 0 0 0 8 10.500M16 6h3.500v1A3.500 3.500 0 0 1 16 10.500M12 13v4M8.500 20.500h7M10 17h4v3.500h-4z"/>',
  target: '<circle cx="12" cy="12" r="8.500"/><circle cx="12" cy="12" r="4.500"/><circle cx="12" cy="12" r=".800"/>',
  trend: '<path d="M3.500 17l5.500-6 4 3.500 7.500-8.500"/><path d="M15.500 6h5v5"/>',
  moon: '<path d="M20 14.500A8.500 8.500 0 0 1 9.500 4a8.500 8.500 0 1 0 10.500 10.500z"/>',
  star: '<path d="M12 3.500l2.600 5.400 5.900.800-4.300 4.100 1 5.900-5.200-2.800-5.200 2.800 1-5.900-4.300-4.100 5.900-.800z"/>',
  share: '<path d="M12 15V3.500M8 7l4-4 4 4M6.500 11H5a1.500 1.500 0 0 0-1.500 1.500v7A1.500 1.500 0 0 0 5 21h14a1.500 1.500 0 0 0 1.500-1.500v-7A1.500 1.500 0 0 0 19 11h-1.500"/>',
  down: '<path d="M12 4v11M7.500 11l4.500 4.500 4.500-4.500M5 20h14"/>',
  up: '<path d="M12 16V5M7.500 9 12 4.500 16.500 9M5 20h14"/>',
  trash: '<path d="M4.500 7h15M9.500 7V4.500h5V7M6.500 7l1 13h9l1-13M10 11v5.500M14 11v5.500"/>',
  cloud: '<path d="M7 18.500a4.500 4.500 0 0 1-.600-8.960 6 6 0 0 1 11.500 1.500 3.800 3.800 0 0 1-.400 7.460z"/>',
  pot: '<path d="M5 10h14v6.500a3 3 0 0 1-3 3H8a3 3 0 0 1-3-3zM3 10h18M9.500 6.500c0-1 1-1 1-2M13.500 6.500c0-1 1-1 1-2"/>',
  wind: '<path d="M3 9h10.500A2.500 2.500 0 1 0 11 6.500M3 13h15a2.500 2.500 0 1 1-2.500 2.500M3 17h7"/>',
  snow: '<path d="M12 3v18M4.200 7.500l15.600 9M19.800 7.500l-15.600 9"/>',
  pan: '<circle cx="10" cy="13" r="6.500"/><path d="M15 9l6-4"/>',
  more: '<circle cx="5" cy="12" r="1.300"/><circle cx="12" cy="12" r="1.300"/><circle cx="19" cy="12" r="1.300"/>',
  phone: '<rect x="6.500" y="2.500" width="11" height="19" rx="3"/><path d="M10.500 18.500h3"/>',
  list: '<path d="M8.500 6.500h11M8.500 12h11M8.500 17.500h11M4.500 6.500h.010M4.500 12h.010M4.500 17.500h.010"/>',
  user: '<circle cx="12" cy="8" r="4"/><path d="M4.500 20.500c1-4 4-5.500 7.500-5.500s6.500 1.500 7.500 5.500"/>',
  barcode: '<path d="M4 6v12M7 6v12M10.500 6v12M13 6v12M16.500 6v12M20 6v12"/>',
  camera: '<path d="M4.500 8h3L9 5.500h6L16.500 8h3A1.500 1.500 0 0 1 21 9.500v8a1.500 1.500 0 0 1-1.500 1.500h-15A1.500 1.500 0 0 1 3 17.500v-8A1.500 1.500 0 0 1 4.500 8z"/><circle cx="12" cy="13" r="3.500"/>',
  edit: '<path d="M4 20h4L19.500 8.500l-4-4L4 16zM13.500 6.500l4 4"/>',
  search: '<circle cx="11" cy="11" r="6.500"/><path d="M16 16l4.500 4.500"/>',
  scan: '<path d="M4 8.500V6.500A2.500 2.500 0 0 1 6.500 4h2M15.500 4h2A2.500 2.500 0 0 1 20 6.500v2M20 15.500v2a2.500 2.500 0 0 1-2.500 2.500h-2M8.500 20h-2A2.500 2.500 0 0 1 4 17.500v-2"/><path d="M8 9v6M10.800 9v6M13.200 9v6M16 9v6"/>',
  cup: '<path d="M5 9.500h11v4.500a5 5 0 0 1-5 5h-1a5 5 0 0 1-5-5z"/><path d="M16 11h1.500a2.500 2.500 0 0 1 0 5H15.600M8.500 3.500c0 1.300 1 1.300 1 2.600M12.500 3.500c0 1.300 1 1.300 1 2.600"/>',
  sparkle: '<path d="M11 4l1.900 5.100L18 11l-5.100 1.900L11 18l-1.900-5.100L4 11l5.100-1.900z"/><path d="M18.500 3.500v3M17 5h3M18.500 17v3.500M16.800 18.700h3.400"/>',
  send: '<path d="M12 19.500V5M5.500 11.500 12 5l6.500 6.500"/>',
  run: '<circle cx="14.500" cy="4.500" r="1.800"/><path d="M5 20.500l3.800-3.700 2-4.800M10.800 12l-1-4 4.200-1.200 2.300 3.700 3.200.500M10.800 12l4.200 3 .800 5.500M7 9.500l2.800-1.500"/>',
  bike: '<circle cx="6" cy="16.500" r="3.500"/><circle cx="18" cy="16.500" r="3.500"/><path d="M6 16.500l3.500-8H15l3 8M9.500 8.500l3.500 8M8 6h2.500M14.200 6H16"/>',
  wave: '<path d="M3 9c2-2 4-2 6 0s4 2 6 0 4-2 6 0M3 15c2-2 4-2 6 0s4 2 6 0 4-2 6 0"/>',
  video: '<rect x="3.500" y="5.500" width="17" height="13" rx="3.500"/><path d="M10.300 9.300v5.400l4.700-2.700z"/>',
  frames: '<rect x="3.500" y="6.500" width="11.500" height="11" rx="2.500"/><path d="M18 8.500v7M20.800 10v4"/>',
  copy: '<rect x="8.500" y="8.500" width="11" height="11" rx="2.500"/><path d="M15.500 8.500V6.500a2 2 0 0 0-2-2h-7a2 2 0 0 0-2 2v7a2 2 0 0 0 2 2h2"/>',
  exit: '<path d="M14.500 4.500h3a2 2 0 0 1 2 2v11a2 2 0 0 1-2 2h-3M10 8l-4 4 4 4M6 12h9.500"/>',
  users: '<circle cx="9" cy="8.500" r="3.200"/><path d="M3 19.500c.800-3.200 3-4.500 6-4.500s5.200 1.300 6 4.500M15.500 5.500a3.200 3.200 0 0 1 0 6.200M18 15.300c1.700.600 2.700 1.900 3.200 4.200"/>',
  key: '<circle cx="8" cy="15.500" r="4"/><path d="M11 12.500 19.500 4M16 7.500l2.500 2.500M18.500 5l2 2"/>',
  sun: '<circle cx="12" cy="12" r="4"/><path d="M12 3v2M12 19v2M3 12h2M19 12h2M5.600 5.600l1.400 1.400M17 17l1.400 1.400M18.400 5.600 17 7M7 17l-1.400 1.400"/>',
  body: '<circle cx="12" cy="4.800" r="2"/><path d="M5 9.500c4.500 1.200 9.500 1.200 14 0M12 10.300v5.200M12 15.500l-3.500 5.500M12 15.500l3.500 5.500"/>',
};

// E' #app che scorre, non la pagina: per tornare in cima si passa di qui.
export const inCima = (liscio = false) => document.getElementById('app')?.scrollTo({ top: 0, behavior: liscio ? 'smooth' : 'auto' });

// Un colpetto sotto il dito quando si spunta qualcosa. Su Android c'e' la vibrazione; sull'iPhone l'unica cosa che
// una pagina puo' far "sentire" e' l'interruttore di sistema (<input switch>, da iOS 17.4): ne tengo uno nascosto.
let leva = null;
export function colpetto() {
  try {
    if (navigator.vibrate) { navigator.vibrate(8); return; }
    if (!leva) {
      leva = document.createElement('label');
      leva.setAttribute('aria-hidden', 'true');
      leva.style.cssText = 'position:fixed;left:-99px;top:0;width:1px;height:1px;opacity:0;pointer-events:none;overflow:hidden';
      const interruttore = document.createElement('input');
      interruttore.type = 'checkbox';
      interruttore.setAttribute('switch', '');
      interruttore.tabIndex = -1;
      leva.append(interruttore);
      document.body.append(leva);
    }
    leva.click();
  } catch { /* nessun colpetto: non e' un problema */ }
}

export function icona(nome, extra) {
  const el = document.createElementNS(NS, 'svg');
  el.setAttribute('viewBox', '0 0 24 24');
  el.setAttribute('fill', 'none');
  el.setAttribute('stroke', 'currentColor');
  el.setAttribute('stroke-width', '1.9');
  el.setAttribute('stroke-linecap', 'round');
  el.setAttribute('stroke-linejoin', 'round');
  el.setAttribute('aria-hidden', 'true');
  if (extra) el.setAttribute('class', extra);
  el.innerHTML = ICONE[nome] || '';
  return el;
}

// ---- numeri e date in italiano
// in italiano le migliaia a quattro cifre non vengono separate da toLocaleString: lo facciamo a mano
export const intero = (x) => String(Math.round(x)).replace(/\B(?=(\d{3})+(?!\d))/g, '.');
export const dec = (x, n = 1) => Number(x).toLocaleString('it-IT', { minimumFractionDigits: 0, maximumFractionDigits: n });
export const numero = (t) => {
  if (t == null) return null;
  const v = parseFloat(String(t).replace(',', '.'));
  return Number.isFinite(v) ? v : null;
};

export const iso = (d) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
export const daIso = (t) => { const [y, m, g] = t.split('-').map(Number); return new Date(y, m - 1, g, 12); };
export const oggi = () => iso(new Date());
export const giornoSett = (d) => (d.getDay() + 6) % 7; // lunedi' = 0
export const piuGiorni = (t, n) => { const d = daIso(t); d.setDate(d.getDate() + n); return iso(d); };
export const lunedi = (t) => piuGiorni(t, -giornoSett(daIso(t)));
export const dataLunga = (t) => daIso(t).toLocaleDateString('it-IT', { weekday: 'long', day: 'numeric', month: 'long' });
export const maiuscola = (t) => t.charAt(0).toUpperCase() + t.slice(1);
export const dataCorta = (t) => daIso(t).toLocaleDateString('it-IT', { day: 'numeric', month: 'short' });
export const minSec = (sec) => { const x = Math.max(0, Math.round(sec)); return `${Math.floor(x / 60)}:${String(x % 60).padStart(2, '0')}`; };
export const durata = (ms) => {
  const m = Math.round(ms / 60000);
  return m < 60 ? `${m} min` : `${Math.floor(m / 60)} h ${String(m % 60).padStart(2, '0')}`;
};

// Foto con dissolvenza solo la prima volta che viene caricata: i ridisegni successivi non lampeggiano.
const giaViste = new Set();
export function foto(src, alt = '') {
  const nota = giaViste.has(src);
  const img = h('img', { src, alt, decoding: nota ? 'sync' : 'async', loading: nota ? 'eager' : 'lazy' });
  if (!nota) {
    img.style.opacity = '0';
    img.addEventListener('load', () => { giaViste.add(src); img.style.transition = 'opacity .5s'; img.style.opacity = '1'; }, { once: true });
  }
  return img;
}
