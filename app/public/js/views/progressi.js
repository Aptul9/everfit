import { h, icona, oggi, dec, intero, numero, daIso, dataCorta, lunedi, piuGiorni, maiuscola } from '../dom.js';
import { P, S, io, giorniAllenati, tipoModello, siAllena } from '../store.js';
import { M, salvaPesata, salvaCirconferenze, eliminaMisura, nuovaPesata, profiloCorpo, ultimaPesata, conComposizione } from '../misure.js';
import { grassoMarina, rapporto } from '../corpo.js';
import { grafico, barra, foglio, conferma, avviso } from '../ui.js';
import { apriBilancia, viaBilancia, controllaSentinella, riepilogoPesata, sentinella, daParte, elencoDaParte, aggiungiDaParte, lasciaPerdereDaParte, quandoBreve, riferisci } from '../bilancia.js';
import { cartaRapporto } from './rapporto.js';

const ui = { scheda: 'corpo', es: null, metrica: 'peso' };
const INIZIALI = ['L', 'M', 'M', 'G', 'V', 'S', 'D'];
const FONTI = { bilancia: 'Bilancia', memoria: 'Memoria della bilancia', manuale: 'A mano', starfit: 'Starfit' };
const METRICHE = {
  peso: { n: 'Peso', u: 'kg', d: 2 },
  grasso: { n: 'Grasso', u: '%', d: 1 },
  muscolo: { n: 'Muscolo', u: '%', d: 1 },
  acqua: { n: 'Acqua', u: '%', d: 1 },
};
// [campo, nome, come si misura]
const MISURE = [
  ['vita', 'Vita', 'All\'altezza dell\'ombelico, dopo aver buttato fuori l\'aria, senza stringere il metro.'],
  ['collo', 'Collo', 'Sotto il pomo d\'Adamo, metro orizzontale.'],
  ['spalle', 'Spalle', 'Nel punto più largo, braccia lungo i fianchi. Fatti aiutare se puoi.'],
  ['petto', 'Petto', 'All\'altezza dei capezzoli, dopo aver espirato.'],
  ['braccio', 'Braccio', 'Braccio destro piegato e contratto, nel punto più grosso.'],
  ['coscia', 'Coscia', 'Gamba destra, a metà tra anca e ginocchio.'],
  ['fianchi', 'Fianchi', 'Nel punto più sporgente dei glutei.'],
  ['polpaccio', 'Polpaccio', 'In piedi, nel punto più grosso.'],
];

let rifai = () => {};
const quandoTesto = (q) => `${maiuscola(daIso(q.slice(0, 10)).toLocaleDateString('it-IT', { weekday: 'short', day: 'numeric', month: 'long' }))}, ${q.slice(11, 16)}`;
const segno = (x, n = 1) => `${x > 0 ? '+' : ''}${dec(x, n)}`;

// ---------- pesate ----------
function pesataAMano() {
  const ultima = ultimaPesata();
  const kg = h('input', { type: 'text', inputmode: 'decimal', placeholder: dec(ultima?.peso ?? P.profilo.pesoIniziale, 2), autocomplete: 'off' });
  const data = h('input', { type: 'date', value: oggi(), max: oggi() });
  const f = foglio(() => [
    h('h2', null, 'Pesata a mano'),
    h('p', { class: 'muto' }, io.bilancia ? 'Al mattino, a digiuno, dopo il bagno. Senza bilancia collegata salvo solo peso e indice di massa corporea.'
      : 'Al mattino, a digiuno, dopo il bagno: sempre nello stesso momento, così le pesate si confrontano tra loro.'),
    h('div', { class: 'due-col' },
      h('div', { class: 'campo' }, h('label', null, 'Peso in kg'), kg),
      h('div', { class: 'campo' }, h('label', null, 'Giorno'), data)),
    h('button', { class: 'btn primo', onclick: async () => {
      const v = numero(kg.value);
      if (!v || v < 30 || v > 250) { kg.focus(); avviso('Scrivi il peso in chili', 'info'); return; }
      const g = data.value || oggi();
      const ora = g === oggi() ? undefined : `${g}T08:00:00`;
      f.chiudi();
      const esito = await salvaPesata(nuovaPesata({ peso: v, quando: ora, fonte: 'manuale' }));
      avviso(esito.ok ? 'Pesata salvata' : esito.errore, esito.ok ? 'check' : 'info');
    } }, icona('check'), 'Salva'),
  ]);
  setTimeout(() => kg.focus(), 520);
}

