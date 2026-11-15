// Pesate e circonferenze. Stanno nel database del server: qui c'e' una copia per vederle senza rete
// e una coda per quelle inserite quando la rete manca.

import { composizione } from './corpo.js';
import { P } from './store.js';
import { oggi } from './dom.js';

const CHIAVE = 'fit.misure.v1';
// passi: [{giorno, passi, aggiornato}], quelli che manda il comando dell'iPhone dall'app Salute (vedi altro.js)
export const M = { pesate: [], circonferenze: [], passi: [], coda: [] };
const ascoltatori = new Set();

export function ascoltaMisure(fn) { ascoltatori.add(fn); return () => ascoltatori.delete(fn); }
function avvisa() { for (const fn of ascoltatori) fn(); }
function scrivi() {
  try { localStorage.setItem(CHIAVE, JSON.stringify(M)); } catch { /* memoria piena o navigazione privata */ }
}

export function caricaMisure() {
  try { Object.assign(M, JSON.parse(localStorage.getItem(CHIAVE) || '{}')); } catch { /* copia illeggibile: si riscarica */ }
  for (const k of ['pesate', 'circonferenze', 'passi', 'coda']) if (!Array.isArray(M[k])) M[k] = [];
}

const ordina = () => {
  M.pesate.sort((a, b) => a.quando.localeCompare(b.quando));
  M.circonferenze.sort((a, b) => a.giorno.localeCompare(b.giorno));
};

async function manda(tipo, dati) {
  const r = await fetch(`api/${tipo}`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(dati) });
  if (!r.ok) throw Object.assign(new Error((await r.json().catch(() => ({}))).errore || String(r.status)), { rifiutato: r.status < 500 });
  return r.json();
}

// Riprova a mandare quello che era rimasto in coda. Quello che il server rifiuta viene scartato.
async function svuotaCoda() {
  while (M.coda.length) {
    const { tipo, dati } = M.coda[0];
    try { await manda(tipo, dati); } catch (e) { if (!e.rifiutato) return false; }
    M.coda.shift();
    scrivi();
  }
  return true;
}

export async function aggiornaMisure() {
  try {
    if (!(await svuotaCoda())) return;
    const r = await fetch('api/misure', { cache: 'no-store' });
    if (!r.ok) return;
    const dati = await r.json();
    M.pesate = dati.pesate || [];
    M.circonferenze = dati.circonferenze || [];
    M.passi = dati.passi || [];
    scrivi();
    avvisa();
  } catch { /* senza rete resta la copia locale */ }
}

async function salva(tipo, chiave, riga) {
  const elenco = M[tipo];
  const i = elenco.findIndex((x) => x[chiave] === riga[chiave]);
  if (i >= 0) elenco[i] = { ...elenco[i], ...riga }; else elenco.push(riga);
  ordina(); scrivi(); avvisa();
  try {
    const salvata = await manda(tipo, riga);
    const j = elenco.findIndex((x) => x[chiave] === riga[chiave]);
    if (j >= 0) elenco[j] = salvata;
    scrivi(); avvisa();
    return { ok: true };
  } catch (e) {
    if (e.rifiutato) {
      M[tipo] = M[tipo].filter((x) => x[chiave] !== riga[chiave]);
      scrivi(); avvisa();
      return { ok: false, errore: e.message };
    }
    M.coda.push({ tipo, dati: riga });
    scrivi();
    return { ok: true, inCoda: true };
  }
}

export const salvaPesata = (riga) => salva('pesate', 'quando', riga);
export const salvaCirconferenze = (riga) => salva('circonferenze', 'giorno', riga);

export async function eliminaMisura(tipo, riga) {
  const chiave = tipo === 'pesate' ? 'quando' : 'giorno';
  M[tipo] = M[tipo].filter((x) => x[chiave] !== riga[chiave]);
  M.coda = M.coda.filter((x) => !(x.tipo === tipo && x.dati[chiave] === riga[chiave]));
  scrivi(); avvisa();
  if (!riga.id) return true;
  try { return (await fetch(`api/${tipo}/${riga.id}`, { method: 'DELETE' })).ok; } catch { return false; }
}

// Eta' di oggi: dalla data di nascita se c'e', altrimenti quella scritta nel piano.
export function profiloCorpo() {
  const p = P.profilo;
  let eta = p.eta;
  if (p.nascita) {
    const [a, m, g] = p.nascita.split('-').map(Number);
    const o = new Date();
    eta = o.getFullYear() - a - (o.getMonth() + 1 < m || (o.getMonth() + 1 === m && o.getDate() < g) ? 1 : 0);
  }
  return { altezza: p.altezza, eta, sesso: p.sesso || 'm' };
}

const adesso = () => {
  const d = new Date();
  const due = (n) => String(n).padStart(2, '0');
  return `${oggi()}T${due(d.getHours())}:${due(d.getMinutes())}:${due(d.getSeconds())}`;
};

// Costruisce la riga da salvare: con l'impedenza calcola tutta la composizione, senza resta solo il peso.
export function nuovaPesata({ peso, impedenza = null, quando = adesso(), fonte = 'manuale', nota = null }) {
  const pr = profiloCorpo();
  const c = composizione({ peso, impedenza, ...pr });
  const riga = { quando, giorno: quando.slice(0, 10), fonte, peso, impedenza: impedenza || null, ...pr, imc: c.imc, nota };
  if (!c.soloPeso) {
    Object.assign(riga, {
      grasso: c.grasso, muscolo: c.muscolo, scheletrico: c.scheletrico, acqua: c.acqua, proteine: c.proteine,
      ossa_kg: c.ossaKg, sottocutaneo: c.sottocutaneo, viscerale: c.viscerale, bmr: c.bmr, eta_corporea: c.etaCorporea,
      algoritmo: c.algoritmo,
    });
  }
  return riga;
}

export const ultimaPesata = () => M.pesate[M.pesate.length - 1] || null;
export const conComposizione = () => M.pesate.filter((x) => x.grasso != null);

// I passi di un giorno (dall'app Salute dell'iPhone), oppure null se quel giorno non sono arrivati.
export const passiDel = (d) => M.passi.find((x) => x.giorno === d)?.passi ?? null;
