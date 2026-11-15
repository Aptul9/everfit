// Movimento libero: camminate, corse, bici, esercizi a casa. Per chi non va in palestra e' il cuore della sezione;
// per chi ci va e' il resto della settimana.

import { h, icona, oggi, intero, numero, lunedi, piuGiorni, daIso, dataCorta, colpetto } from '../dom.js';
import {
  P, ATTIVITA, OBIETTIVO_MINUTI, aggiungiAttivita, togliAttivita, minutiAttivi, minutiSettimana, kcalAttivita, kcalStimate, kcalTue,
  impostaKcalAttivita, bruciateDel, impostaBruciate, siAllena,
} from '../store.js';
import { ultimaPesata, passiDel } from '../misure.js';
import { anello, foglio, avviso, conferma } from '../ui.js';

const INIZIALI = ['L', 'M', 'M', 'G', 'V', 'S', 'D'];
const chili = () => ultimaPesata()?.peso || P.profilo.pesoIniziale || 70;
export const kcalDi = (a) => kcalAttivita(a, chili());
const stimaDi = (a) => kcalStimate(a, chili());
export const minutiInParole = (m) => (m < 60 ? `${m} min` : `${Math.floor(m / 60)} h ${String(m % 60).padStart(2, '0')}`);
// la palestra tra le attivita' solo per chi ci va: per gli altri sarebbe un tasto senza senso
const tipiDaProporre = () => Object.keys(ATTIVITA).filter((id) => !ATTIVITA[id].palestra || siAllena());

// Le calorie scritte a mano: "1.200" sono milleduecento, non 1,2 (alle kcal i decimali non servono).
const kcalScritte = (t) => {
  const s = String(t ?? '').replace(/\s/g, '');
  if (!s) return null;
  const v = Number(s.replace(/[.,](?=\d{3}(?!\d))/g, '').replace(',', '.'));
  return Number.isFinite(v) ? Math.round(v) : null;
};
const kcalBuone = (k, max) => k != null && k >= 0 && k <= max;
const campoKcal = (st) => h('input', { type: 'text', inputmode: 'numeric', autocomplete: 'off', placeholder: 'per esempio dall\'orologio',
  'aria-label': 'Calorie bruciate', value: st.kcal, oninput: (e) => { st.kcal = e.target.value; } });
// I due lati della scelta: la stima dell'app (o la somma delle attivita') e le calorie che sai tu.
const sceltaKcal = (st, api, campo, nomeStima) => h('div', { class: 'seg', role: 'group', 'aria-label': 'Quali calorie' },
  h('button', { class: st.mie ? '' : 'on', 'aria-pressed': String(!st.mie), onclick: () => { if (st.mie) { st.mie = false; api.ridisegna(); } } }, nomeStima),
  h('button', { class: st.mie ? 'on' : '', 'aria-pressed': String(st.mie), onclick: () => { if (!st.mie) { st.mie = true; api.ridisegna(); campo.focus(); } } }, 'Le mie'));