function apriPesata(p) {
  const f = foglio(() => [
    h('div', null,
      h('div', { class: 'chips', style: { marginBottom: '10px' } }, h('span', { class: 'chip acc' }, FONTI[p.fonte] || p.fonte), p.impedenza ? h('span', { class: 'chip' }, `${p.impedenza} ohm`) : null),
      h('h2', null, `${dec(p.peso, 2)} kg`),
      h('p', { class: 'muto' }, quandoTesto(p.quando))),
    riepilogoPesata(p),
    p.grasso != null ? h('div', null,
      [['Indice di massa corporea', dec(p.imc)], ['Massa magra', `${dec(p.peso - p.peso * p.grasso / 100)} kg`], ['Muscolo scheletrico', `${dec(p.scheletrico)}%`],
        ['Proteine', `${dec(p.proteine)}%`], ['Grasso sottocutaneo', `${dec(p.sottocutaneo)}%`], ['Età corporea', `${p.eta_corporea} anni`]]
        .map(([n, v]) => h('div', { class: 'voce' }, h('div', { class: 'cresce' }, h('b', null, n)), h('span', { class: 'q' }, v)))) : null,
    p.nota ? h('p', { class: 'piccolo' }, p.nota) : null,
    h('button', { class: 'btn rosso', onclick: () => conferma({
      titolo: 'Eliminare questa pesata?', testo: 'Sparisce anche dal database sul server.',
      azioni: [{ t: 'Elimina', tipo: 'rosso', fai: async () => { f.chiudi(); const ok = await eliminaMisura('pesate', p); avviso(ok ? 'Pesata eliminata' : 'Serve la rete per eliminarla', ok ? 'trash' : 'info'); } }, { t: 'Annulla' }],
    }) }, icona('trash'), 'Elimina'),
  ]);
}

// La bilancia si usa dall'app per PC oppure, dal telefono, passando dalla sentinella accesa sul PC di casa.
// Quella collegata e' una sola, dell'amministratore (io.bilancia): gli altri segnano il peso a mano, senza sentirsi dire di un PC che non hanno.
// Finche' la carta della pesata e' in vista il collegamento con il PC si ricontrolla da solo: il pallino cambia, e il
// tasto "Pesati ora" compare o sparisce, quando il PC si accende o va a dormire, senza uscire e rientrare nell'app.
// Con il pallino rosso si guarda piu' spesso: chi ha appena riacceso il PC sta aspettando il tasto.
let sorveglia = null;
function tieniDOcchio() {
  if (sorveglia) return;
  let giri = 0, senza = 0;
  sorveglia = setInterval(() => {
    if (!document.querySelector('.pallino-pc')) { clearInterval(sorveglia); sorveglia = null; return; }   // la carta non c'e' piu'
    if (document.visibilityState !== 'visible') return;
    // senza «Pesati ora» per piu' di 15 secondi davanti agli occhi: il telefono lo dice al registro del server
    senza = viaBilancia() ? 0 : senza + 1;
    if (senza === 3) riferisci(sentinella.online === false ? 'rosso' : 'grigio');
    if (!viaBilancia() || ++giri % 3 === 0) controllaSentinella(true);   // rosso: ogni 5 secondi; verde: ogni 15
  }, 5000);
}

function cartaPesati() {
  const collegata = !!io.bilancia;
  const via = collegata ? viaBilancia() : null;
  if (collegata) { controllaSentinella(); tieniDOcchio(); }
  // Del collegamento con il PC di casa si vede solo un pallino: verde se risponde, rosso se no. Quello rosso si puo'
  // toccare: dice in due parole perche' la bilancia adesso non c'e'.
  // Finche' il primo controllo non ha risposto il pallino e' grigio: rosso solo quando il server dice che il PC non c'e'.
  const pallino = !collegata ? null
    : via ? h('span', { class: 'pallino-pc si', role: 'img', 'aria-label': 'PC collegato' })
      : sentinella.online == null ? h('span', { class: 'pallino-pc forse', role: 'img', 'aria-label': 'Controllo il collegamento con il PC' })
        : h('button', { class: 'pallino-pc', 'aria-label': 'PC non collegato: perché?', onclick: () => { riferisci('tocco-rosso'); controllaSentinella(true); avviso('Il PC che collega la bilancia non risponde: di solito riparte da solo, riprova tra un minuto', 'info'); } });
  const testo = via ? 'Peso, grasso, acqua e muscolo in venti secondi.' : 'Pesati al mattino, a digiuno, e segna qui il peso: il grafico si aggiorna da solo.';
  return h('div', { class: 'card' },
    h('div', { class: 'riga' },
      h('span', { class: 'chip acc', style: { width: '44px', height: '44px', padding: 0, justifyContent: 'center', borderRadius: '15px' } }, icona('scale', 'ic22')),
      h('div', { class: 'cresce' }, h('b', { style: { fontSize: '17px' } }, via ? 'Bilancia pronta' : 'Pesata', pallino), h('div', { class: 'piccolo' }, testo))),
    h('div', { class: 'riga', style: { marginTop: '14px' } },
      // "Pesati ora" c'e' solo quando la bilancia puo' pesare davvero (il capo, 12/10/2026: "voglio che esca solo quando
      // mi puo' pesare"): compare da solo appena il PC torna a rispondere, vedi tieniDOcchio
      via ? h('button', { class: 'btn primo', onclick: apriBilancia }, icona('bolt'), 'Pesati ora') : null,
      h('button', { class: `btn${via ? '' : ' primo'}`, style: via ? { width: 'auto', padding: '0 18px', flex: 'none' } : null, onclick: pesataAMano }, via ? 'A mano' : [icona('plus'), 'Nuova pesata'])),
    // le pesate rimaste nella memoria della bilancia: entrano solo se le aggiungi tu (vedi bilancia.js, daParte)
    daParte().length ? h('div', { class: 'da-parte' },
      h('p', null, daParte().length === 1 ? `Nella bilancia c'era una pesata fatta senza app: ${elencoDaParte()}.` : `Nella bilancia c'erano ${daParte().length} pesate fatte senza app: ${elencoDaParte()}.`),
      h('div', { class: 'riga' },
        h('button', { class: 'btn basso', onclick: () => aggiungiDaParte() }, icona('plus'), daParte().length === 1 ? 'Aggiungila' : 'Aggiungile'),
        h('button', { class: 'btn basso', style: { width: 'auto', padding: '0 16px', flex: 'none' }, onclick: () => lasciaPerdereDaParte() }, 'Lascia perdere'))) : null);
}

