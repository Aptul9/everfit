// Pesata con la bilancia Bluetooth. Due strade, stessa schermata:
//   - dentro l'app per PC c'e' il ponte `window.pywebview.api` e la bilancia si collega da li';
//   - dal telefono (Safari non ha il Bluetooth) la richiesta passa dal server alla sentinella accesa sul PC di casa,
//     che fa la pesata e manda indietro gli avanzamenti (vedi server/ponte.py e desktop/sentinella.pyw).

import { io, S, aggiorna } from './store.js';
import { h, icona, dec, intero, daIso } from './dom.js';
import { foglio, avviso } from './ui.js';
import { M, salvaPesata, nuovaPesata, profiloCorpo, ultimaPesata } from './misure.js';

const sulPc = () => !!window.pywebview?.api?.misura;
const JSON_ = { 'Content-Type': 'application/json' };

// ---- la sentinella sul PC: e' accesa?
// errore = perche' l'ultimo controllo non ha avuto risposta (finisce nel registro del server, vedi riferisci)
export const sentinella = { online: null, quando: 0, errore: null };
const ascoltatori = new Set();
export function ascoltaSentinella(fn) { ascoltatori.add(fn); return () => ascoltatori.delete(fn); }

export async function controllaSentinella(forza = false) {
  if (sulPc() || !io.bilancia || (!forza && Date.now() - sentinella.quando < 15000)) return;
  sentinella.quando = Date.now();
  let online;
  try {
    // una domanda rimasta appesa (rete che va e viene) non deve tenere il pallino grigio: dopo 8 secondi si lascia
    // perdere, e al prossimo controllo si riprova
    const r = await fetch('api/bilancia/sentinella', { cache: 'no-store', signal: AbortSignal.timeout ? AbortSignal.timeout(8000) : undefined });
    // una risposta di errore (fuori dall'account, il server che sta ripartendo) non dice niente del PC: prima la si
    // leggeva come "PC spento" e il pallino diventava rosso anche con la sentinella accesa
    if (!r.ok) throw new Error(String(r.status));
    online = !!(await r.json()).online;
    sentinella.errore = null;
  } catch (e) {
    // Il server non si e' sentito (senza rete, o la rete non e' ancora tornata, come quando il telefono riapre l'app):
    // del PC non si sa niente, quindi resta quello che si sapeva e al prossimo controllo si riprova. Rosso solo quando
    // e' il server a dire che il PC non risponde.
    sentinella.errore = String(e?.name === 'Error' ? e.message : e?.name || e).slice(0, 40);
    sentinella.quando = 0;
    return;
  }
  if (online !== sentinella.online) { sentinella.online = online; for (const fn of ascoltatori) fn(); }
}

// Quando «Pesati ora» manca da un po' (pallino grigio o rosso), il telefono lo dice al registro del server, una volta
// per ogni motivo: cosi' si sa cosa vedeva il telefono, senza chiedere uno screenshot. Niente di personale.
const riferiti = new Set();
export function riferisci(motivo) {
  if (riferiti.has(motivo)) return;
  riferiti.add(motivo);
  const dati = { quando: `bilancia-${motivo}`, online: sentinella.online, errore: sentinella.errore, bilancia: !!io.bilancia,
    visibile: document.visibilityState, rete: navigator.onLine, dove: location.hash.slice(0, 30) };
  fetch('api/diagnosi', { method: 'POST', headers: JSON_, body: JSON.stringify(dati), keepalive: true }).catch(() => {});
}

// 'pc' = bilancia collegata a questo PC, 'sentinella' = passa dal PC di casa, null = adesso non si puo'
export const viaBilancia = () => (sulPc() ? 'pc' : sentinella.online ? 'sentinella' : null);

// Nella memoria della bilancia restano le pesate fatte senza app, anche quelle di chi vive con te: si tengono solo
// quelle vicine al tuo peso (kg di scarto ammessi).
const TOLLERANZA = 4;

// Quelle pesate non entrano da sole tra le tue: il capo le vuole aggiungere lui, se gli servono (14/10/2026). La
// bilancia pero' le cancella appena le ha passate al PC, quindi restano da parte nello stato (S.memoriaBilancia,
// arriva anche agli altri dispositivi) finche' non le aggiungi o le lasci perdere: dopo la pesata e in Progressi.
export const daParte = () => (Array.isArray(S.memoriaBilancia) ? S.memoriaBilancia : []);
export const quandoBreve = (q) => `${daIso(q.slice(0, 10)).toLocaleDateString('it-IT', { day: 'numeric', month: 'short' })}, ${q.slice(11, 16)}`;

function mettiDaParte(nuove) {
  const gia = new Set([...M.pesate.map((x) => x.quando), ...daParte().map((x) => x.quando)]);
  const davvero = nuove.filter((x) => !gia.has(x.quando));
  if (davvero.length) aggiorna((s) => { s.memoriaBilancia = [...daParte(), ...davvero].sort((a, b) => a.quando.localeCompare(b.quando)).slice(-20); });
  return davvero.length;
}

