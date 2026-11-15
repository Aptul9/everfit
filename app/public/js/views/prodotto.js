// Scanner dei prodotti: si inquadra il codice a barre e l'app dice se quel prodotto va bene per la dieta,
// con tutti i valori dell'etichetta, punti di forza e punti deboli, consigli e, se c'e' una chiave di AI, un parere scritto.

import { h, s, icona, intero, dec, oggi } from '../dom.js';
import { P, S, io, aggiorna } from '../store.js';
import { foglio, avviso } from '../ui.js';
import { ultimaPesata } from '../misure.js';
import { avviaLettore, fotocameraDisponibile, codiceValido } from '../codice.js';
import { conLaFoto, ricordaScanner, tastoFoto, notaPermesso, TESTO_FOTO, TESTO_VIVO, PASSA_ALLA_FOTO, PASSA_AL_VIVO } from '../scatto.js';
import { valuta, tabella } from '../giudizio.js';
import { apriDiario } from './diario.js';

const mini = (url) => String(url).replace(/\.400\.jpg$/, '.200.jpg');
const NOVA = { 1: 'non lavorato', 2: 'ingrediente da cucina', 3: 'lavorato', 4: 'ultra-processato' };
const NUTRI = { a: '#2e8b57', b: '#8bc34a', c: '#f4c430', d: '#f08c2e', e: '#e0503a' };
const SEMAFORO = { basso: '#6dffa0', medio: '#ffc34d', alto: '#ff7a7a' };
let ai = null;   // questo account ha una chiave per i pareri scritti? Lo dice io.ai.

// A chi si rivolge il parere: lo stesso profilo che usa il resto dell'app.
function persona() {
  const p = P.profilo, o = P.obiettivi;
  return { obiettivi: o, lattosio: p.lattosio !== false };
}
export function personaInParole() {
  const p = P.profilo, o = P.obiettivi;
  const peso = ultimaPesata()?.peso || p.pesoIniziale;
  const meta = p.generato ? `Peso a cui vuole arrivare: ${dec(p.pesoObiettivo)} kg. ` : `Obiettivo: rimodellare il fisico e arrivare a ${dec(p.pesoObiettivo)} kg mettendo muscolo. `;
  return `${p.sesso === 'f' ? 'Donna' : 'Uomo'} di ${p.eta} anni, ${p.altezza} cm, ${dec(peso)} kg. ${meta}`
    + `Ogni giorno tra ${o.rest.kcal} e ${o.train.kcal} kcal, tra ${o.rest.p} e ${o.train.p} g di proteine, ${o.rest.f} g di grassi. ${p.note || ''}`;
}

async function prendi(ean) {
  let r;
  try { r = await fetch(`api/cibo/ean/${ean}`); } catch {
    const mio = S.prodotti?.[ean];
    if (mio) return { ...mio, per: 100 };
    throw new Error('Sei senza rete: riprova quando torna.');
  }
  if (r.status === 404) return null;
  const j = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(j.errore || 'Il catalogo dei prodotti non risponde.');
  return { ...j, per: 100 };
}

function ricordaScansione(a, g) {
  aggiorna((st) => {
    const resto = (st.scansioni || []).filter((v) => v.ean !== a.ean);
    st.scansioni = [{ ean: a.ean, n: a.n, marca: a.marca || null, img: a.img || null, voto: g?.voto ?? null, esito: g?.esito || null, quando: Date.now() }, ...resto].slice(0, 30);
  }, true);
}

function anelloVoto(g) {
  const r = 34, giro = 2 * Math.PI * r;
  return h('div', { class: 'voto' },
    s('svg', { viewBox: '0 0 84 84' },
      s('circle', { cx: 42, cy: 42, r, fill: 'none', style: { stroke: 'rgba(var(--ink), .1)' }, 'stroke-width': 8 }),
      s('circle', { cx: 42, cy: 42, r, fill: 'none', stroke: g.colore, 'stroke-width': 8, 'stroke-linecap': 'round', 'stroke-dasharray': giro, 'stroke-dashoffset': giro * (1 - g.voto / 100), transform: 'rotate(-90 42 42)' })),
    h('b', null, g.voto));
}

const elenco = (voci, classe, ic) => h('div', { class: `punti ${classe}` }, voci.map((t) => h('div', null, icona(ic), h('span', null, t))));