// Il foglio per segnare un'attivita': che cosa, per quanto, eventualmente quanti chilometri, oggi o ieri, e le calorie:
// la stima dell'app oppure le tue.
export function apriAttivita(tipoIniziale = 'camminata', giorno = oggi()) {
  const tipi = tipiDaProporre();
  const tipo = tipi.includes(tipoIniziale) ? tipoIniziale : 'camminata';
  const st = { tipo, min: ATTIVITA[tipo].palestra ? 60 : 30, km: '', d: giorno, mie: false, kcal: '' };
  const campoKm = h('input', { type: 'text', inputmode: 'decimal', autocomplete: 'off', placeholder: 'facoltativo', 'aria-label': 'Chilometri',
    oninput: (e) => { st.km = e.target.value; } });
  const campo = campoKcal(st);
  const f = foglio((api) => {
    const t = ATTIVITA[st.tipo];
    const cambia = (m) => { colpetto(); st.min = Math.max(5, Math.min(600, m)); api.ridisegna(); };
    return [
      h('h2', null, 'Segna il movimento'),
      h('div', { class: 'scorri' }, tipi.map((id) =>
        h('button', { class: `scelta${st.tipo === id ? ' on' : ''}`, onclick: () => { st.tipo = id; api.ridisegna(); } }, ATTIVITA[id].n))),
      h('div', { class: 'quanti' },
        h('button', { class: 'tondo', 'aria-label': 'Meno minuti', onclick: () => cambia(st.min - 5) }, icona('minus')),
        h('div', null, h('b', null, st.min), h('span', null, 'minuti')),
        h('button', { class: 'tondo', 'aria-label': 'Più minuti', onclick: () => cambia(st.min + 5) }, icona('plus'))),
      h('div', { class: 'scorri', style: { justifyContent: 'center' } }, t.minuti.map((m) =>
        h('button', { class: `scelta${st.min === m ? ' on' : ''}`, onclick: () => cambia(m) }, minutiInParole(m)))),
      t.km ? h('div', { class: 'campo' }, h('label', null, 'Chilometri'), campoKm) : null,
      h('div', { class: 'seg' },
        h('button', { class: st.d === oggi() ? 'on' : '', onclick: () => { st.d = oggi(); api.ridisegna(); } }, 'Oggi'),
        h('button', { class: st.d !== oggi() ? 'on' : '', onclick: () => { st.d = piuGiorni(oggi(), -1); api.ridisegna(); } }, 'Ieri')),
      h('h4', { style: { margin: '4px 0 -2px' } }, 'Calorie bruciate'),
      sceltaKcal(st, api, campo, 'Stima dell\'app'),
      st.mie ? h('div', { class: 'campo' }, h('label', null, 'Le tue calorie'), campo)
        : h('p', { class: 'piccolo', style: { textAlign: 'center' } }, `Circa ${intero(stimaDi({ tipo: st.tipo, min: st.min }))} kcal, dai minuti e dal tuo peso.`),
      h('button', { class: 'btn primo', onclick: () => {
        const km = t.km ? numero(st.km) : null;
        const kcal = st.mie ? kcalScritte(st.kcal) : null;
        if (st.mie && !kcalBuone(kcal, 10000)) { avviso('Scrivi le calorie bruciate, da 0 a 10.000', 'info'); return; }
        aggiungiAttivita({ tipo: st.tipo, min: st.min, km: km > 0 && km < 400 ? km : null, d: st.d, kcal });
        colpetto();
        f.chiudi();
        avviso(`${t.n}: ${minutiInParole(st.min)}${kcal != null ? ` · ${intero(kcal)} kcal` : ''}`, t.icona);
      } }, icona('check'), 'Aggiungi'),
    ];
  });
  return f;
}

// Le calorie di una cosa gia' segnata (un'attivita', o il totale di un giorno): la stima o un numero tuo.
// `salva(null)` torna alla stima.
function apriCalorie({ titolo, testo = null, nomeStima, fraseStima, tue, salva, max = 10000 }) {
  const st = { mie: tue != null, kcal: tue != null ? String(tue) : '' };
  const campo = campoKcal(st);
  const f = foglio((api) => [
    h('h2', null, titolo),
    testo ? h('p', { class: 'muto' }, testo) : null,
    sceltaKcal(st, api, campo, nomeStima),
    st.mie ? h('div', { class: 'campo' }, h('label', null, 'Le tue calorie'), campo) : h('p', { class: 'piccolo', style: { textAlign: 'center' } }, fraseStima),
    h('button', { class: 'btn primo', onclick: () => {
      const k = st.mie ? kcalScritte(st.kcal) : null;
      if (st.mie && !kcalBuone(k, max)) { avviso(`Scrivi le calorie bruciate, da 0 a ${intero(max)}`, 'info'); return; }
      salva(k);
      colpetto();
      f.chiudi();
      avviso(k != null ? `${intero(k)} kcal: le tue` : `Torna ${nomeStima.toLowerCase()}`, 'flame');
    } }, icona('check'), 'Salva'),
  ]);
  return f;
}

// Le calorie bruciate oggi: la somma delle attivita' (le tue dove le hai scritte, la stima per le altre) oppure un
// totale tuo, per chi ha l'orologio e non vuole dividerle attivita' per attivita'.
export function cartaBruciate(d = oggi()) {
  const b = bruciateDel(d, chili());
  const quante = b.n === 1 ? 'un\'attività' : `${b.n} attività`;
  const sotto = b.tuo ? 'Il totale che hai scritto tu'
    : !b.n ? 'Segna un\'attività, o scrivi il tuo totale'
      : !b.stimate ? `Somma di ${quante}, con le tue calorie`
        : b.stimate === b.n ? `Stima dell'app su ${quante}`
          : `Somma di ${quante}: ${b.n - b.stimate} con le tue calorie, ${b.stimate} stimate`;
  const apri = () => apriCalorie({
    titolo: 'Calorie bruciate oggi',
    testo: 'Il tuo totale vale al posto della somma delle attività. Non cambia le calorie che puoi mangiare: quelle di un giorno di palestra contano già l\'allenamento.',
    nomeStima: 'Somma delle attività',
    fraseStima: b.n ? `La somma delle attività di oggi: ${b.stimate ? 'circa ' : ''}${intero(b.somma)} kcal.` : 'Oggi non hai ancora segnato attività.',
    tue: b.tuo ? b.kcal : null, salva: (k) => impostaBruciate(d, k), max: 20000,
  });
  return h('div', { class: 'card elenco' },
    h('button', { class: 'voce', onclick: apri },
      h('span', { class: 'ic-att' }, icona('flame')),
      h('div', { class: 'cresce' }, h('b', null, 'Bruciate oggi'), h('small', null, sotto)),
      h('span', { class: 'q' }, `${b.tuo || !b.stimate ? '' : 'circa '}${intero(b.kcal)} kcal`)));
}