function cartaAndamento() {
  const tutte = M.pesate;
  // grasso, muscolo e acqua li misura solo la bilancia collegata: chi non ce l'ha vede il peso e basta
  const composizione = !!io.bilancia || tutte.some((x) => x.grasso != null);
  if (!composizione) ui.metrica = 'peso';
  if (!tutte.length) return h('div', { class: 'card vuoto' }, h('b', null, 'La prima pesata ti aspetta'), composizione ? 'Da qui vedrai peso e composizione giorno per giorno.' : 'Da qui vedrai il peso giorno per giorno.');
  const m = METRICHE[ui.metrica];
  const serie = tutte.filter((x) => x[ui.metrica] != null);
  const prima = serie[0], ultima = serie[serie.length - 1];
  const ob = P.profilo.pesoObiettivo;
  const chips = composizione ? h('div', { class: 'seg mini', style: { marginBottom: '16px' } }, Object.entries(METRICHE).map(([k, v]) =>
    h('button', { class: ui.metrica === k ? 'on' : '', onclick: () => { ui.metrica = k; rifai(); } }, v.n))) : null;
  if (!serie.length) return h('div', { class: 'card' }, chips, h('p', { class: 'piccolo' }, 'Questo valore arriva solo dalle pesate fatte con la bilancia collegata.'));
  // chi vuole restare com'e' non ha una strada da fare: niente barra che resterebbe ferma a zero
  const fermo = Math.abs(ob - prima.peso) < 0.05;
  const delta = ultima[ui.metrica] - prima[ui.metrica];
  // il colore dice se il cambiamento va nel verso giusto: il grasso deve scendere, il muscolo salire, e il peso
  // andare verso l'obiettivo (in giu' per chi vuole dimagrire, in su per chi vuole crescere)
  const buono = ui.metrica === 'grasso' ? delta <= 0 : ui.metrica === 'peso' && Number.isFinite(ob) && ob < prima.peso ? delta <= 0 : delta >= 0;
  // il piu' basso e il piu' alto di tutte le pesate, con il giorno (a parita' vale il piu' recente)
  const estremo = (vince) => serie.reduce((a, x) => (vince(x[ui.metrica], a[ui.metrica]) ? x : a));
  const minimo = estremo((v, a) => v <= a), massimo = estremo((v, a) => v >= a);
  const valoreDi = (nome, x) => h('div', null, h('span', null, nome), h('b', null, dec(x[ui.metrica], m.d), h('small', null, ` ${m.u}`)), h('small', null, quandoBreve(x.quando)));
  return h('div', { class: 'card' },
    chips,
    h('div', { class: 'fra', style: { alignItems: 'flex-start' } },
      h('div', null, h('div', { class: 'grande' }, dec(ultima[ui.metrica], m.d), h('small', null, m.u)),
        h('div', { class: 'piccolo', style: { marginTop: '6px' } }, quandoTesto(ultima.quando))),
      serie.length > 1 ? h('span', { class: `delta${buono ? '' : ' giu'}` }, `${segno(delta, m.d)} ${m.u}`) : null),
    serie.length > 1 ? h('div', { class: 'estremi' }, valoreDi('Il più basso', minimo), valoreDi('Il più alto', massimo)) : null,
    ui.metrica === 'peso' ? h('div', { style: { margin: '16px 0 6px' } },
      h('div', { class: 'fra piccolo', style: { marginBottom: '7px', fontWeight: 650 } }, h('span', null, `Partenza ${dec(prima.peso, 2)}`), h('span', { style: { color: 'var(--acc)' } }, fermo ? `Da tenere: ${dec(ob)} kg` : `Obiettivo ${dec(ob)} kg`)),
      fermo ? null : barra({ id: 'peso', val: Math.max(0, (ultima.peso - prima.peso) / (ob - prima.peso)), max: 1, colore: 'linear-gradient(90deg,#c8ff4d,#6dffa0)', alta: true })) : null,
    serie.length > 1
      ? h('div', { style: { marginTop: '14px' } }, grafico(serie.map((x) => ({ x: new Date(x.quando).getTime(), y: x[ui.metrica] })), { meta: ui.metrica === 'peso' ? ob : null, unita: m.u }))
      : h('p', { class: 'piccolo', style: { marginTop: '12px' } }, 'Dalla seconda pesata compare il grafico.'));
}