export async function aggiungiDaParte() {
  const lista = daParte();
  for (const m of lista) await salvaPesata(nuovaPesata({ peso: m.peso, impedenza: m.impedenza, quando: m.quando, fonte: 'memoria' }));
  aggiorna((s) => { s.memoriaBilancia = []; });
  avviso(lista.length === 1 ? 'Pesata aggiunta' : `${lista.length} pesate aggiunte`);
}
export function lasciaPerdereDaParte() { aggiorna((s) => { s.memoriaBilancia = []; }); }

// Le pesate messe da parte, in parole: "13 ott, 00:01 · 61,56 kg; 13 ott, 09:27 · 61,22 kg"
export const elencoDaParte = () => daParte().map((m) => `${quandoBreve(m.quando)} · ${dec(m.peso, 2)} kg`).join('; ');

const TESTI = {
  chiedo: ['Collego la bilancia', 'Un attimo.'],
  cerca: ['Sali sulla bilancia', 'Scalzo, un piede su ogni coppia di dischi di metallo.'],
  trovata: ['Bilancia trovata', 'Resta sopra, fermo: mi sto collegando. Può volerci una decina di secondi.'],
  collegata: ['Bilancia collegata', 'Resta fermo.'],
  peso: ['Sto pesando', 'Resta fermo.'],
  impedenza: ['Peso fermo', 'Non scendere: sto misurando il grasso.'],
};

function valore(nome, testo, sotto) {
  return h('div', { class: 'stat' }, h('b', null, testo), h('span', null, nome), sotto ? h('small', { class: 'piccolo', style: { display: 'block' } }, sotto) : null);
}

export function riepilogoPesata(p) {
  if (p.grasso == null) return null;
  const kg = (perc) => `${dec(p.peso * perc / 100)} kg`;
  return h('div', { class: 'tre-col' },
    valore('grasso', `${dec(p.grasso)}%`, kg(p.grasso)),
    valore('muscolo', `${dec(p.muscolo)}%`, kg(p.muscolo)),
    valore('acqua', `${dec(p.acqua)}%`, kg(p.acqua)),
    valore('viscerale', dec(p.viscerale)),
    valore('ossa', `${dec(p.ossa_kg)} kg`),
    valore('metabolismo', intero(p.bmr), 'kcal'));
}

// ---- le due strade: tutte e due danno { esito: Promise, annulla() } e chiamano alEvento({fase, kg})
function dalPc(profilo, alEvento) {
  window.fitBilancia = alEvento;   // l'app per PC manda qui lo stato mentre la misura va avanti
  return {
    esito: window.pywebview.api.misura(profilo).finally(() => { delete window.fitBilancia; }),
    annulla: () => { delete window.fitBilancia; window.pywebview.api.annulla?.(); },
  };
}

function dallaSentinella(profilo, alEvento) {
  let ident = null, vivo = true;
  const pausa = (ms) => new Promise((r) => setTimeout(r, ms));
  const esito = (async () => {
    alEvento({ fase: 'chiedo' });
    let r = await fetch('api/bilancia/richiesta', { method: 'POST', headers: JSON_, body: JSON.stringify({ profilo }) });
    let j = await r.json().catch(() => ({}));
    if (!r.ok) { sentinella.online = r.status === 503 ? false : sentinella.online; return { ok: false, errore: j.errore || 'La bilancia non risponde.' }; }
    ident = j.id;
    let visti = 0, inciampi = 0;
    while (vivo) {
      try {
        r = await fetch(`api/bilancia/stato?id=${ident}&dopo=${visti}&attesa=20`, { cache: 'no-store' });
        if (!r.ok) throw new Error(String(r.status));
        j = await r.json();
        inciampi = 0;
      } catch {
        // il telefono puo' perdere la rete per un momento: si riprova qualche volta prima di arrendersi
        if (++inciampi > 6) return { ok: false, errore: 'Ho perso il collegamento con il server a metà pesata. Se la bilancia ha finito, la pesata arriva alla prossima.' };
        await pausa(1500);
        continue;
      }
      for (const ev of j.eventi) alEvento(ev);
      visti = j.prossimo;
      if (j.esito) return j.esito;
    }
    return { ok: false, annullata: true };
  })().catch(() => ({ ok: false, errore: navigator.onLine === false ? 'Sei senza rete.' : 'Non riesco a parlare con il server. Riprova.' }));
  return {
    esito,
    annulla: () => {
      vivo = false;
      if (ident) fetch('api/bilancia/annulla', { method: 'POST', headers: JSON_, body: JSON.stringify({ id: ident }) }).catch(() => {});
    },
  };
}