// I minuti della settimana, con l'anello e una colonna per giorno.
export function cartaSettimanaMovimento() {
  const o = oggi(), lun = lunedi(o);
  const fatti = minutiSettimana(lun);
  const giorni = INIZIALI.map((l, i) => { const d = piuGiorni(lun, i); return { l, d, min: minutiAttivi(d) }; });
  const tetto = Math.max(30, ...giorni.map((g) => g.min));
  const mancano = Math.max(0, OBIETTIVO_MINUTI - fatti);
  return h('div', { class: 'card movimento' },
    anello({ id: 'mov', val: fatti, max: OBIETTIVO_MINUTI, lato: 112, spessore: 11, colori: ['#5cc8ff', '#6dffa0'], dentro: [h('b', null, intero(fatti)), h('span', null, 'minuti')] }),
    h('div', { class: 'cresce' },
      h('b', { class: 'titolo' }, mancano ? `Ne mancano ${mancano}` : 'Obiettivo della settimana fatto'),
      h('div', { class: 'piccolo' }, `Su ${OBIETTIVO_MINUTI} minuti a settimana`),
      h('div', { class: 'colonnine' }, giorni.map((g) => h('div', { class: g.d === o ? 'oggi' : '' },
        h('i', null, h('u', { style: { height: `${Math.round((g.min / tetto) * 100)}%` } })), h('small', null, g.l)))),
      rigaPassi(giorni.map((g) => g.d))));
}

// I passi dall'app Salute dell'iPhone: oggi e la media dei giorni della settimana che li hanno. Niente, se non arrivano.
function rigaPassi(giorni) {
  const con = giorni.map(passiDel).filter((n) => n != null);
  if (!con.length) return null;
  const oggiN = passiDel(oggi());
  const media = Math.round(con.reduce((a, b) => a + b, 0) / con.length);
  return h('div', { class: 'piccolo passi-riga' }, icona('walk'),
    [oggiN != null ? `Oggi ${oggiN.toLocaleString('it-IT')} passi` : null, `media ${media.toLocaleString('it-IT')} al giorno`].filter(Boolean).join(' · '));
}

// I tasti per aggiungere al volo: un tocco, e si apre il foglio gia' sul tipo giusto.
export function tastiMovimento(tipi = tipiDaProporre()) {
  return h('div', { class: 'tre-azioni' }, tipi.map((id) =>
    h('button', { onclick: () => apriAttivita(id) }, icona(ATTIVITA[id].icona), ATTIVITA[id].n)));
}

export function rigaAttivita(a) {
  const t = ATTIVITA[a.tipo] || ATTIVITA.altro;
  const tue = kcalTue(a);
  const km = a.km ? ` · ${String(a.km).replace('.', ',')} km` : '';
  const kcal = tue != null ? `${intero(tue)} kcal` : `circa ${intero(stimaDi(a))} kcal`;
  return h('button', { class: 'voce', onclick: () => conferma({
    titolo: `${t.n} del ${dataCorta(a.d)}`,
    testo: `${minutiInParole(a.min)}${km} · ${tue != null ? `${intero(tue)} kcal, le tue` : `circa ${intero(stimaDi(a))} kcal, stima dell'app`}`,
    azioni: [
      { t: 'Cambia le calorie', fai: () => apriCalorie({
        titolo: `Calorie: ${t.n.toLowerCase()} del ${dataCorta(a.d)}`, nomeStima: 'Stima dell\'app',
        fraseStima: `Circa ${intero(stimaDi(a))} kcal, dai minuti e dal tuo peso.`, tue, salva: (k) => impostaKcalAttivita(a.id, k),
      }) },
      { t: 'Elimina', tipo: 'rosso', fai: () => { togliAttivita(a.id); avviso('Tolta', 'trash'); } },
      { t: 'Chiudi' },
    ],
  }) },
    h('span', { class: 'ic-att' }, icona(t.icona)),
    h('div', { class: 'cresce' }, h('b', null, t.n), h('small', null, `${daIso(a.d).toLocaleDateString('it-IT', { weekday: 'short', day: 'numeric', month: 'short' })}${km} · ${kcal}`)),
    h('span', { class: 'q' }, minutiInParole(a.min)));
}