// ---------- composizione: il semaforo ----------
// Ogni valore ha le sue fasce: [fino a, colore] in ordine, l'ultima vale per tutto il resto. Dipendono da sesso ed eta'.
// Le fasce del grasso sono quelle di Gallagher (2000), le piu' usate; quelle di muscolo, muscolo scheletrico e grasso
// sottocutaneo sono le stesse fasce passate per le formule della bilancia (sono tutti conti fatti dal grasso); l'IMC e'
// quello dell'OMS; la massa magra si giudica rapportata all'altezza (indice di massa magra).
// 'ok' verde, 'occhio' giallo, 'no' rosso; senza fasce il valore e' solo un'informazione ('info').
const NOMI_SEMAFORO = { ok: 'Va bene', occhio: 'Da tenere d\'occhio', no: 'Fuori dalla norma', info: 'Solo un\'informazione' };
function fasce(chiave, { sesso, eta, altezza }) {
  const d = sesso === 'f';
  const g = eta < 40 ? (d ? [21, 33, 39] : [8, 20, 25]) : eta < 60 ? (d ? [23, 34, 40] : [11, 22, 28]) : (d ? [24, 36, 42] : [13, 25, 30]);
  switch (chiave) {
    case 'grasso': return { fasce: [[g[0], 'occhio'], [g[1], 'ok'], [g[2], 'occhio'], [Infinity, 'no']], norma: `tra ${g[0]} e ${g[1]}%` };
    case 'muscolo': { const a = d ? [57, 63] : [70, 75]; return { fasce: [[a[0], 'no'], [a[1], 'occhio'], [Infinity, 'ok']], norma: `sopra il ${a[1]}%` }; }
    case 'scheletrico': { const a = d ? [42, 46] : [51.5, 55]; return { fasce: [[a[0], 'no'], [a[1], 'occhio'], [Infinity, 'ok']], norma: `sopra il ${dec(a[1])}%` }; }
    case 'acqua': { const a = d ? [40, 45, 60] : [45, 50, 65]; return { fasce: [[a[0], 'no'], [a[1], 'occhio'], [a[2], 'ok'], [Infinity, 'occhio']], norma: `tra ${a[1]} e ${a[2]}%` }; }
    case 'viscerale': return { fasce: [[9.5, 'ok'], [14.5, 'occhio'], [Infinity, 'no']], norma: 'fino a 9' };
    case 'sottocutaneo': { const a = d ? [14.2, 21.6, 25] : [5.6, 13.6, 16.8]; return { fasce: [[a[0], 'occhio'], [a[1], 'ok'], [a[2], 'occhio'], [Infinity, 'no']], norma: `tra ${dec(a[0])} e ${dec(a[1])}%` }; }
    case 'imc': return { fasce: [[17, 'no'], [18.5, 'occhio'], [25, 'ok'], [30, 'occhio'], [Infinity, 'no']], norma: 'tra 18,5 e 25' };
    case 'magra': { const a = d ? [13, 14.5] : [16.5, 18]; const m2 = (altezza / 100) ** 2; return { fasce: [[a[0] * m2, 'no'], [a[1] * m2, 'occhio'], [Infinity, 'ok']], norma: `sopra i ${dec(a[1] * m2)} kg per la tua altezza` }; }
    case 'eta_corporea': return { fasce: [[eta + 0.5, 'ok'], [eta + 3.5, 'occhio'], [Infinity, 'no']], norma: `non più della tua età (${eta})` };
    default: return null;
  }
}
const magraDi = (x) => x.peso - x.peso * x.grasso / 100;
const imcDi = (x) => x.imc ?? (x.peso / ((x.altezza || P.profilo.altezza) / 100) ** 2);
// [chiave, nome, come leggere il valore da una pesata, unita', decimali, scende = migliora]
const VALORI = {
  grasso: ['Grasso', (x) => x.grasso, '%', 1, true],
  muscolo: ['Muscolo', (x) => x.muscolo, '%', 1, false],
  acqua: ['Acqua', (x) => x.acqua, '%', 1, false],
  magra: ['Massa magra', magraDi, ' kg', 1, false],
  scheletrico: ['Muscolo scheletrico', (x) => x.scheletrico, '%', 1, false],
  proteine: ['Proteine', (x) => x.proteine, '%', 1, null],
  viscerale: ['Grasso viscerale', (x) => x.viscerale, '', 1, true],
  sottocutaneo: ['Grasso sottocutaneo', (x) => x.sottocutaneo, '%', 1, true],
  imc: ['Indice di massa corporea', imcDi, '', 1, null],
  ossa_kg: ['Ossa', (x) => x.ossa_kg, ' kg', 1, null],
  bmr: ['Metabolismo basale', (x) => x.bmr, ' kcal', 0, null],
  eta_corporea: ['Età corporea', (x) => x.eta_corporea, ' anni', 0, true],
  impedenza: ['Impedenza', (x) => x.impedenza, ' ohm', 0, null],
};
// Cosa vuol dire e cosa fare: [in due parole, [come migliorarlo...]]
const SPIEGA = {
  grasso: ['È la parte del tuo peso fatta di grasso. È il numero da guardare quando vuoi dimagrire: il peso da solo non dice se stai perdendo grasso o muscolo.',
    ['Resta nel deficit leggero del piano: tagliare di più fa perdere muscolo.', 'Proteine tutti i giorni come da piano, e pesi tre volte a settimana.', 'Cammina mezz\'ora al giorno: è il modo più facile di consumare di più.', 'Scende piano: mezzo punto al mese è già un buon ritmo.']],
  muscolo: ['Quanto del tuo peso è muscolo e organi, cioè tutto tranne grasso e ossa. Sale quando perdi grasso o metti muscolo.',
    ['Allenati con i pesi cercando ogni volta una ripetizione o un po\' di carico in più.', 'Non saltare le proteine del piano.', 'Dormi: il muscolo si costruisce a riposo.']],
  acqua: ['L\'acqua che hai in corpo. I muscoli ne tengono tanta, il grasso poca, quindi sale quando la composizione migliora. Da un giorno all\'altro può cambiare anche di un punto.',
    ['Bevi l\'acqua prevista dal piano, un po\' di più nei giorni di palestra.', 'Pesati sempre nelle stesse condizioni: al mattino, a digiuno, dopo il bagno.']],
  magra: ['Tutto quello che non è grasso: muscoli, ossa, acqua, organi. Mentre dimagrisci deve restare ferma: se scende insieme al peso stai perdendo muscolo. Il colore la giudica rispetto alla tua altezza.',
    ['Pesi con carichi che salgono, anche poco per volta.', 'Proteine alte e niente tagli drastici alle calorie.', 'Se è bassa per la tua altezza, c\'è margine per mettere muscolo: cambia l\'aspetto più di un chilo in meno.']],
  scheletrico: ['I muscoli che muovi, quelli che con l\'allenamento crescono. La bilancia lo ricava dal grasso, quindi si muove insieme a lui.',
    ['Vale quello che vale per il muscolo: pesi, proteine, sonno.']],
  proteine: ['È un conto fatto dagli altri valori (quello che resta tolti acqua, grasso e ossa). Non c\'è niente da inseguire: guardalo solo per curiosità.', []],
  viscerale: ['Il grasso attorno agli organi, dentro la pancia: è quello che conta di più per la salute. Fino a 9 va bene.',
    ['Scende con il deficit e con il movimento: camminare tutti i giorni aiuta più di tutto.', 'Poco alcol e poche bibite zuccherate.', 'Dormi a orari regolari: il sonno corto lo fa salire.']],
  sottocutaneo: ['Il grasso sotto la pelle, quello che si vede e si pizzica (pancia, fianchi).',
    ['Si perde con lo stesso deficit che fa scendere il grasso totale.', 'Non si può scegliere da dove toglierlo: la pancia di solito è l\'ultima a andarsene.', 'Gli addominali rinforzano il muscolo, non tolgono il grasso che ci sta sopra.']],
  imc: ['Il peso rapportato all\'altezza. Dice se il peso è nella norma, ma non distingue il muscolo dal grasso: per questo va letto insieme al grasso.',
    ['Se sei già nella fascia normale, più che far scendere il peso conviene cambiare la composizione: meno grasso, più muscolo.']],
  ossa_kg: ['Il peso stimato delle ossa. Cambia pochissimo: è solo un\'informazione.', []],
  bmr: ['Le calorie che consumi stando fermo tutto il giorno. Il piano parte da qui per decidere quanto farti mangiare. Più muscolo hai, più è alto.', ['Non si alza mangiando meno: si alza mettendo muscolo.']],
  eta_corporea: ['Un confronto tra il tuo grasso e quello medio alla tua età: più bassa della tua età vuol dire meglio della media.', ['Scende quando scende il grasso.']],
  impedenza: ['Il dato grezzo della bilancia: quanta fatica fa una piccola corrente ad attraversarti. Da qui escono tutti gli altri numeri. Cambia con l\'acqua che hai in corpo e con i piedi asciutti o bagnati.', ['Per numeri confrontabili: sempre al mattino, a digiuno, a piedi nudi e asciutti.']],
};

