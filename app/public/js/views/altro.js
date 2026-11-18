// La scheda "Piano": il profilo e gli obiettivi, la guida, l'account, le persone (solo per chi gestisce l'app),
// la chiave dell'intelligenza artificiale e i dati.

import { h, icona, dec, intero, oggi, dataCorta } from '../dom.js';
import { P, S, io, sync, esporta, importa, azzera, aggiorna, esci, rinomina, aggiornaIo, siAllena, CASA, vuole, scegliCasa, pianoScritto, menuDelPiano, scegliMenu } from '../store.js';
import { tema, cambiaTema } from '../tema.js';
import { riassuntoProfilo, scelta } from './profilo.js';
import { M } from '../misure.js';
import { mappaCorpo, conferma, avviso, foglio } from '../ui.js';
import { possibili, iphoneFuoriDallaHome, statoNotifiche, attivaNotifiche, spegniNotifiche, promemoriaPasti, provaNotifica } from '../notifiche.js';

const ui = { carente: -1, aperta: null };
const inApp = () => matchMedia('(display-mode: standalone)').matches || navigator.standalone === true;
const JSON_ = { 'Content-Type': 'application/json' };
const tessera = (ic, acceso = true) => h('span', { class: `chip ${acceso ? 'acc' : ''}`, style: { width: '36px', height: '36px', padding: 0, justifyContent: 'center', borderRadius: '12px', flex: 'none' } }, icona(ic));

function profilo() {
  const p = P.profilo, o = P.obiettivi;
  const riga = (nome, x) => h('tr', null, h('td', null, nome), h('td', null, intero(x.kcal)), h('td', null, `${x.p} g`), h('td', null, `${x.c} g`), h('td', null, `${x.f} g`));
  return h('div', { class: 'card' },
    h('div', { class: 'tre-col' },
      h('div', { class: 'stat' }, h('b', null, dec(p.pesoIniziale, 1), h('small', null, 'kg')), h('span', null, 'Partenza')),
      h('div', { class: 'stat' }, h('b', null, dec(p.pesoObiettivo), h('small', null, 'kg')), h('span', null, 'Obiettivo')),
      h('div', { class: 'stat' }, h('b', null, p.altezza, h('small', null, 'cm')), h('span', null, 'Altezza'))),
    h('table', { class: 'tabella', style: { marginTop: '16px' } },
      h('thead', null, h('tr', null, h('th', null, 'Ogni giorno'), h('th', null, 'kcal'), h('th', { style: { color: 'var(--p)' } }, 'Prot.'), h('th', { style: { color: 'var(--c)' } }, 'Carbo'), h('th', { style: { color: 'var(--f)' } }, 'Grassi'))),
      h('tbody', null, siAllena() ? [riga('Palestra', o.train), riga('Riposo', o.rest)] : riga('Tutti i giorni', o.rest))),
    p.fonte ? h('p', { class: 'piccolo', style: { marginTop: '12px' } }, p.fonte) : null);
}

// Chi ha la dieta in due forme (un menu che cambia ogni giorno, o lo schema fisso di chi l'ha scritta) l'ha scelta
// alla prima apertura: qui puo' cambiare idea senza rifare tutte le domande.
function formaDieta() {
  const menu = menuDelPiano();
  if (!menu) return null;
  const ora = S.opzioni.menu === 'fisso' ? 'fisso' : 'giro';
  return [
    h('div', { class: 'sez' }, h('h2', null, 'Come segui la dieta')),
    ...['giro', 'fisso'].map((id) => scelta(ora === id, menu[id]?.[0] || id, menu[id]?.[1], () => {
      if (ora === id) return;
      scegliMenu(id);
      avviso(id === 'fisso' ? 'Da oggi vedi lo schema fisso' : 'Da oggi vedi il menu che cambia', 'check');
    })),
  ];
}

function carenti(rifai) {
  const pc = P.puntiCarenti;
  const scelti = ui.carente < 0 ? pc.flatMap((x) => x.m) : pc[ui.carente].m;
  return h('div', { class: 'card' },
    mappaCorpo(scelti, [], 'rosso'),
    h('div', { style: { marginTop: '10px' } }, pc.map((x, i) =>
      h('button', { class: `carente${ui.carente === i ? ' on' : ''}`, onclick: () => { ui.carente = ui.carente === i ? -1 : i; rifai(); } },
        h('span', { class: 'n' }, i + 1), h('div', null, h('b', null, x.t), h('p', null, x.d))))));
}

function guida() {
  return P.guida.map((g) => h('div', { class: `card fisarmonica${ui.aperta === g.id ? ' aperta' : ''}` },
    h('button', { 'aria-expanded': ui.aperta === g.id, onclick: (e) => {
      ui.aperta = ui.aperta === g.id ? null : g.id;
      for (const el of document.querySelectorAll('.fisarmonica')) el.classList.toggle('aperta', el === e.currentTarget.parentElement && ui.aperta === g.id);
    } }, h('span', { class: 'ic' }, icona(g.icona)), g.t, h('span', { class: 'fr' }, icona('chev'))),
    h('div', { class: 'dentro' }, h('div', null, h('ul', null, g.p.map((t) => h('li', null, t)))))));
}