export function apriProdotto(a) {
  const g = valuta(a, persona());
  const x = a.x || {};
  ai = !!io.motore;   // serve un servizio con la chiave: l'AI che gira sulla VM fa solo l'assistente
  const st = { parere: null, stato: ai ? 'chiedi' : 'spenta', aperti: false };
  if (g) ricordaScansione(a, g);
  let f = null;

  async function chiediParere(rifai = false) {
    st.stato = 'attesa'; f.ridisegna();
    try {
      let r;
      try { r = await fetch('api/cibo/parere', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ ean: a.ean, persona: personaInParole(), rifai }) }); } catch { throw new Error('Sei senza rete.'); }
      const j = await r.json().catch(() => ({}));
      if (r.status === 503) { ai = false; st.stato = 'spenta'; f.ridisegna(); return; }
      if (!r.ok) throw new Error(j.errore || 'Il parere non è arrivato.');
      ai = true; st.parere = j; st.stato = 'fatto';
    } catch (e) { st.stato = 'errore'; st.errore = e.message; }
    f.ridisegna();
  }

  function parere() {
    if (st.stato === 'attesa') return h('div', { class: 'card', style: { textAlign: 'center' } }, h('div', { class: 'splash', style: { height: '70px' } }, h('i')), h('div', { class: 'piccolo' }, 'Leggo l\'etichetta e scrivo due righe…'));
    if (st.stato === 'fatto') {
      const p = st.parere;
      return h('div', { class: 'card parere' },
        h('p', null, p.riassunto),
        p.forti.length ? elenco(p.forti, 'forti', 'check') : null,
        p.deboli.length ? elenco(p.deboli, 'deboli', 'x') : null,
        p.consigli.length ? elenco(p.consigli, 'consigli', 'bolt') : null,
        h('div', { class: 'piccolo', style: { marginTop: '10px' } }, `Scritto da ${{ gemini: 'Gemini', mistral: 'Mistral' }[p.motore] || 'Claude'} leggendo i dati dell'etichetta. `,
          h('button', { class: 'collega', style: { display: 'inline', padding: 0 }, onclick: () => chiediParere(true) }, 'Riscrivi')));
    }
    if (st.stato === 'errore') return h('div', { class: 'nota' }, icona('info'), h('span', null, `${st.errore} `, h('button', { class: 'collega', style: { display: 'inline', padding: 0 }, onclick: () => chiediParere() }, 'Riprova')));
    if (st.stato === 'spenta') return h('div', { class: 'nota' }, icona('info'), h('span', null, 'Per avere anche due righe scritte su misura serve una chiave di AI: la metti in Piano → Intelligenza artificiale. Il giudizio qui sopra c\'è comunque.'));
    return h('button', { class: 'btn', onclick: () => chiediParere() }, icona('bolt'), 'Chiedi un parere all\'AI');
  }

  f = foglio(() => {
    if (!g) {
      return [
        h('div', { class: 'riga', style: { alignItems: 'flex-start' } }, foto(a.img, 'prodotto-foto'), h('div', { class: 'cresce' }, h('h2', null, a.n), h('p', { class: 'muto' }, a.marca || ''))),
        h('div', { class: 'nota' }, icona('info'), h('span', null, 'Nel catalogo questo prodotto non ha i valori nutrizionali, quindi non posso giudicarlo. Puoi scriverli tu dal diario: «Ho mangiato altro» → Codice a barre.')),
        h('button', { class: 'btn', onclick: () => f.chiudi() }, 'Chiudi'),
      ];
    }
    const righe = tabella(a);
    const k = a.pz ? a.pz / 100 : null;
    return [
      h('div', { class: 'riga', style: { alignItems: 'flex-start' } },
        foto(a.img, 'prodotto-foto'),
        h('div', { class: 'cresce' }, h('h2', { style: { fontSize: '22px' } }, a.n),
          h('p', { class: 'muto', style: { marginTop: '4px' } }, [a.marca, a.conf ? `${intero(a.conf)} g` : null].filter(Boolean).join(' · ')))),
      h('div', { class: `card giudizio ${g.esito}` },
        anelloVoto(g),
        h('div', { class: 'cresce' }, h('b', null, g.titolo),
          h('div', { class: 'piccolo' }, g.parziale ? 'Giudizio parziale: l\'etichetta nel catalogo è incompleta.' : (P.profilo.generato ? 'Rispetto ai tuoi obiettivi di calorie e proteine.' : 'Rispetto ai tuoi obiettivi: più muscolo, pochi zuccheri, niente lattosio.')))),
      h('div', { class: 'chips' },
        x.nutri ? h('span', { class: 'chip', style: { background: NUTRI[x.nutri], color: '#fff' } }, `Nutri-Score ${x.nutri.toUpperCase()}`) : null,
        x.nova ? h('span', { class: 'chip' }, `NOVA ${x.nova} · ${NOVA[x.nova]}`) : null,
        x.senza_lattosio ? h('span', { class: 'chip acc' }, 'Senza lattosio') : null,
        (x.additivi || []).length ? h('span', { class: 'chip' }, `${x.additivi.length} additivi`) : null),
      g.forti.length ? [h('h4', null, 'Punti di forza'), elenco(g.forti, 'forti', 'check')] : null,
      g.deboli.length ? [h('h4', null, 'Punti deboli'), elenco(g.deboli, 'deboli', 'x')] : null,
      g.consigli.length ? [h('h4', null, 'Consigli'), elenco(g.consigli, 'consigli', 'bolt')] : null,
      h('h4', null, 'Il parere'),
      parere(),
      h('h4', null, 'Valori nutrizionali'),
      h('div', { class: 'card', style: { paddingTop: '10px', paddingBottom: '8px' } },
        h('table', { class: 'tabella valori' },
          h('thead', null, h('tr', null, h('th', null, ''), h('th', null, x.bevanda ? 'per 100 ml' : 'per 100 g'), k ? h('th', null, `per ${a.pzn?.[0] || 'porzione'}`) : null)),
          h('tbody', null, righe.map(([nome, v, u, liv, dentro]) => h('tr', { class: dentro ? 'dentro' : '' },
            h('td', null, liv ? h('i', { class: 'semaforo', style: { background: SEMAFORO[liv] }, title: liv }) : h('i', { class: 'semaforo vuoto' }), nome),
            h('td', null, `${u === 'kcal' ? intero(v) : dec(v)} ${u}`),
            k ? h('td', null, `${u === 'kcal' ? intero(v * k) : dec(v * k)} ${u}`) : null)))),
        h('div', { class: 'piccolo', style: { marginTop: '8px' } }, 'Pallino verde: poco. Giallo: nella media. Rosso: tanto.')),
      x.ingredienti || (x.allergeni || []).length ? h('h4', null, 'Ingredienti e allergeni') : null,
      (x.allergeni || []).length || (x.tracce || []).length ? h('div', { class: 'chips' },
        (x.allergeni || []).map((t) => h('span', { class: 'chip', style: { background: 'rgba(255,122,122,.14)', color: 'var(--bad)' } }, t)),
        (x.tracce || []).map((t) => h('span', { class: 'chip' }, `tracce: ${t}`))) : null,
      x.ingredienti ? h('p', { class: 'piccolo', style: { lineHeight: 1.5 } }, x.ingredienti) : null,
      h('p', { class: 'piccolo' }, 'Dati da Open Food Facts, inseriti da volontari: se qualcosa non torna, vale l\'etichetta.'),
      h('button', { class: 'btn primo', onclick: () => { f.chiudi(); apriDiario(oggi(), null, a); } }, icona('plus'), 'Aggiungi al diario'),
    ];
  });
  return f;
}