function semaforo(chiave, x) {
  const f = fasce(chiave, { ...profiloCorpo(), eta: x.eta || profiloCorpo().eta });
  const v = VALORI[chiave][1](x);
  if (!f || v == null) return { colore: 'info', norma: null };
  return { colore: f.fasce.find(([fino]) => v < fino)[1], norma: f.norma, fasce: f.fasce };
}

function apriValore(chiave) {
  const con = conComposizione();
  const [nome, leggi, unita, cifre, scende] = VALORI[chiave];
  const p = con[con.length - 1], prima = con[0];
  const v = leggi(p), sem = semaforo(chiave, p);
  const punti = con.filter((x) => leggi(x) != null).map((x) => ({ x: daIso(x.giorno).getTime(), y: leggi(x) }));
  const d = con.length > 1 ? v - leggi(prima) : 0;
  const [spiega, consigli] = SPIEGA[chiave];
  const numero_ = (n) => (cifre ? dec(n, cifre) : intero(n));
  foglio(() => [
    h('h2', null, nome),
    h('div', { class: 'riga', style: { alignItems: 'baseline', gap: '10px' } },
      h('b', { class: 'grande' }, numero_(v), h('small', null, unita.trim())),
      h('span', { class: `chip semaforo ${sem.colore}` }, h('i', { class: `bollo ${sem.colore}` }), NOMI_SEMAFORO[sem.colore])),
    sem.norma ? h('p', { class: 'muto' }, `Per te va bene ${sem.norma}.`) : null,
    punti.length > 1
      ? h('div', { class: 'card' },
        h('div', { class: 'fra', style: { marginBottom: '6px' } }, h('b', null, 'Andamento'),
          Math.abs(d) >= 0.05 ? h('span', { class: `chip ${scende == null ? '' : (scende ? d < 0 : d > 0) ? 'acc' : ''}` }, `${segno(d, cifre || 0)}${unita} dal ${dataCorta(prima.giorno)}`) : h('span', { class: 'piccolo' }, 'fermo')),
        grafico(punti, { unita: unita.trim() }))
      : h('div', { class: 'card vuoto' }, h('b', null, 'L\'andamento arriva con la prossima pesata'), 'Con due misure si vede se sale o scende.'),
    h('h4', null, 'Cosa vuol dire'),
    h('p', { class: 'muto', style: { lineHeight: 1.5 } }, spiega),
    consigli.length ? h('h4', null, sem.colore === 'ok' ? 'Come tenerlo così' : sem.colore === 'info' ? 'Da sapere' : 'Come migliorarlo') : null,
    consigli.length ? h('ul', { class: 'punti' }, consigli.map((c) => h('li', null, c))) : null,
    h('p', { class: 'piccolo', style: { lineHeight: 1.45 } }, 'Le bilance a impedenza sbagliano di qualche punto in assoluto: conta come si muove il numero nel tempo, più del numero di oggi.'),
  ]);
}