function installa() {
  if (inApp() || window.pywebview) return null;
  return [
    h('div', { class: 'sez' }, h('h2', null, 'Mettila sulla Home')),
    h('div', { class: 'card' },
      h('ol', { class: 'passi' },
        h('li', null, h('span', null, 'Apri questa pagina in Safari e tocca ', h('b', null, 'Condividi'), ' in basso.')),
        h('li', null, h('span', null, 'Scegli ', h('b', null, 'Aggiungi alla schermata Home'), '.')),
        h('li', null, 'Da lì si apre a tutto schermo, già dentro il tuo account, e funziona anche senza rete.'))),
  ];
}

// ---------- account: il nome, e l'uscita da questo dispositivo ----------
function cambiaNome() {
  const campo = h('input', { type: 'text', value: io.nome, maxlength: 24, autocomplete: 'off', autocapitalize: 'words', 'aria-label': 'Il tuo nome' });
  const f = foglio(() => [
    h('h2', null, 'Come ti chiami?'),
    h('p', { class: 'muto' }, 'È il nome con cui l\'app ti saluta.'),
    h('div', { class: 'campo' }, campo),
    h('button', { class: 'btn primo', onclick: async () => {
      const nome = campo.value.trim();
      if (!nome) { campo.focus(); return; }
      try { await rinomina(nome); f.chiudi(); avviso('Nome cambiato'); } catch (e) { avviso(navigator.onLine === false ? 'Sei senza rete' : e.message, 'info'); }
    } }, 'Salva'),
  ]);
}

function account(rifai) {
  return h('div', { class: 'card' },
    h('div', { class: 'riga' },
      h('span', { class: 'faccia grande' }, (io.nome || '?').charAt(0).toUpperCase()),
      h('div', { class: 'cresce' }, h('b', { style: { fontSize: '17px' } }, io.nome), h('div', { class: 'piccolo' }, io.capo ? 'Amministratore: gestisci tu le persone che usano l\'app' : `${io.utente || ''} · vedi solo i tuoi dati`)),
      h('button', { class: 'tondo', 'aria-label': 'Cambia nome', onclick: cambiaNome }, icona('edit'))),
    aspetto(rifai),
    io.esci ? h('button', { class: 'btn basso', style: { marginTop: '14px' }, onclick: () => conferma({
      titolo: 'Uscire da questo dispositivo?', testo: 'I tuoi dati restano sul server. Per rientrare servirà di nuovo il tuo codice.',
      azioni: [{ t: 'Esci', tipo: 'rosso', fai: () => esci().catch(() => avviso(navigator.onLine === false ? 'Sei senza rete: riprova dopo' : 'Non riesco a uscire: riprova', 'info')) }, { t: 'Annulla' }],
    }) }, icona('exit'), 'Esci da questo dispositivo') : null);
}

// ---------- la tua Home: i pezzi della schermata Oggi, e le domande del primo avvio da rifare quando si vuole ----------
function interruttore(acceso, tocca, etichetta) {
  return h('button', { class: `interruttore${acceso ? ' on' : ''}`, role: 'switch', 'aria-checked': acceso, 'aria-label': etichetta, onclick: tocca }, h('i'));
}

function casa() {
  return h('div', { class: 'card' },
    h('div', { class: 'elenco-leve' }, Object.entries(CASA).map(([id, [titolo, sotto]]) =>
      h('div', { class: 'fra' },
        h('div', null, h('b', null, titolo), h('div', { class: 'piccolo' }, sotto)),
        interruttore(vuole(id), () => scegliCasa(id, !vuole(id)), titolo)))),
    // le domande del primo avvio si possono rifare; sull'account dell'amministratore non ci sono, ne' all'inizio ne' qui
    io.capo ? null : h('button', { class: 'btn basso', style: { marginTop: '14px' }, onclick: () => { location.hash = '#/profilo'; } }, icona('edit'),
      riassuntoProfilo() ? 'Rifai le domande' : 'Rispondi a qualche domanda'),
    io.capo ? null : h('p', { class: 'piccolo', style: { marginTop: '10px', lineHeight: 1.45 } }, pianoScritto()
      ? 'Obiettivo, numeri, giorni di allenamento e orari dei pasti: l\'app si regola su quello che rispondi. La dieta resta la tua.'
      : 'Obiettivo, numeri, giorni di allenamento e cibi esclusi: da qui si ricalcola il piano.'));
}

// ---------- aspetto: scuro (com'e' nata) o chiaro ----------
function aspetto(rifai) {
  const chiaro = tema() === 'chiaro';
  return h('div', { class: 'fra', style: { marginTop: '16px' } },
    h('div', null, h('b', null, 'Aspetto'), h('div', { class: 'piccolo' }, chiaro ? 'Chiaro. Vale per questo dispositivo.' : 'Scuro. Vale per questo dispositivo.')),
    h('div', { class: 'seg mini', style: { width: '148px', flex: 'none' } },
      h('button', { class: chiaro ? '' : 'on', onclick: () => { cambiaTema('scuro'); rifai(); } }, icona('moon'), 'Scuro'),
      h('button', { class: chiaro ? 'on' : '', onclick: () => { cambiaTema('chiaro'); rifai(); } }, icona('sun'), 'Chiaro')));
}

// ---------- persone: chi puo' usare l'app. Le vede e le crea solo chi la gestisce ----------
// Ognuno entra con il suo nome utente e la sua password, e vede solo i suoi dati. La password si sceglie qui: il server
// ne tiene solo l'impasto, quindi non si puo' rileggere, solo cambiare.
const gente = { lista: null, attese: [], chiesto: false, occupato: false };
const campoTesto = (segnaposto, etichetta, altro = {}) => h('input', { type: 'text', autocomplete: 'off', autocapitalize: 'none', autocorrect: 'off', spellcheck: 'false', placeholder: segnaposto, 'aria-label': etichetta, ...altro });
const nuova = { nome: campoTesto('Nome', 'Nome della persona', { maxlength: 24, autocapitalize: 'words' }), utente: campoTesto('Nome utente', 'Nome utente', { maxlength: 24 }), password: campoTesto('Password', 'Password', { maxlength: 100 }) };
const perAttesa = new Map();   // i campi delle password di chi aspetta l'account, uno per nome utente