function foto(url, classe) {
  if (!url) return null;
  const img = h('img', { src: url, alt: '', loading: 'lazy', decoding: 'async', referrerpolicy: 'no-referrer' });
  const scatola = h('div', { class: classe }, img);
  img.addEventListener('error', () => scatola.remove(), { once: true });
  return scatola;
}

export function apriScanner() {
  let spegni = null, vivo = true, f = null;
  let foto_ = conLaFoto();   // dal vivo, a meno che la persona non abbia scelto di scattare una foto (scatto.js)
  let senzaVideo = false;
  const video = h('video', { playsinline: true, muted: true, autoplay: true });
  const lettore = h('div', { class: 'lettore' }, video, h('div', { class: 'mira' }));
  const stato = h('p', { class: 'piccolo', style: { textAlign: 'center' } }, foto_ ? TESTO_FOTO : TESTO_VIVO);
  const cifre = h('input', { type: 'text', inputmode: 'numeric', autocomplete: 'off', maxlength: 14, placeholder: '8001234567890', 'aria-label': 'Codice a barre' });
  const scatto = tastoFoto(stato, (c) => trova(c));

  const accendi = () => {
    if (foto_) return;
    if (!fotocameraDisponibile()) { senzaVideo = true; lettore.remove(); stato.textContent = 'Scrivi i numeri che trovi sotto le barre.'; return; }
    avviaLettore(video, trova).then((ferma) => { if (vivo && !foto_) spegni = ferma; else ferma(); }).catch(() => {
      senzaVideo = true;
      lettore.remove();
      stato.textContent = 'La fotocamera non parte (serve il permesso). Fotografa il codice, oppure scrivi i numeri che trovi sotto le barre.';
      f?.ridisegna();
    });
  };
  const cambiaModo = (conFoto) => {
    foto_ = conFoto;
    ricordaScanner(conFoto ? 'foto' : 'vivo');
    spegni?.(); spegni = null;
    senzaVideo = false;
    stato.textContent = conFoto ? TESTO_FOTO : TESTO_VIVO;
    f.ridisegna();
    if (conFoto) scatto.apri(); else accendi();
  };

  async function trova(codice) {
    const ean = String(codice).replace(/\D/g, '');
    if (!codiceValido(ean)) { avviso('Il codice non torna: ricontrolla le cifre', 'info'); return; }
    cifre.blur();
    stato.textContent = `Cerco ${ean}…`;
    try {
      const a = await prendi(ean.length === 12 ? `0${ean}` : ean);
      if (!vivo) return;
      if (!a) { stato.textContent = `Il codice ${ean} non è nel catalogo. Prova con un altro prodotto.`; cifre.value = ''; if (!foto_ && (!spegni || !video.srcObject)) accendi(); return; }
      f.chiudi();
      apriProdotto(a);
    } catch (e) {
      if (!vivo) return;
      stato.textContent = e.message;
      cifre.value = ean;
    }
  }
  cifre.addEventListener('keydown', (e) => { if (e.key === 'Enter') { e.preventDefault(); trova(cifre.value); } });

  f = foglio(() => {
    const recenti = S.scansioni || [];
    return [
      h('div', null, h('h2', null, 'Scansiona un prodotto'), h('p', { class: 'muto', style: { marginTop: '4px' } }, 'Ti dico se va bene per la tua dieta, con valori, punti di forza e punti deboli.')),
      foto_ || senzaVideo ? [scatto.campo, scatto.tasto] : lettore, stato,
      foto_ ? null : notaPermesso(),
      // se la fotocamera non e' partita (permesso negato) sotto c'e' gia' il tasto della foto: qui si puo' riprovare dal vivo
      h('button', { class: 'testo-link', style: { marginTop: 0 }, onclick: () => cambiaModo(senzaVideo ? false : !foto_) },
        foto_ ? PASSA_AL_VIVO : senzaVideo ? 'Riprova con la fotocamera' : PASSA_ALLA_FOTO),
      h('div', { class: 'riga' },
        h('div', { class: 'campo cresce' }, cifre),
        h('button', { class: 'btn', style: { width: 'auto', padding: '0 18px', flex: 'none', marginTop: 0, height: '56px' }, onclick: () => trova(cifre.value) }, icona('search'))),
      recenti.length ? h('h4', null, 'Già scansionati') : null,
      recenti.length ? h('div', { class: 'card elenco' }, recenti.slice(0, 12).map((v) => h('button', { class: 'voce', onclick: () => trova(v.ean) },
        foto(v.img && mini(v.img), 'prodotto-mini'),
        h('div', { class: 'cresce' }, h('b', null, v.n), h('small', null, v.marca || '')),
        v.voto != null ? h('span', { class: `votino ${v.esito}` }, v.voto) : null))) : null,
    ];
  }, { alChiudere: () => { vivo = false; spegni?.(); } });
  // chi ha toccato il tasto dello scanner vuole scansionare: la fotocamera parte subito (chi ha scelto la foto, quella di sistema)
  if (foto_) scatto.apri(); else accendi();
  return f;
}