function tessera(chiave, testo, sotto, variazione) {
  const con = conComposizione();
  const colore = semaforo(chiave, con[con.length - 1]).colore;
  return h('button', { class: `tessera tocco ${colore}`, 'aria-label': `${VALORI[chiave][0]}: ${NOMI_SEMAFORO[colore]}. Tocca per i dettagli`, onclick: () => apriValore(chiave) },
    h('span', null, h('i', { class: `bollo ${colore}` }), VALORI[chiave][0]),
    h('b', null, testo),
    h('small', null, sotto || ' ', variazione ? h('i', { class: variazione.buono ? 'su' : 'giu' }, ` ${variazione.t}`) : null));
}

function cartaComposizione() {
  const con = conComposizione();
  if (!con.length) return null;
  const p = con[con.length - 1], prima = con[0];
  const kg = (x, perc) => `${dec(x.peso * perc / 100)} kg`;
  // variazione dalla prima misura completa; `giu` = il valore migliora quando scende
  const cambio = (campo, giu, n = 1, valore = (x) => x[campo]) => {
    if (con.length < 2) return null;
    const d = valore(p) - valore(prima);
    if (Math.abs(d) < 0.05) return null;
    return { t: segno(d, n), buono: giu ? d < 0 : d > 0 };
  };
  return [
    h('div', { class: 'sez' }, h('h2', null, 'Composizione'), h('span', null, dataCorta(p.giorno))),
    h('div', { class: 'rap-legenda', style: { margin: '-4px 4px 2px' } },
      ['ok', 'occhio', 'no'].map((c) => h('span', null, h('i', { class: `bollo ${c}` }), NOMI_SEMAFORO[c])), h('span', null, 'tocca un valore')),
    h('div', { class: 'tessere' },
      tessera('grasso', `${dec(p.grasso)}%`, kg(p, p.grasso), cambio('grasso', true)),
      tessera('muscolo', `${dec(p.muscolo)}%`, kg(p, p.muscolo), cambio('muscolo', false)),
      tessera('acqua', `${dec(p.acqua)}%`, kg(p, p.acqua), cambio('acqua', false)),
      tessera('magra', `${dec(magraDi(p))} kg`, null, cambio('magra', false, 1, magraDi)),
      tessera('scheletrico', `${dec(p.scheletrico)}%`, null, cambio('scheletrico', false)),
      tessera('viscerale', dec(p.viscerale), 'meglio sotto 9', cambio('viscerale', true)),
      tessera('sottocutaneo', `${dec(p.sottocutaneo)}%`, null, cambio('sottocutaneo', true)),
      tessera('imc', dec(imcDi(p)), 'peso per altezza', null),
      tessera('eta_corporea', `${p.eta_corporea}`, `anni, ne hai ${p.eta}`, null),
      tessera('bmr', intero(p.bmr), 'kcal al giorno', cambio('bmr', false, 0)),
      tessera('proteine', `${dec(p.proteine)}%`, kg(p, p.proteine), null),
      tessera('ossa_kg', `${dec(p.ossa_kg)} kg`, null, null),
      tessera('impedenza', `${p.impedenza}`, 'ohm, il dato grezzo', null)),
    h('p', { class: 'piccolo', style: { padding: '0 4px', lineHeight: 1.45 } }, 'Stesse formule dell\'app Starfit. Le bilance a impedenza sbagliano di qualche punto in assoluto: guarda come si muovono i numeri nel tempo, sempre al mattino e a digiuno.'),
  ];
}

// ---------- circonferenze ----------
function misuraMetro() {
  const ultima = M.circonferenze[M.circonferenze.length - 1] || {};
  const campi = Object.fromEntries(MISURE.map(([k]) => [k, h('input', { type: 'text', inputmode: 'decimal', placeholder: ultima[k] != null ? dec(ultima[k]) : 'cm', autocomplete: 'off' })]));
  const f = foglio(() => [
    h('h2', null, 'Misure con il metro'),
    h('p', { class: 'muto' }, 'Ogni due settimane, al mattino, muscoli a riposo. Compila quelle che vuoi: bastano vita, collo e spalle.'),
    ...MISURE.map(([k, nome, come]) => h('div', { class: 'campo' }, h('label', null, `${nome} in cm`), campi[k], h('span', { class: 'piccolo', style: { paddingLeft: '4px' } }, come))),
    h('button', { class: 'btn primo', onclick: async () => {
      const riga = { giorno: oggi() };
      for (const [k, nome] of MISURE) {
        const testo = campi[k].value.trim();
        if (!testo) continue;
        const v = numero(testo);
        if (!v || v < 10 || v > 250) { campi[k].focus(); avviso(`${nome}: scrivi i centimetri`, 'info'); return; }
        riga[k] = v;
      }
      if (Object.keys(riga).length === 1) { avviso('Scrivi almeno una misura', 'info'); return; }
      f.chiudi();
      const esito = await salvaCirconferenze(riga);
      avviso(esito.ok ? 'Misure salvate' : esito.errore, esito.ok ? 'check' : 'info');
    } }, icona('check'), 'Salva'),
  ]);
}