async function chiedi(percorso, opzioni) {
  const r = await fetch(percorso, opzioni);
  const j = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(j.errore || 'Il server non ha risposto bene.');
  return j;
}
async function ricaricaPersone(rifai) {
  try {
    const j = await chiedi('api/persone'); gente.lista = j.persone; gente.attese = j.attese || [];
    // l'avviso nella schermata di oggi ("account da attivare") segue l'elenco: creato l'ultimo, sparisce
    if (io.attese !== gente.attese.length) { aggiornaIo({ attese: gente.attese.length }); return; }
  } catch { /* resta l'elenco di prima */ }
  rifai();
}
async function creaPersona(rifai, nome, utente, campo) {
  const password = campo.value;
  if (password.length < 8) { campo.focus(); avviso('La password deve avere almeno 8 caratteri', 'info'); return; }
  campo.blur();
  gente.occupato = true; rifai();
  try {
    await chiedi('api/persone', { method: 'POST', headers: JSON_, body: JSON.stringify({ nome, utente, password }) });
    campo.value = '';
    avviso(`Account di ${nome} creato`, 'user');
  } catch (e) { avviso(navigator.onLine === false ? 'Sei senza rete' : e.message, 'info'); }
  gente.occupato = false;
  await ricaricaPersone(rifai);
}

// "oggi alle 13:20", "ieri alle 9:05", "3 giorni fa (8 ott)": quando e' successa una cosa, in parole
function quandoFu(v) {
  if (!v) return null;
  const t = new Date(v);
  if (Number.isNaN(t.getTime())) return null;
  const giorni = Math.round((new Date(new Date().toDateString()) - new Date(t.toDateString())) / 86400000);
  const ora = `${t.getHours()}:${String(t.getMinutes()).padStart(2, '0')}`;
  const data = t.toLocaleDateString('it-IT', { day: 'numeric', month: 'short' });
  return giorni <= 0 ? `oggi alle ${ora}` : giorni === 1 ? `ieri alle ${ora}` : giorni < 30 ? `${giorni} giorni fa (${data})` : `il ${t.toLocaleDateString('it-IT', { day: 'numeric', month: 'short', year: 'numeric' })}`;
}