export function apriBilancia() {
  const st = { fase: 'cerca', kg: null, esito: null, errore: null, daParte: 0, scartate: 0, vivo: true, corsa: null };
  const remoto = !sulPc();

  const alEvento = (ev) => {
    if (!st.vivo || st.fase === 'fatto' || st.fase === 'errore') return;
    if (ev.fase) st.fase = ev.fase;
    if (ev.fase === 'cerca' || ev.fase === 'chiedo') st.kg = null;
    if (ev.kg != null) st.kg = ev.kg;
    f.ridisegna();
  };

  const avvia = () => {
    Object.assign(st, { fase: remoto ? 'chiedo' : 'cerca', kg: null, esito: null, errore: null, daParte: 0, scartate: 0 });
    f.ridisegna();
    st.corsa = (remoto ? dallaSentinella : dalPc)(profiloCorpo(), alEvento);
    st.corsa.esito.then(async (r) => {
      if (!st.vivo) return;
      if (!r?.ok) { st.fase = 'errore'; st.errore = r?.errore || 'Misura non riuscita.'; f.ridisegna(); return; }
      const tuo = r.peso || ultimaPesata()?.peso;
      const nuove = [];
      for (const m of r.memoria || []) {
        if (tuo && Math.abs(m.peso - tuo) > TOLLERANZA) { st.scartate++; continue; }
        nuove.push({ quando: m.quando, peso: m.peso, impedenza: m.impedenza || null });
      }
      // da parte, non tra le pesate: le aggiunge chi vuole, con il tasto qui sotto o da Progressi
      if (nuove.length) mettiDaParte(nuove);
      st.daParte = daParte().length;
      if (r.peso) {
        st.esito = nuovaPesata({ peso: r.peso, impedenza: r.impedenza, fonte: 'bilancia' });
        const s = await salvaPesata(st.esito);
        st.inCoda = !!s.inCoda;
      }
      st.fase = 'fatto';
      f.ridisegna();
    }).catch((e) => { st.fase = 'errore'; st.errore = String(e?.message || e); f.ridisegna(); });
  };

  const f = foglio(() => {
    if (st.fase === 'errore') {
      return [
        h('h2', null, 'Non ci sono riuscito'),
        h('p', { class: 'muto' }, st.errore),
        h('button', { class: 'btn primo', onclick: avvia }, 'Riprova'),
      ];
    }
    if (st.fase === 'fatto') {
      const p = st.esito;
      return [
        h('div', { class: 'festa' },
          h('div', { class: 'coppa' }, icona('check')),
          h('div', { class: 'grande', style: { marginTop: '10px' } }, p ? dec(p.peso, 2) : '–', h('small', null, 'kg')),
          h('p', { class: 'muto' }, p ? (st.inCoda ? 'Salvata qui: arriva al server appena torna la rete.' : 'Pesata salvata.') : 'Nessuna pesata nuova.')),
        p ? riepilogoPesata(p) : null,
        p && p.grasso == null ? h('div', { class: 'nota' }, icona('info'), h('span', null, 'La bilancia non ha misurato l\'impedenza: piedi nudi e asciutti sui dischi di metallo, e resta fermo qualche secondo dopo che il peso si blocca.')) : null,
        st.daParte && daParte().length ? h('div', { class: 'nota', style: { flexDirection: 'column', gap: '10px' } },
          h('div', { style: { display: 'flex', gap: '10px' } }, icona('info'), h('span', null, daParte().length === 1
            ? `Nella memoria della bilancia c'era anche una pesata fatta senza app (${elencoDaParte()}). Non l'ho aggiunta.`
            : `Nella memoria della bilancia c'erano anche ${daParte().length} pesate fatte senza app (${elencoDaParte()}). Non le ho aggiunte.`)),
          h('button', { class: 'btn basso', onclick: async () => { await aggiungiDaParte(); f.ridisegna(); } }, icona('plus'), daParte().length === 1 ? 'Aggiungila' : 'Aggiungile')) : null,
        st.scartate ? h('div', { class: 'nota' }, icona('info'), h('span', null, st.scartate === 1 ? 'In memoria c\'era anche una pesata con un peso troppo lontano dal tuo: sarà di qualcun altro, non l\'ho presa.' : `In memoria c'erano anche ${st.scartate} pesate con un peso troppo lontano dal tuo: saranno di qualcun altro, non le ho prese.`)) : null,
        h('button', { class: 'btn', onclick: () => f.chiudi() }, 'Chiudi'),
      ];
    }
    const [titolo, sotto] = TESTI[st.fase] || TESTI.cerca;
    return [
      h('div', { class: 'festa' },
        h('div', { class: `bilancia-onda${st.fase === 'cerca' || st.fase === 'chiedo' ? '' : ' viva'}` }, icona('scale')),
        st.kg != null ? h('div', { class: 'grande', style: { marginTop: '12px' } }, dec(st.kg, 2), h('small', null, 'kg')) : null,
        h('h2', { style: { marginTop: '10px' } }, titolo),
        h('p', { class: 'muto' }, sotto)),
      h('button', { class: 'btn', onclick: () => f.chiudi() }, 'Annulla'),
    ];
  }, { alChiudere: () => { const inCorso = st.fase !== 'fatto' && st.fase !== 'errore'; st.vivo = false; if (inCorso) st.corsa?.annulla(); } });

  avvia();
}