function cartaCirconferenze() {
  const c = M.circonferenze;
  const testa = h('div', { class: 'sez' }, h('h2', null, 'Con il metro'), c.length ? h('span', null, dataCorta(c[c.length - 1].giorno)) : null);
  const bottone = h('button', { class: 'btn', style: { marginTop: '14px' }, onclick: misuraMetro }, icona('plus'), c.length ? 'Nuove misure' : 'Prendi le misure');
  if (!c.length) {
    return [testa, h('div', { class: 'card' },
      h('p', { class: 'muto', style: { fontSize: '14.5px', lineHeight: 1.45 } }, 'La bilancia non vede dove cambia il corpo. Vita, collo e spalle dicono se la pancia scende e le spalle si allargano: sono i numeri che contano di più per il tuo obiettivo.'),
      bottone)];
  }
  // per ogni misura: ultimo e primo valore noto, anche se presi in giorni diversi
  const ultimo = (k) => [...c].reverse().find((x) => x[k] != null);
  const primo = (k) => c.find((x) => x[k] != null);
  const val = (k) => ultimo(k)?.[k] ?? null;
  const pr = profiloCorpo();
  const formaV = rapporto(val('spalle'), val('vita'));
  const vitaAlt = rapporto(val('vita'), pr.altezza);
  const marina = grassoMarina({ sesso: pr.sesso, altezza: pr.altezza, collo: val('collo'), vita: val('vita'), fianchi: val('fianchi') });
  const stat = (testo, nome, sotto) => h('div', { class: 'stat' }, h('b', null, testo), h('span', null, nome), h('small', { class: 'piccolo', style: { display: 'block' } }, sotto));
  return [testa, h('div', { class: 'card' },
    (formaV || vitaAlt || marina) ? h('div', { class: 'tre-col', style: { marginBottom: '8px' } },
      formaV ? stat(dec(formaV, 2), 'spalle / vita', 'obiettivo 1,5') : null,
      vitaAlt ? stat(dec(vitaAlt, 2), 'vita / altezza', 'bene sotto 0,5') : null,
      marina ? stat(`${dec(marina)}%`, 'grasso dal metro', 'da vita e collo') : null) : null,
    h('div', null, MISURE.filter(([k]) => val(k) != null).map(([k, nome]) => {
      const d = ultimo(k)[k] - primo(k)[k];
      return h('div', { class: 'voce' }, h('div', { class: 'cresce' }, h('b', null, nome)),
        Math.abs(d) >= 0.05 ? h('span', { class: 'piccolo num' }, `${segno(d)} cm`) : null,
        h('span', { class: 'q' }, `${dec(val(k))} cm`));
    })),
    bottone,
    h('button', { class: 'btn basso rosso', style: { marginTop: '10px' }, onclick: () => conferma({
      titolo: `Eliminare le misure del ${dataCorta(c[c.length - 1].giorno)}?`,
      azioni: [{ t: 'Elimina', tipo: 'rosso', fai: async () => { const ok = await eliminaMisura('circonferenze', c[c.length - 1]); avviso(ok ? 'Misure eliminate' : 'Serve la rete per eliminarle', ok ? 'trash' : 'info'); } }, { t: 'Annulla' }],
    }) }, 'Elimina le ultime'))];
}

function elencoPesate() {
  const pes = [...M.pesate].reverse().slice(0, 10);
  if (!pes.length) return null;
  return [
    h('div', { class: 'sez' }, h('h2', null, 'Pesate'), h('span', null, `${M.pesate.length} in tutto`)),
    h('div', { class: 'card', style: { paddingTop: '6px', paddingBottom: '6px' } }, pes.map((x) =>
      h('button', { class: 'voce', onclick: () => apriPesata(x) },
        h('div', { class: 'cresce' }, h('b', null, quandoTesto(x.quando)), h('small', null, `${FONTI[x.fonte] || x.fonte}${x.grasso != null ? ` · grasso ${dec(x.grasso)}%` : ''}`)),
        h('span', { class: 'q' }, `${dec(x.peso, 2)} kg`)))),
  ];
}

// ---------- allenamenti ----------
// Gli allenamenti contano per giorni: quelli con la seduta segnata e quelli di palestra lasciati su "Gym" (store.js, allenato).
const nellaSettimana = (fatti, lun) => [0, 1, 2, 3, 4, 5, 6].filter((i) => fatti.has(piuGiorni(lun, i))).length;
function settimaneDiFila(fatti) {
  let n = 0;
  let lun = lunedi(oggi());
  if (!nellaSettimana(fatti, lun)) lun = piuGiorni(lun, -7);
  while (nellaSettimana(fatti, lun)) { n++; lun = piuGiorni(lun, -7); }
  return n;
}