function apriPersona(p, rifai) {
  const campo = campoTesto('Password nuova', 'Password nuova', { maxlength: 100 });
  const con = async (fai) => {
    try { await fai(); } catch (e) { avviso(navigator.onLine === false ? 'Sei senza rete' : e.message, 'info'); }
    ricaricaPersone(rifai);
  };
  const f = foglio(() => [
    h('h2', null, p.nome),
    h('p', { class: 'muto' }, `Nome utente ${p.utente || '–'}`),
    // quando e quanto usa l'app: mai che cosa ci scrive
    h('table', { class: 'tabella' }, h('tbody', null, [
      ['Ultimo accesso', quandoFu(p.vista || p.visto) || 'non è ancora mai entrata'],
      ['Ultima cosa salvata', quandoFu(p.attivo) || 'niente finora'],
      ['Dispositivi collegati', String(p.dispositivi ?? 0)],
      ['Domande iniziali', p.capo ? null : p.domande ? 'fatte' : 'non ancora'],
      ['Dieta', p.piano ? 'scritta su misura' : 'quella dell\'app'],
      ['Giorni segnati nel diario', p.giorni ? `${p.giorni}${p.ultimo_giorno ? `, l'ultimo il ${dataCorta(p.ultimo_giorno)}` : ''}` : 'nessuno'],
      ['Pesate', p.pesate ? `${p.pesate}, l'ultima il ${dataCorta(p.ultima_pesata)}` : 'nessuna'],
      ['Allenamenti segnati', String(p.sedute ?? 0)],
      ['FitAI', (p.ai || []).length ? `acceso (${p.ai.map((x) => NOMI_AI[x] || x).join(', ')})` : 'spento'],
      ['Account creato', quandoFu(p.creato) || '–'],
    ].filter(([, valore]) => valore != null).map(([nome, valore]) => h('tr', null, h('td', null, nome), h('td', null, valore))))),
    h('div', { class: 'campo' }, h('label', null, p.capo ? 'Scegli la tua password' : 'Cambia la password'), campo),
    h('button', { class: 'btn', onclick: () => {
      if (campo.value.length < 8) { campo.focus(); avviso('Almeno 8 caratteri', 'info'); return; }
      const password = campo.value;
      f.chiudi();
      con(async () => { await chiedi(`api/persone/${p.id}/password`, { method: 'POST', headers: JSON_, body: JSON.stringify({ password }) }); avviso(p.capo ? 'Password salvata' : 'Password cambiata', 'key'); });
    } }, icona('key'), 'Salva la password nuova'),
    // l'amministratore entra con il suo nome utente e questa password, oppure con il codice di otto cifre di sempre; non si elimina
    p.capo ? h('p', { class: 'piccolo', style: { textAlign: 'center', lineHeight: 1.45 } }, `Da un dispositivo nuovo entri con il nome utente ${p.utente} e questa password. Il codice di otto cifre che avevi continua a valere.`) : [
      h('p', { class: 'piccolo', style: { textAlign: 'center' } }, 'Quella di prima smette di funzionare. I dispositivi già entrati restano dentro.'),
      h('button', { class: 'btn rosso', onclick: () => conferma({
        titolo: `Eliminare ${p.nome}?`, testo: 'Spariscono il suo account e tutti i suoi dati: diario, pesate, sedute. Non si può annullare.',
        azioni: [{ t: 'Elimina per sempre', tipo: 'rosso', fai: () => { f.chiudi(); con(async () => { await chiedi(`api/persone/${p.id}`, { method: 'DELETE' }); avviso(`${p.nome} eliminata`, 'trash'); }); } }, { t: 'Annulla' }],
      }) }, icona('trash'), 'Elimina la persona'),
    ],
  ]);
}

function persone(rifai) {
  if (!gente.chiesto) { gente.chiesto = true; ricaricaPersone(rifai); }
  const aggiungi = () => {
    const nome = nuova.nome.value.trim(), utente = nuova.utente.value.trim().toLowerCase();
    if (!nome) { nuova.nome.focus(); return; }
    if (!/^[a-z0-9][a-z0-9._-]{2,23}$/.test(utente)) { nuova.utente.focus(); avviso('Nome utente: lettere minuscole, cifre, punti o trattini', 'info'); return; }
    creaPersona(rifai, nome, utente, nuova.password).then(() => { if (!nuova.password.value) { nuova.nome.value = ''; nuova.utente.value = ''; } });
  };
  return h('div', { class: 'card' },
    gente.lista ? h('div', { style: { marginBottom: '8px' } }, gente.lista.map((p) =>
      // anche la riga dell'amministratore si apre: da li' si sceglie la sua password (eliminarsi no)
      h('button', { class: 'voce', onclick: () => apriPersona(p, rifai) },
        h('span', { class: 'faccia' }, p.nome.charAt(0).toUpperCase()),
        h('div', { class: 'cresce' }, h('b', null, p.nome, p.capo ? h('span', { class: 'chip acc', style: { marginLeft: '8px' } }, 'tu') : null),
          h('small', null, p.capo ? `Amministratore · nome utente ${p.utente || ''}` : `${p.utente || ''}${p.visto ? ` · ${p.dispositivi === 1 ? '1 dispositivo' : `${p.dispositivi} dispositivi`}` : ' · non è ancora entrata'}`)),
        icona('chev', 'freccia')))) : h('p', { class: 'piccolo', style: { marginBottom: '12px' } }, 'Carico l\'elenco…'),
    // chi ha gia' la dieta pronta e aspetta solo l'account: nome e nome utente ci sono, manca la password
    gente.attese.map((a) => {
      if (!perAttesa.has(a.utente)) perAttesa.set(a.utente, campoTesto('Scegli la password', `Password di ${a.nome}`, { maxlength: 100 }));
      const campo = perAttesa.get(a.utente);
      return h('div', { class: 'attesa' },
        h('div', { class: 'riga' }, h('span', { class: 'faccia' }, a.nome.charAt(0).toUpperCase()),
          h('div', { class: 'cresce' }, h('b', null, a.nome), h('small', null, `${a.utente} · il piano è già pronto, manca l'account`))),
        h('div', { class: 'riga' }, h('div', { class: 'campo cresce' }, campo),
          h('button', { class: 'btn primo', style: { width: 'auto', padding: '0 18px', height: '56px', flex: 'none' }, disabled: gente.occupato, onclick: () => creaPersona(rifai, a.nome, a.utente, campo) }, 'Crea')));
    }),
    h('div', { class: 'nuova-persona' },
      h('b', null, 'Aggiungi una persona'),
      h('div', { class: 'due-col' }, h('div', { class: 'campo' }, nuova.nome), h('div', { class: 'campo' }, nuova.utente)),
      h('div', { class: 'riga' }, h('div', { class: 'campo cresce' }, nuova.password),
        h('button', { class: 'btn', style: { width: 'auto', padding: '0 18px', height: '56px', flex: 'none' }, disabled: gente.occupato, onclick: aggiungi }, icona('plus'), 'Aggiungi'))),
    h('p', { class: 'piccolo', style: { marginTop: '12px', lineHeight: 1.45 } }, `Ognuno entra da ${location.host} con il suo nome utente e la sua password, e ha il suo account: la sua dieta, i suoi progressi, i suoi dati. Loro non vedono i tuoi; tu dei loro vedi solo quando e quanto usano l'app (tocca un nome), non cosa mangiano né quanto pesano. Al primo accesso l'app fa qualche domanda per adattarsi.`));
}

// ---------- intelligenza artificiale: assistente, foto dei piatti, pareri sui prodotti ----------
// Le chiavi sono dell'account: le scrive chi lo usa e finiscono sul server, che non le restituisce piu'. Qui si sa solo
// se ci sono. I servizi gratuiti sono due: con la chiave di entrambi, quando uno ha finito le richieste risponde l'altro.
const ai = { stato: null, chiesto: false, occupato: false, messaggio: null, aperto: null };
const campoChiave = h('input', { type: 'password', autocomplete: 'off', autocapitalize: 'off', spellcheck: 'false', placeholder: 'Incolla qui la chiave', 'aria-label': 'Chiave del servizio' });
const NOMI_AI = { gemini: 'Gemini di Google', mistral: 'Mistral', anthropic: 'Claude di Anthropic', locale: 'AI sulla VM' };
const collegamento = (indirizzo) => h('a', { href: `https://${indirizzo}`, target: '_blank', rel: 'noopener', style: { color: 'var(--acc)', fontWeight: 650 } }, indirizzo);
// i servizi gratuiti che si accendono dall'app: come si prende la chiave
const GRATIS = {
  gemini: () => [
    h('li', null, h('span', null, 'Apri ', collegamento('aistudio.google.com/apikey'), ' con il tuo account Google.')),
    h('li', null, h('span', null, 'Tocca ', h('b', null, 'Create API key'), ' e copia la chiave che compare.')),
    h('li', null, 'Incollala qui sotto. È gratuita, entro i limiti del piano gratuito di Google.'),
  ],
  mistral: () => [
    h('li', null, h('span', null, 'Apri ', collegamento('console.mistral.ai'), ' e crea un account: chiede il numero di telefono per conferma, non la carta.')),
    h('li', null, h('span', null, 'Apri ', h('b', null, 'API Keys'), ' e tocca ', h('b', null, 'Create new key'), '. Il piano gratuito è già attivo: non c\'è niente da scegliere.')),
    h('li', null, 'Copia la chiave e incollala qui sotto. Con il piano gratuito rispondono i modelli leggeri di Mistral.'),
  ],
};

async function chiamaAi(rifai, percorso, opzioni) {
  ai.occupato = true; ai.messaggio = null; rifai();
  try {
    const j = await chiedi(percorso, opzioni);
    if (j.chiavi) { ai.stato = j; aggiornaIo({ ai: !!(j.fila?.length || j.motore), motore: j.motore, fila: j.fila || [] }); }
    // con Mistral il modello che risponde dipende dal piano: si dice quale
    ai.messaggio = j.ok === false ? j.errore : (percorso.endsWith('prova') || opzioni?.method === 'POST' ? `Funziona${j.modello ? `: risponde ${j.modello}` : ''}.` : null);
    if (j.ok !== false) { campoChiave.value = ''; ai.aperto = null; }
  } catch (e) {
    ai.messaggio = navigator.onLine === false ? 'Sei senza rete.' : e.message;
  }
  ai.occupato = false; rifai();
}

function intelligenza(rifai) {
  if (!ai.chiesto) {
    ai.chiesto = true;
    fetch('api/ai').then((r) => r.json()).then((j) => { ai.stato = j; rifai(); }).catch(() => {});
  }
  const motore = ai.stato ? ai.stato.motore : io.motore;
  // in ordine: chi risponde per primo e chi entra quando il primo e' pieno
  const fila = ai.stato ? (ai.stato.fila || []) : io.fila?.length ? io.fila : (motore ? [motore] : []);
  const mancano = Object.keys(GRATIS).filter((m) => !fila.includes(m));
  const aperto = fila.length ? ai.aperto : (ai.aperto || 'gemini');   // senza chiavi il modulo e' gia' aperto
  const salva = (nome) => {
    const chiave = campoChiave.value.trim();
    if (chiave.length < 20) { campoChiave.focus(); avviso('Incolla la chiave intera', 'info'); return; }
    campoChiave.blur();
    chiamaAi(rifai, 'api/ai/chiave', { method: 'POST', headers: JSON_, body: JSON.stringify({ motore: nome, chiave }) });
  };
  // l'AI che gira sulla VM non ha chiave: c'e' o non c'e', e sta sempre in fondo
  const ruolo = (i) => (fila[i] === 'locale' ? (fila.length < 2 ? 'Gira sul tuo server: gratis e senza limiti, ma lenta' : 'Gira sul tuo server, gratis e senza limiti ma lenta: risponde quando gli altri hanno finito')
    : fila.length < 2 ? 'Risponde a tutte le domande' : i === 0 ? 'Risponde per primo' : 'Di riserva: entra quando chi viene prima ha finito le richieste');
  return h('div', { class: 'card', id: 'carta-ai' },
    h('div', { class: 'riga', style: { marginBottom: '12px' } },
      tessera('sparkle', !!fila.length),
      h('div', { class: 'cresce' }, h('b', null, fila.length ? `Accesa con ${NOMI_AI[fila[0]]}` : 'Spenta'),
        h('div', { class: 'piccolo' }, 'Serve per FitAI, l\'assistente a cui fare domande, per stimare un piatto da una foto e per il parere scritto sui prodotti.'))),
    fila.map((nome, i) => h('div', { class: 'servizio-ai' },
      h('div', { class: 'cresce' }, h('b', null, NOMI_AI[nome]), h('small', null, ruolo(i))),
      h('button', { disabled: ai.occupato, onclick: () => chiamaAi(rifai, 'api/ai/prova', { method: 'POST', headers: JSON_, body: JSON.stringify({ motore: nome }) }) }, 'Prova'),
      nome === 'locale' ? null : h('button', { class: 'rosso', disabled: ai.occupato, 'aria-label': `Togli la chiave di ${NOMI_AI[nome]}`, onclick: () => chiamaAi(rifai, `api/ai/chiave/${nome}`, { method: 'DELETE' }) }, 'Togli'))),
    ai.messaggio ? h('div', { class: 'nota', style: { margin: '10px 0' } }, icona('info'), h('span', null, ai.messaggio)) : null,
    fila.length && !aperto ? mancano.map((nome) => h('button', { class: 'btn basso', style: { marginTop: '10px' }, onclick: () => { ai.aperto = nome; ai.messaggio = null; rifai(); } },
      icona('plus'), `Aggiungi ${NOMI_AI[nome]} di riserva, gratis`)) : null,
    aperto && mancano.includes(aperto) && fila.length
      ? h('p', { class: 'piccolo', style: { margin: '14px 0 12px', lineHeight: 1.45 } }, `I servizi gratuiti hanno un tetto di richieste. Con anche la chiave di ${NOMI_AI[aperto]}, quando ${NOMI_AI[fila[0]]} dice che per ora basta risponde l'altro, senza che tu debba fare niente.`) : null,
    aperto && mancano.includes(aperto) ? h('ol', { class: 'passi', style: { marginBottom: '14px' } }, GRATIS[aperto]()) : null,
    aperto && mancano.includes(aperto) ? h('div', { class: 'campo', style: { marginBottom: '10px' } }, campoChiave) : null,
    aperto && mancano.includes(aperto) ? h('button', { class: 'btn basso', disabled: ai.occupato, onclick: () => salva(aperto) }, icona('check'), ai.occupato ? 'Provo la chiave…' : 'Salva e prova') : null,
    aperto && mancano.includes(aperto) && !fila.length
      ? h('button', { class: 'testo-link', onclick: () => { ai.aperto = aperto === 'gemini' ? 'mistral' : 'gemini'; ai.messaggio = null; rifai(); } }, aperto === 'gemini' ? 'Preferisco usare Mistral' : 'Preferisco usare Gemini') : null,
    h('p', { class: 'piccolo', style: { marginTop: '12px', lineHeight: 1.45 } }, 'Le chiavi valgono solo per il tuo account: chi altro usa l\'app non le vede e non le consuma. I piani gratuiti hanno un tetto di richieste, e chi offre il servizio può usare foto e testi che gli mandi per migliorare i suoi prodotti.'));
}

// ---------- notifiche sul telefono ----------
const nt = { stato: null, promemoria: true, occupato: false, chiesto: false };
function notifiche(rifai) {
  if (!nt.chiesto) { nt.chiesto = true; statoNotifiche().then((s) => { nt.stato = s.stato; nt.promemoria = s.promemoria !== false; rifai(); }); }
  const con = async (fai, bene) => {
    nt.occupato = true; rifai();
    try { const j = await fai(); if (bene) avviso(typeof bene === 'function' ? bene(j) : bene, 'check'); } catch (e) { avviso(navigator.onLine === false ? 'Sei senza rete' : e.message, 'info'); }
    const s = await statoNotifiche();
    nt.stato = s.stato; nt.promemoria = s.promemoria !== false; nt.occupato = false; rifai();
  };
  const testa = (titolo, sotto) => h('div', { class: 'riga', style: { marginBottom: '12px' } },
    tessera('clock', nt.stato === 'attive'), h('div', { class: 'cresce' }, h('b', null, titolo), h('div', { class: 'piccolo' }, sotto)));
  const cosa = 'Ti avviso quando FitAI ha risposto e l\'app è chiusa, e se a pranzo o a cena non hai segnato il pasto.';
  if (!possibili() || nt.stato === 'no') {
    return h('div', { class: 'card' }, testa('Non disponibili qui', iphoneFuoriDallaHome()
      ? 'Sull\'iPhone le notifiche arrivano solo aprendo EverFit dall\'icona sulla schermata Home: in Safari tocca Condividi, poi «Aggiungi alla schermata Home», e torna qui da lì.'
      : 'Questo browser non sa ricevere le notifiche di EverFit.'));
  }
  if (nt.stato === 'negate') return h('div', { class: 'card' }, testa('Bloccate', 'Le hai bloccate dal telefono: si riattivano da Impostazioni → Notifiche → EverFit.'));
  if (nt.stato !== 'attive') {
    return h('div', { class: 'card' }, testa('Spente', cosa),
      h('button', { class: 'btn primo', disabled: nt.occupato || nt.stato == null, onclick: () => con(attivaNotifiche, 'Notifiche attive') }, icona('check'), nt.occupato ? 'Un attimo…' : 'Attiva le notifiche'));
  }
  return h('div', { class: 'card' }, testa('Attive su questo telefono', cosa),
    h('div', { class: 'riga', style: { padding: '6px 0 12px' } },
      h('div', { class: 'cresce' }, h('b', null, 'Promemoria di pranzo e cena'), h('div', { class: 'piccolo' }, 'Tre quarti d\'ora dopo l\'ora del pasto, solo se non l\'hai segnato.')),
      interruttore(nt.promemoria, () => { if (!nt.occupato) con(() => promemoriaPasti(!nt.promemoria)); }, 'Promemoria di pranzo e cena')),
    h('div', { class: 'due-col' },
      h('button', { class: 'btn basso', disabled: nt.occupato, onclick: () => con(provaNotifica, (j) => (j.ok ? 'Mandata: arriva tra qualche secondo' : 'Non è partita: riprova')) }, icona('send'), 'Prova'),
      h('button', { class: 'btn basso rosso', disabled: nt.occupato, onclick: () => con(spegniNotifiche, 'Notifiche spente') }, 'Disattiva')));
}

// ---------- passi dall'iPhone ----------
// L'app Salute dell'iPhone non si puo' leggere da una pagina web: i passi li manda un comando dell'app Comandi, a
// orari fissi (un'automazione), con un codice suo che vale solo per quello (server.py, _passi_dal_comando). Il codice
// si vede una volta sola, appena creato: se si perde se ne fa uno nuovo e quello vecchio smette di funzionare.
const ps = { letto: 0, stato: null, codice: null, occupato: false, istruzioni: false };
function passi(rifai) {
  const leggi = () => chiedi('api/passi/codice').then((j) => { ps.stato = j; rifai(); }).catch(() => {});
  // si riguarda ogni volta che la scheda si ridisegna (non piu' di una volta ogni 10 secondi): dopo aver provato il
  // comando sull'iPhone e tornati qui, l'ultimo invio deve comparire senza ricaricare l'app
  if (Date.now() - ps.letto > 10000) { ps.letto = Date.now(); leggi(); }
  const con = async (fai) => {
    ps.occupato = true; rifai();
    try { await fai(); } catch (e) { avviso(navigator.onLine === false ? 'Sei senza rete' : e.message, 'info'); }
    ps.occupato = false; await leggi();
  };
  const crea = () => con(async () => { ps.codice = (await chiedi('api/passi/codice', { method: 'POST' })).codice; ps.istruzioni = true; });
  const ultimo = ps.stato?.ultimo;
  const indirizzo = `${location.origin}/api/passi`;
  const copia = (testo, cosa) => {
    navigator.clipboard?.writeText(testo).then(() => avviso(`${cosa} copiato`, 'check'), () => avviso('Tienilo premuto per copiarlo', 'info'));
  };
  const passo = (...parti) => h('li', null, h('span', null, ...parti));
  const istruzioni = h('ol', { class: 'passi passi-comando' },
    passo('Apri l\'app ', h('b', null, 'Comandi'), ' e tocca ', h('b', null, '+'), ' per un comando nuovo. Chiamalo «Passi EverFit».'),
    passo('Aggiungi l\'azione ', h('b', null, 'Trova campioni di salute'), '. Tipo: ', h('b', null, 'Passi'), '; filtro «Data di inizio» ',
      h('b', null, 'è oggi'), '; «Raggruppa per» ', h('b', null, 'Giorno'), ' (così i passi di iPhone e Watch non si contano due volte).'),
    passo('Aggiungi l\'azione ', h('b', null, 'Ottieni contenuto dell\'URL'), ' e incolla l\'indirizzo qui sotto. Apri le altre opzioni: metodo ',
      h('b', null, 'POST'), ', corpo della richiesta ', h('b', null, 'JSON'), '.'),
    passo('Nel JSON aggiungi due campi Testo: ', h('b', null, 'codice'), ' con il codice qui sotto, e ', h('b', null, 'passi'),
      ': tocca il valore, scegli la variabile «Campioni di salute», toccala di nuovo e scegli ', h('b', null, 'Valore'), '.'),
    passo('Tocca ▶︎ per provarlo: la prima volta l\'iPhone chiede di leggere i passi da Salute, rispondi Consenti. Qui deve comparire «Ultimo invio».'),
    passo('Per farlo andare da solo: scheda ', h('b', null, 'Automazione'), ', ', h('b', null, '+'), ', ', h('b', null, 'Ora del giorno'),
      ' (per esempio 22:00, ogni giorno), ', h('b', null, 'Esegui immediatamente'), ', e scegli «Passi EverFit». Per vederli anche di giorno aggiungi altre ore.'));
  const testa = h('div', { class: 'riga', style: { marginBottom: '12px' } },
    tessera('walk', !!ps.stato?.attivo),
    h('div', { class: 'cresce' },
      h('b', null, ps.stato == null ? 'Passi dall\'iPhone' : ps.stato.attivo ? (ultimo ? 'Collegati' : 'Codice pronto, aspetto i primi passi') : 'Non collegati'),
      h('div', { class: 'piccolo' }, ultimo
        ? `Ultimo invio ${quandoFu(ultimo.aggiornato * 1000)}: ${Number(ultimo.passi).toLocaleString('it-IT')} passi del ${dataCorta(ultimo.giorno)}.`
        : 'I passi che conta l\'app Salute, nella schermata di oggi e nel movimento. Li manda un comando dell\'app Comandi.')));
  return h('div', { class: 'card' }, testa,
    ps.codice ? [
      h('div', { class: 'piccolo', style: { marginBottom: '6px' } }, 'Il codice del comando (si vede solo adesso):'),
      h('div', { class: 'codice-comando' }, h('code', null, ps.codice), h('button', { class: 'btn basso', onclick: () => copia(ps.codice, 'Codice') }, icona('copy'), 'Copia')),
      h('div', { class: 'piccolo', style: { margin: '10px 0 6px' } }, 'L\'indirizzo:'),
      h('div', { class: 'codice-comando' }, h('code', null, indirizzo), h('button', { class: 'btn basso', onclick: () => copia(indirizzo, 'Indirizzo') }, icona('copy'), 'Copia')),
    ] : null,
    ps.codice || ps.istruzioni ? istruzioni : null,
    !ps.stato?.attivo
      ? h('button', { class: 'btn primo', disabled: ps.occupato || ps.stato == null, onclick: crea }, icona('walk'), ps.occupato ? 'Un attimo…' : 'Collega i passi')
      : h('div', { class: 'due-col' },
        ps.codice || ps.istruzioni ? null : h('button', { class: 'btn basso', onclick: () => { ps.istruzioni = true; rifai(); } }, 'Come si fa'),
        h('button', { class: 'btn basso', disabled: ps.occupato, onclick: () => conferma({
          titolo: 'Un codice nuovo?', testo: 'Quello di adesso smette di funzionare: andrà messo il nuovo nel comando dell\'iPhone.',
          azioni: [{ t: 'Fai il codice nuovo', fai: crea }, { t: 'Annulla' }],
        }) }, 'Nuovo codice'),
        ps.codice || ps.istruzioni ? h('button', { class: 'btn basso rosso', disabled: ps.occupato, onclick: () => conferma({
          titolo: 'Scollegare i passi?', testo: 'Il comando dell\'iPhone non potrà più mandarli. Quelli già arrivati restano.',
          azioni: [{ t: 'Scollega', tipo: 'rosso', fai: () => con(async () => { await chiedi('api/passi/codice', { method: 'DELETE' }); ps.codice = null; ps.istruzioni = false; }) }, { t: 'Annulla' }],
        }) }, 'Scollega') : null));
}

const STATI = { ok: 'Copia sul server aggiornata', offline: 'Senza rete: i dati restano sul telefono', assente: 'Server non raggiungibile: i dati restano sul telefono', locale: 'Controllo la copia sul server' };

function dati() {
  const file = h('input', { type: 'file', accept: 'application/json,.json', style: { display: 'none' }, onchange: async (e) => {
    const f = e.target.files[0];
    if (!f) return;
    try { importa(JSON.parse(await f.text())); avviso('Dati importati'); } catch { avviso('File non valido', 'info'); }
    e.target.value = '';
  } });
  return h('div', { class: 'card' },
    h('div', { class: 'riga', style: { marginBottom: '14px' } },
      tessera('cloud'),
      h('div', { class: 'cresce' }, h('b', { 'data-sync': '' }, STATI[sync.stato]),
        h('div', { class: 'piccolo' }, `Sedute ${S.sedute.length} · pesate ${M.pesate.length} · giorni segnati ${Object.keys(S.giorni).length}`))),
    h('div', { class: 'due-col' },
      h('button', { class: 'btn basso', onclick: () => {
        const url = URL.createObjectURL(new Blob([esporta()], { type: 'application/json' }));
        const a = h('a', { href: url, download: `fit-${oggi()}.json` });
        document.body.append(a); a.click(); a.remove();
        setTimeout(() => URL.revokeObjectURL(url), 2000);
      } }, icona('down'), 'Esporta'),
      h('button', { class: 'btn basso', onclick: () => file.click() }, icona('up'), 'Importa')),
    file,
    h('div', { class: 'fra', style: { marginTop: '16px' } },
      h('div', null, h('b', null, 'Suono a fine recupero'), h('div', { class: 'piccolo' }, 'Due bip quando puoi ripartire.')),
      h('div', { class: 'seg mini', style: { width: '112px', flex: 'none' } },
        h('button', { class: S.opzioni.suono !== false ? 'on' : '', onclick: () => aggiorna((s) => { s.opzioni.suono = true; }) }, 'Sì'),
        h('button', { class: S.opzioni.suono === false ? 'on' : '', onclick: () => aggiorna((s) => { s.opzioni.suono = false; }) }, 'No'))),
    h('button', { class: 'btn basso rosso', style: { marginTop: '16px' }, onclick: () => conferma({
      titolo: 'Azzerare tutto?', testo: 'Spariscono pasti spuntati, diario, sedute e carichi. Pesate e misure restano nel database.',
      azioni: [{ t: 'Azzera', tipo: 'rosso', fai: () => { azzera(); avviso('Dati azzerati', 'trash'); } }, { t: 'Annulla' }],
    }) }, icona('trash'), 'Azzera i miei dati'));
}

export function aggiornaSync() {
  const el = document.querySelector('[data-sync]');
  if (el) el.textContent = STATI[sync.stato];
}

export function vistaAltro(_, rifai) {
  return [
    h('div', { class: 'top' }, h('div', null, h('div', { class: 'sopra' }, `${io.nome || P.profilo.nome} · ${P.profilo.eta} anni`), h('h1', null, 'Il tuo piano'))),
    profilo(),
    formaDieta(),
    P.puntiCarenti?.length ? [h('div', { class: 'sez' }, h('h2', null, 'Punti carenti'), h('span', null, 'Tocca per vederli')), carenti(rifai)] : null,
    P.guida?.length ? [h('div', { class: 'sez' }, h('h2', null, 'Guida')), ...guida()] : null,
    ...(installa() || []),
    h('div', { class: 'sez' }, h('h2', null, 'La tua Home'), h('span', null, 'Cosa vedi ogni giorno')),
    casa(),
    h('div', { class: 'sez' }, h('h2', null, 'Account')),
    account(rifai),
    // solo l'amministratore: gli altri non sanno nemmeno che questa sezione esiste (e il server non gliela darebbe)
    io.capo ? [h('div', { class: 'sez', id: 'carta-persone' }, h('h2', null, 'Persone'), h('span', null, 'Chi usa l\'app')), persone(rifai)] : null,
    h('div', { class: 'sez' }, h('h2', null, 'Intelligenza artificiale')),
    intelligenza(rifai),
    h('div', { class: 'sez' }, h('h2', null, 'Passi dall\'iPhone'), h('span', null, 'Dall\'app Salute')),
    passi(rifai),
    h('div', { class: 'sez' }, h('h2', null, 'Notifiche')),
    notifiche(rifai),
    h('div', { class: 'sez' }, h('h2', null, 'I tuoi dati')),
    dati(),
    h('p', { class: 'piccolo', style: { textAlign: 'center', padding: '6px 12px 0', lineHeight: 1.5 } }, P.crediti.piatti, h('br'), P.crediti.esercizi, h('br'), `Piano ${P.versione}`),
  ];
}