function cartaSedute() {
  const o = oggi();
  const lun = lunedi(o);
  const giorniFatti = giorniAllenati();
  const questa = nellaSettimana(giorniFatti, lun);
  const celle = [];
  for (let w = 4; w >= 0; w--) {
    for (let i = 0; i < 7; i++) {
      const d = piuGiorni(lun, i - w * 7);
      const fatta = giorniFatti.has(d);
      celle.push(h('i', { class: `${fatta ? 'all' : ''} ${d === o ? 'oggi' : ''}`, title: dataCorta(d) }, fatta ? '' : (tipoModello(d) === 'train' && d >= o ? '·' : '')));
    }
  }
  return h('div', { class: 'card' },
    h('div', { class: 'tre-col' },
      h('div', { class: 'stat' }, h('b', null, siAllena() ? `${questa}/${P.settimana.filter((g) => g.tipo === 'train').length || 3}` : questa), h('span', null, 'questa sett.')),
      h('div', { class: 'stat' }, h('b', null, giorniFatti.size), h('span', null, 'in totale')),
      h('div', { class: 'stat' }, h('b', null, settimaneDiFila(giorniFatti)), h('span', null, 'sett. di fila'))),
    h('div', { class: 'puntini', style: { marginTop: '16px' } }, INIZIALI.map((l) => h('i', { class: 'tit' }, l)), celle),
    h('p', { class: 'piccolo', style: { marginTop: '10px', textAlign: 'center' } }, 'Ultime cinque settimane'));
}

function cartaCarichi() {
  const fatti = new Map();
  for (const x of S.sedute) for (const v of x.voci) if (!P.esercizi[v.es]?.tempo) fatti.set(v.es, (fatti.get(v.es) || 0) + 1);
  if (!fatti.size) return h('div', { class: 'card vuoto' }, h('b', null, 'I carichi compaiono qui'), 'Dopo la prima seduta vedrai come sale ogni esercizio.');
  const lista = [...fatti.keys()].sort((a, b) => P.esercizi[a].n.localeCompare(P.esercizi[b].n, 'it'));
  if (!ui.es || !fatti.has(ui.es)) ui.es = lista[0];
  const punti = [];
  for (const x of S.sedute) {
    const v = x.voci.find((q) => q.es === ui.es);
    if (!v) continue;
    const top = v.serie.reduce((m, q) => (!m || (q.kg || 0) > m.kg || ((q.kg || 0) === m.kg && q.rip > m.rip) ? { kg: q.kg || 0, rip: q.rip } : m), null);
    if (top) punti.push({ x: daIso(x.d).getTime(), y: top.kg, rip: top.rip, d: x.d, serie: v.serie });
  }
  const ultimo = punti[punti.length - 1], primo = punti[0];
  return h('div', { class: 'card' },
    h('div', { class: 'campo' },
      h('label', null, 'Esercizio'),
      h('select', { onchange: (e) => { ui.es = e.target.value; rifai(); } }, lista.map((id) => h('option', { value: id, selected: id === ui.es }, P.esercizi[id].n)))),
    h('div', { class: 'fra', style: { margin: '16px 0 4px', alignItems: 'flex-start' } },
      h('div', { class: 'grande' }, dec(ultimo.y, 2), h('small', null, `kg × ${ultimo.rip}`)),
      punti.length > 1 ? h('span', { class: `delta${ultimo.y - primo.y < 0 ? ' giu' : ''}` }, `${segno(ultimo.y - primo.y, 2)} kg`) : null),
    punti.length > 1 ? grafico(punti, { unita: 'kg' }) : h('p', { class: 'piccolo' }, 'Serve una seconda seduta per vedere l\'andamento.'),
    h('div', { style: { marginTop: '8px' } }, [...punti].reverse().slice(0, 4).map((p) => h('div', { class: 'voce' },
      h('div', { class: 'cresce' }, h('b', null, dataCorta(p.d))), h('span', { class: 'q' }, p.serie.map((q) => `${dec(q.kg || 0, 2)}×${q.rip}`).join('  ·  '))))));
}

// Dalla Home la carta del peso apre la scheda Corpo, dove c'e' la bilancia, e quella della seduta fatta gli Allenamenti.
// Prima Progressi riapriva l'ultima scheda guardata: dalla carta del peso si poteva finire su Dieta, senza «Pesati ora»
// (il capo, 28/10/2026: "a volte non esce neanche il pesati ora").
export function mostraScheda(id) { ui.scheda = id; }

export function vistaProgressi(_, ridisegna) {
  rifai = ridisegna;
  const scheda = (id, nome) => h('button', { class: ui.scheda === id ? 'on' : '', onclick: () => { ui.scheda = id; rifai(true); } }, nome);
  return [
    h('div', { class: 'top' }, h('div', null, h('div', { class: 'sopra' }, `Dal ${dataCorta(P.profilo.dataInizio)}`), h('h1', null, 'Progressi'))),
    h('div', { class: 'seg' }, scheda('corpo', 'Corpo'), scheda('dieta', 'Dieta'), scheda('allenamenti', 'Allenamenti')),
    ...(ui.scheda === 'corpo' ? [cartaPesati(), cartaAndamento(), cartaComposizione(), cartaCirconferenze(), elencoPesate()]
      : ui.scheda === 'dieta' ? cartaRapporto()
        : [cartaSedute(), h('div', { class: 'sez' }, h('h2', null, 'Carichi')), cartaCarichi()]),
  ];
}
