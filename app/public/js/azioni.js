// Quello che l'assistente puo' fare nell'app al posto della persona: segnare un cibo nel diario, spuntare un pasto,
// aggiungere acqua o movimento, cambiare un piatto del piano, crearne uno nuovo. E, con l'azione "modifica", tutto il
// resto: riscrive direttamente i dati della persona (diario, sedute, opzioni, profilo) e la sua versione del piano
// (S.mie: quantita' dei piatti, obiettivi, schede, giorni di allenamento, pasti in piu' o in meno).
//
// Il server manda azioni gia' ripulite nella forma (server/assistente.py). Qui si controlla che abbiano senso per il
// piano di questa persona (quel pasto esiste? quella ricetta e' del tipo giusto?), le si esegue con le stesse funzioni
// che usano le schermate, e per ognuna si tiene quello che serve ad annullarla: l'esito finisce nella conversazione
// ({ok, t: cosa e' successo, u: come tornare indietro}) e la chat lo mostra con il tasto "Annulla".

import { oggi, daIso, giornoSett, piuGiorni, intero, dec, dataCorta } from './dom.js';
import {
  P, S, aggiorna, giorno, pastiDelGiorno, ingredienti, tipoGiorno, macro, FUORI_PASTO,
  aggiungiExtra, togliExtra, bevi, togliBevuta, aggiungiAttivita, togliAttivita, ATTIVITA,
  segnaFatto, cambiaPasti, rimettiPasti, vaNelPasto, aggiungiPiatto, togliPiatto, rimettiPiatto, nuovoId,
  modificaStato, annullaModifica, mangiatiSolo, impostaDosi, rimettiDosi, cambiaVoce, rimettiVoce, vocePer,
} from './store.js';
import { M, salvaPesata, salvaCirconferenze, nuovaPesata, eliminaMisura } from './misure.js';
import { tema, cambiaTema } from './tema.js';

const fotoDi = (r) => (r ? r.foto || (r.img ? `img/food/${r.img}.jpg` : null) : null);
const kcalDi = (rid, tipo) => intero(macro(rid, tipo).kcal);
const nomiGiorni = (giorni) => giorni.map((wd) => P.giorni[wd].toLowerCase()).join(', ');
const nomePasto = (mom) => (mom === FUORI_PASTO ? 'fuori pasto' : (P.momenti[mom]?.n || mom).toLowerCase());

// ---------- quello che l'assistente deve sapere per poter agire: gli identificativi veri ----------
// La parte che non cambia quasi mai: i cibi, le ricette con i loro ingredienti e i pasti, per identificativo.
// Va in ogni domanda, quindi e' asciutta. I pasti di oggi li scrive il riassunto (views/assistente.js).
export function catalogo() {
  const r = [];
  // i valori stanno qui perche' i conti li faccia con questi: senza andava a memoria (28/10/2026: 310 kcal per una colazione da 260)
  const pezzo = (c) => (c.pz ? `, ${c.pz} g` : '');
  r.push(`Cibi (identificativo: nome kcal/proteine/carboidrati/grassi per 100 g, poi quanto pesa un pezzo): ${Object.entries(P.cibi).map(([id, c]) => `${id}: ${c.n} ${c.kcal}/${c.p}/${c.c}/${c.f}${pezzo(c)}`).join('; ')}.`);
  const grammi = ([, g, gp]) => (g === gp ? `${g}` : `${g}/${gp}`);
  r.push('Ricette (identificativo: nome; tipo; kcal a riposo/in palestra; ingredienti: cibo e grammi a riposo/in palestra):');
  for (const [id, x] of Object.entries(P.ricette)) {
    if (id === 'shake') continue;
    r.push(`- ${id}: ${x.n}; ${x.tipo}${x.per ? ` solo ${x.per.join('/')}` : ''}; ${intero(macro(id, 'rest').kcal)}/${intero(macro(id, 'train').kcal)}`
      + (Array.isArray(x.ing) && x.ing.length ? `; ${x.ing.map((i) => `${i[0]} ${grammi(i)}`).join(', ')}` : ''));
  }
  // un pasto con `con` (il caffe' della colazione) ha la sua spunta ma si chiama come il pasto a cui e' attaccato
  r.push(`Pasti (identificativo = nome, tipo): ${Object.entries(P.momenti).map(([k, m]) => `${k} = ${m.con ? `${m.tipo} insieme a ${m.n.toLowerCase()}` : m.n}, ${m.tipo}`).join('; ')}.`);
  return r.join('\n');
}

// La settimana com'e' adesso, con i cambi gia' fatti: cambia quando si sposta un piatto.
export function settimanaPiano() {
  const d = oggi(), lun = piuGiorni(d, -giornoSett(daIso(d)));
  const r = ['Settimana, con i cambi gia\' fatti (giorno: pasto=ricetta):'];
  for (let i = 0; i < 7; i++) {
    const g = piuGiorni(lun, i);
    r.push(`- ${i} ${P.giorni[i].toLowerCase()}${tipoGiorno(g) === 'train' ? ' (palestra)' : ''}: ${pastiDelGiorno(g).filter((x) => x.mom !== 'post' && !x.con).map((x) => `${x.mom}=${x.rid}${x.soloOggi ? ' (solo quel giorno)' : x.cambiato ? '*' : ''}`).join(', ')}`);
  }
  return r.join('\n');
}

// Le voci del diario che si possono togliere (oggi e ieri): cambiano spesso, stanno con le cose di adesso.
export function vociDiario() {
  const d = oggi();
  const r = [];
  for (const [quando, g] of [['oggi', d], ['ieri', piuGiorni(d, -1)]]) {
    const voci = S.giorni[g]?.extra || [];
    if (voci.length) r.push(`Voci del diario di ${quando} (identificativo: cosa): ${voci.map((e) => `${e.id}: ${e.n}, ${nomePasto(e.mom)}, ${intero(e.kcal)} kcal`).join('; ')}.`);
  }
  return r.join('\n');
}

// Gli identificativi veri, in elenchi: il server ci chiude lo schema dell'AI che gira sulla VM, che cosi' non puo'
// scriverne uno che non esiste.
export function idsAssistente() {
  const d = oggi();
  return {
    giorni: [d, piuGiorni(d, -1)],
    pasti: Object.keys(P.momenti),
    ricette: Object.keys(P.ricette).filter((id) => id !== 'shake'),
    cibi: Object.keys(P.cibi),
    voci: [d, piuGiorni(d, -1)].flatMap((g) => (S.giorni[g]?.extra || []).map((e) => e.id)),
  };
}

// Tutti i dati della persona e tutto il suo piano, in JSON: e' da qui che l'assistente prende i percorsi per l'azione
// "modifica" (store.js, modificaStato). Dei giorni, delle sedute e delle attivita' passano solo gli ultimi.
// Pesa parecchio (migliaia di token): va solo nelle domande che ne hanno bisogno (il livello "tutto").
export function mondo() {
  const d = oggi();
  const crea = (giorni, sedute) => {
    const da = piuGiorni(d, -giorni);
    const stato = {
      giorni: Object.fromEntries(Object.entries(S.giorni).filter(([g]) => g >= da).sort(([a], [b]) => a.localeCompare(b))
        .map(([g, x]) => [g, { ...x, ...(x.extra ? { extra: x.extra.map(({ img, ...e }) => e) } : {}) }])),
      cambi: S.cambi, spesa: S.spesa,
      sedute: S.sedute.slice(-sedute).map((x) => ({ id: x.id, d: x.d, w: x.w, voci: x.voci.map((v) => ({ es: v.es, serie: v.serie.map((q) => ({ kg: q.kg, rip: q.rip })) })) })),
      attivita: S.attivita.filter((a) => a.d >= piuGiorni(d, -14)),
      opzioni: S.opzioni, profilo: S.profilo || null, mie: S.mie,
    };
    const piano = {
      obiettivi: P.obiettivi, momenti: P.momenti,
      settimana: P.settimana.map((g) => ({ tipo: g.tipo, scheda: g.scheda || null, pasti: g.pasti, ...(g.ob ? { ob: g.ob } : {}) })),
      ricette: Object.fromEntries(Object.entries(P.ricette).map(([id, x]) => [id, {
        n: x.n, tipo: x.tipo, ing: x.ing, min: x.min, ...(x.per ? { per: x.per } : {}), ...(x.libero ? { libero: true, stima: x.stima } : {}),
      }])),
      cibi: Object.fromEntries(Object.entries(P.cibi).map(([id, c]) => [id, { n: c.n, kcal: c.kcal, p: c.p, c: c.c, f: c.f, ...(c.pz ? { pz: c.pz } : {}) }])),
      schede: Object.fromEntries(Object.entries(P.schede).map(([w, sc]) => [w, { n: sc.n, fuoco: sc.fuoco, ...(sc.casa ? { casa: true } : {}), es: sc.es.map((e) => e.slice(0, 4)) }])),
      esercizi: Object.fromEntries(Object.entries(P.esercizi).map(([id, e]) => [id, e.n])),
      aspetto: tema(),
    };
    return `STATO (JSON: e' quello che puoi modificare, i percorsi partono da qui; di giorni, sedute e attivita' ci sono solo gli ultimi)\n${JSON.stringify(stato)}\n\n`
      + `PIANO (JSON, sola lettura: per cambiarlo si scrive in stato.mie)\n${JSON.stringify(piano)}`;
  };
  const largo = crea(4, 3);
  return largo.length < 30000 ? largo : crea(2, 1);   // un diario molto pieno: si accorcia la storia, non il piano
}

// ---------- eseguire ----------
// Il giorno a cui si riferisce un'azione: vuoto = oggi. Lontano da oggi non si tocca niente.
function giornoDi(a) {
  const d = a.giorno || oggi();
  return /^\d{4}-\d{2}-\d{2}$/.test(d) && d >= piuGiorni(oggi(), -60) && d <= piuGiorni(oggi(), 1) ? d : null;
}
const quando = (d) => (d === oggi() ? '' : d === piuGiorni(oggi(), -1) ? ' · ieri' : ` · ${dataCorta(d)}`);
const no = (t) => ({ ok: false, t, u: null });

const FARE = {
  mangiato(a) {
    const d = giornoDi(a);
    if (!d) return no(`Non segno "${a.nome}": il giorno non mi torna`);
    const pasto = pastiDelGiorno(d).find((x) => x.mom === a.pasto);
    const mom = pasto ? a.pasto : FUORI_PASTO;   // un pasto che quel giorno non c'e' finisce tra i fuori pasto
    let via = [];
    if (pasto && a.al_posto === 'tutto') via = ['*'];
    else if (pasto && a.al_posto === 'parte') {
      const previsti = new Set(ingredienti(pasto.rid, pasto.tipo).map((i) => i.id));
      via = (a.tolti || []).filter((id) => previsti.has(id));
    }
    const img = fotoDi(P.ricette[a.foto_di]);
    const era = pasto ? pasto.fatto : null;
    const id = aggiungiExtra(d, mom, { n: a.nome, q: a.quantita || '', g: null, kcal: a.kcal, p: a.p, c: a.c, f: a.f, fonte: 'ai', stima: true, ...(img ? { img } : {}) }, via);
    const come = !pasto ? '' : via.includes('*') ? `, al posto di ${pasto.r.n.toLowerCase()}`
      : via.length ? `, al posto di ${via.map((x) => P.cibi[x].n.toLowerCase()).join(', ')}` : ', in più';
    return { ok: true, t: `Nel diario: ${a.nome}${a.quantita ? ` (${a.quantita})` : ''}, ${intero(a.kcal)} kcal · ${nomePasto(mom)}${come}${quando(d)}`, u: { k: 'voce', d, id, mom, era } };
  },

  pasto_fatto(a) {
    const d = giornoDi(a);
    const pasto = d && pastiDelGiorno(d).find((x) => x.mom === a.pasto);
    if (!pasto) return no('Quel pasto in quel giorno non c\'è');
    // mangiato solo in parte: `solo` sono gli ingredienti mangiati, `senza` quelli lasciati nel piatto
    const nelPiatto = ingredienti(pasto.rid, pasto.tipo, pasto.dosi).filter((i) => !pasto.tolti.has(i.id));
    const ids = nelPiatto.map((i) => i.id);
    const solo = (a.solo || []).filter((id) => ids.includes(id));
    const senza = new Set([...(a.senza || []).filter((id) => ids.includes(id)), ...(solo.length ? ids.filter((id) => !solo.includes(id)) : [])]);
    if (a.fatto && senza.size && senza.size < ids.length) {
      const prima = mangiatiSolo(d, a.pasto, [...senza], true);
      const presi = nelPiatto.filter((i) => !senza.has(i.id)).map((i) => i.n.toLowerCase());
      return { ok: true, t: `${pasto.nome}: segnato, solo ${presi.join(', ')} (${pasto.r.n})${quando(d)}`, u: { k: 'parte', d, mom: a.pasto, prima } };
    }
    const prima = mangiatiSolo(d, a.pasto, null, a.fatto);
    return { ok: true, t: `${pasto.nome}: ${a.fatto ? 'segnato come mangiato' : 'tolta la spunta'} (${pasto.r.n})${quando(d)}`, u: { k: 'parte', d, mom: a.pasto, prima } };
  },

  // I grammi veri di un ingrediente del piatto previsto, solo per quel giorno: l'ingrediente resta nel piatto.
  dose(a) {
    const d = giornoDi(a);
    const pasto = d && pastiDelGiorno(d).find((x) => x.mom === a.pasto);
    if (!pasto) return no('Quel pasto in quel giorno non c\'è');
    const riga = (P.ricette[pasto.rid].ing || []).find((x) => x[0] === a.cibo);
    if (!riga || pasto.tolti.has(a.cibo)) return no(`${P.cibi[a.cibo]?.n || 'Quel cibo'} non c'è in ${pasto.r.n.toLowerCase()}`);
    const piano = riga[pasto.tipo === 'train' ? 2 : 1];
    const nome = P.cibi[a.cibo].n.toLowerCase();
    const prima = impostaDosi(d, a.pasto, { [a.cibo]: a.grammi === piano ? null : a.grammi });
    return { ok: true, t: `${pasto.nome}: ${nome} ${intero(a.grammi)} g${a.grammi === piano ? ' (come nel piano)' : ` invece di ${intero(piano)} g`}${quando(d) || ' · solo oggi'}`,
      u: { k: 'dosi', d, mom: a.pasto, prima } };
  },

  // Quanto ne ha mangiato davvero di una cosa gia' segnata: la stessa voce con la quantita' nuova, i valori seguono.
  cambia_voce(a) {
    const giorni = [...new Set([giornoDi(a), oggi(), piuGiorni(oggi(), -1)].filter(Boolean))];
    const d = giorni.find((g) => (S.giorni[g]?.extra || []).some((e) => e.id === a.voce));
    const voce = d && S.giorni[d].extra.find((e) => e.id === a.voce);
    if (!voce) return no('Non trovo quella voce nel diario');
    const n = parseFloat(String(a.quantita || '').replace(',', '.'));
    if (!(n > 0)) return no(`Non capisco la quantità nuova di ${voce.n}`);
    const campi = vocePer(voce, n);
    // se ha dato i valori li usa (un cibo diverso pesa diverso); altrimenti quelli di prima in proporzione
    if (a.kcal != null) Object.assign(campi, { kcal: Math.round(a.kcal), p: a.p ?? campi.p, c: a.c ?? campi.c, f: a.f ?? campi.f });
    const prima = cambiaVoce(d, voce.id, campi);   // (la voce cambia sul posto: com'era sta in `prima`)
    return { ok: true, t: `Nel diario: ${prima.n} ora ${campi.q}, ${intero(campi.kcal)} kcal (prima ${prima.q || '1 porzione'})${quando(d)}`, u: { k: 'rivoce', d, prima } };
  },

  togli_voce(a) {
    // se il giorno non c'e' o non e' quello giusto, la voce si cerca tra oggi e ieri
    const giorni = [...new Set([giornoDi(a), oggi(), piuGiorni(oggi(), -1)].filter(Boolean))];
    const d = giorni.find((g) => (S.giorni[g]?.extra || []).some((e) => e.id === a.voce));
    const voce = d && S.giorni[d].extra.find((e) => e.id === a.voce);
    if (!voce) return no('Non trovo quella voce nel diario');
    togliExtra(d, voce.id);
    return { ok: true, t: `Tolto dal diario: ${voce.n}, ${intero(voce.kcal)} kcal${quando(d)}`, u: { k: 'rimetti', d, voce } };
  },

  acqua(a) {
    const d = giornoDi(a);
    if (!d) return no('Il giorno non mi torna');
    bevi(d, a.ml);
    return { ok: true, t: `Acqua: +${intero(a.ml)} ml${quando(d)}`, u: { k: 'acqua', d, ml: a.ml } };
  },

  movimento(a) {
    const d = giornoDi(a);
    if (!d) return no('Il giorno non mi torna');
    const tipo = ATTIVITA[a.attivita] ? a.attivita : 'altro';
    const id = aggiungiAttivita({ tipo, min: a.minuti, d });
    return { ok: true, t: `${ATTIVITA[tipo].n}: ${intero(a.minuti)} minuti${quando(d)}`, u: { k: 'attivita', id } };
  },

  peso(a) {
    const riga = nuovaPesata({ peso: a.kg, fonte: 'manuale', nota: 'Detto all\'assistente' });
    salvaPesata(riga);   // va sul server per conto suo; senza rete resta in coda
    return { ok: true, t: `Peso di oggi: ${dec(a.kg, 2)} kg`, u: { k: 'pesata', quando: riga.quando } };
  },

  cambia_pasto(a) {
    if (!vaNelPasto(a.ricetta, a.pasto)) return no(P.ricette[a.ricetta] ? `${P.ricette[a.ricetta].n} non è un piatto da ${nomePasto(a.pasto)}` : 'Non trovo quella ricetta');
    const giorni = a.giorni.filter((wd) => P.settimana[wd]?.pasti?.[a.pasto]);
    if (!giorni.length) return no('In quei giorni quel pasto non c\'è');
    const prima = cambiaPasti(giorni, a.pasto, a.ricetta);
    const r = P.ricette[a.ricetta];
    return { ok: true, t: `${P.momenti[a.pasto].n} di ${nomiGiorni(giorni)}: ora c'è ${r.n} (${kcalDi(a.ricetta, 'rest')} kcal)`, u: { k: 'cambi', mom: a.pasto, prima } };
  },

  ripristina_pasto(a) {
    const giorni = a.giorni.filter((wd) => S.cambi[wd]?.[a.pasto]);
    if (!P.momenti[a.pasto] || !giorni.length) return no('In quei giorni quel pasto è già quello del piano');
    const prima = cambiaPasti(giorni, a.pasto, null);
    return { ok: true, t: `${P.momenti[a.pasto].n} di ${nomiGiorni(giorni)}: tornato il piatto del piano`, u: { k: 'cambi', mom: a.pasto, prima } };
  },

  nuovo_piatto(a) {
    const momento = P.momenti[a.pasto];
    if (!momento || a.pasto === 'post') return no('Non so in quale pasto mettere il piatto nuovo');
    const cibi = {}, ing = [];
    for (const i of a.ingredienti) {
      let id = i.cibo && P.cibi[i.cibo] ? i.cibo : null;
      if (!id && i.nome) {
        // un cibo che nel catalogo non c'e': entra tra quelli della persona, con i valori che ha dato l'assistente
        id = nuovoId(i.nome, (x) => !!P.cibi[x] || !!cibi[x]);
        cibi[id] = { n: i.nome, kcal: i.kcal, p: i.p, c: i.c, f: i.f, rep: i.reparto || 'Dispensa', mio: true };
      }
      if (!id) return no(`Non creo "${a.nome}": c'è un ingrediente che non conosco`);
      ing.push([id, Math.round(i.grammi), Math.round(i.grammi_palestra || i.grammi)]);
    }
    // la foto e' quella del piatto che gli somiglia di piu'; se manca, quella di un piatto dello stesso pasto
    const simile = [P.ricette[a.foto_di], ...Object.values(P.ricette).filter((x) => x.tipo === momento.tipo)].find((x) => x && (x.img || x.foto));
    const ricetta = {
      n: a.nome, tipo: momento.tipo, come: 'Ricetta tua', min: Math.round(a.minuti) || 15, ing,
      passi: a.passi?.length ? a.passi : ['Cuoci gli ingredienti come fai di solito e mettili insieme.'],
      ...(simile?.img ? { img: simile.img } : simile?.foto ? { foto: simile.foto } : {}),
    };
    const rid = aggiungiPiatto(ricetta, cibi);
    const giorni = (a.giorni || []).filter((wd) => P.settimana[wd]?.pasti?.[a.pasto]);
    const prima = giorni.length ? cambiaPasti(giorni, a.pasto, rid) : {};
    return {
      ok: true, u: { k: 'piatto', rid, mom: a.pasto, prima },
      t: `Piatto nuovo: ${a.nome}, ${kcalDi(rid, 'rest')} kcal e ${intero(macro(rid, 'rest').p)} g di proteine${giorni.length ? ` · messo a ${nomePasto(a.pasto)} di ${nomiGiorni(giorni)}` : ' · lo trovi tra le alternative'}`,
    };
  },

  togli_piatto(a) {
    const nome = P.ricette[a.ricetta]?.n;
    const suo = !!P.ricette[a.ricetta]?.mia;
    const tolto = togliPiatto(a.ricetta);
    if (!tolto) return no('Posso togliere solo i piatti creati o ritoccati da te');
    return { ok: true, t: suo ? `Eliminato il piatto ${nome}` : `${nome}: tornato com'era nel piano`, u: { k: 'ripiatto', tolto } };
  },

  // Tutto il resto: l'assistente riscrive direttamente i dati (vedi modificaStato). Se dopo la modifica qualcosa non
  // sta in piedi l'app la rifiuta da sola, e qui si dice perche'.
  modifica(a) {
    const esito = modificaStato(a.operazioni || []);
    if (!esito.ok) return no(`Non l'ho fatto: ${esito.errore}`);
    return { ok: true, t: a.descrizione || 'Modifica fatta', u: { k: 'modifica', disfa: esito.disfa } };
  },

  // ---- le modifiche al piano piu' chieste hanno un'azione loro, piu' semplice (e piu' sicura) della modifica libera:
  // la sa scrivere anche un modello piccolo, e i conti li fa l'app
  obiettivo(a) {
    const quali = a.giorni === 'palestra' ? ['train'] : a.giorni === 'riposo' ? ['rest'] : ['train', 'rest'];
    const campi = ['kcal', 'p', 'c', 'f'].filter((k) => Number.isFinite(a[k]));
    if (!campi.length) return no('Non ho capito quale numero cambiare');
    const esito = modificaStato(quali.flatMap((q) => campi.map((k) => ({ op: 'metti', percorso: ['mie', 'obiettivi', q, k], valore: a[k] }))));
    if (!esito.ok) return no(`Non l'ho fatto: ${esito.errore}`);
    const nomi = { kcal: 'kcal', p: 'g di proteine', c: 'g di carboidrati', f: 'g di grassi' };
    const dove = a.giorni === 'palestra' ? 'dei giorni di palestra' : a.giorni === 'riposo' ? 'dei giorni di riposo' : 'di tutti i giorni';
    return { ok: true, t: `Obiettivi ${dove}: ${campi.map((k) => `${intero(a[k])} ${nomi[k]}`).join(', ')}`, u: { k: 'modifica', disfa: esito.disfa } };
  },

  quantita(a) {
    const r = P.ricette[a.ricetta], c = P.cibi[a.cibo];
    if (!r || !Array.isArray(r.ing)) return no('Non trovo quella ricetta');
    if (!c) return no('Non trovo quel cibo');
    const g = Math.round(a.grammi), gp = Math.round(a.grammi_palestra ?? a.grammi);
    const cera = r.ing.some((i) => i[0] === a.cibo);
    if (!cera && !g && !gp) return no(`In ${r.n.toLowerCase()} quel cibo non c'è già`);
    // la ricetta si riscrive intera: gli altri ingredienti restano com'erano
    const ing = r.ing.map((i) => (i[0] === a.cibo ? [a.cibo, g, gp] : [...i])).filter((i) => i[1] > 0 || i[2] > 0);
    if (!cera) ing.push([a.cibo, g, gp]);
    if (!ing.length) return no('Un piatto senza ingredienti non lo lascio');
    const esito = modificaStato([{ op: 'metti', percorso: ['mie', 'ricette', a.ricetta, 'ing'], valore: ing }]);
    if (!esito.ok) return no(`Non l'ho fatto: ${esito.errore}`);
    const quanto = !g && !gp ? 'tolto' : g === gp ? `${g} g` : `${g} g a riposo, ${gp} g in palestra`;
    return { ok: true, t: `${r.n}: ${c.n.toLowerCase()} ${quanto} · ora ${kcalDi(a.ricetta, 'rest')} kcal`, u: { k: 'modifica', disfa: esito.disfa } };
  },

  orario(a) {
    const m = P.momenti[a.pasto];
    if (!m || !/^\d\d:\d\d$/.test(a.ora || '')) return no('Non ho capito quale pasto spostare, o a che ora');
    const esito = modificaStato([{ op: 'metti', percorso: ['mie', 'momenti', a.pasto, 'ora'], valore: { rest: a.ora, train: a.ora } }]);
    if (!esito.ok) return no(`Non l'ho fatto: ${esito.errore}`);
    return { ok: true, t: `${m.n}: ora alle ${a.ora}`, u: { k: 'modifica', disfa: esito.disfa } };
  },

  tema(a) {
    const prima = tema();
    if (prima === a.aspetto) return no(`L'aspetto è già quello ${a.aspetto}`);
    cambiaTema(a.aspetto);
    return { ok: true, t: `Aspetto ${a.aspetto}`, u: { k: 'tema', prima } };
  },

  misure(a) {
    const g = oggi();
    const prima = M.circonferenze.find((x) => x.giorno === g) || null;
    salvaCirconferenze({ giorno: g, ...a.cm });
    return { ok: true, t: `Misure di oggi: ${Object.entries(a.cm).map(([k, v]) => `${k} ${dec(v)} cm`).join(', ')}`, u: { k: 'misure', giorno: g, prima } };
  },
};

export function esegui(a) {
  try {
    return FARE[a?.tipo] ? FARE[a.tipo](a) : no('Azione che non conosco');
  } catch {
    return no('Non ci sono riuscito');
  }
}

// ---------- tornare indietro ----------
const DISFARE = {
  voce(u) { togliExtra(u.d, u.id); if (u.era === false && u.mom !== FUORI_PASTO) segnaFatto(u.d, u.mom, false); },
  fatto(u) { segnaFatto(u.d, u.mom, u.era); },
  parte(u) { mangiatiSolo(u.d, u.mom, u.prima.saltati, u.prima.fatto); },
  dosi(u) { rimettiDosi(u.d, u.mom, u.prima); },
  rivoce(u) { rimettiVoce(u.d, u.prima); },
  rimetti(u) { aggiorna(() => { const g = giorno(u.d); g.extra = [...(g.extra || []), u.voce]; }); },
  acqua(u) {
    const i = (S.giorni[u.d]?.bevute || []).map((b) => b.ml).lastIndexOf(u.ml);
    if (i >= 0) togliBevuta(u.d, i);
  },
  attivita(u) { togliAttivita(u.id); },
  pesata(u) { const riga = M.pesate.find((x) => x.quando === u.quando); if (riga) eliminaMisura('pesate', riga); },
  cambi(u) { rimettiPasti(u.mom, u.prima); },
  piatto(u) { rimettiPasti(u.mom, u.prima); togliPiatto(u.rid); },
  ripiatto(u) { rimettiPiatto(u.tolto); },
  modifica(u) { return annullaModifica(u.disfa || []); },
  tema(u) { cambiaTema(u.prima); },
  misure(u) {
    const riga = M.circonferenze.find((x) => x.giorno === u.giorno);
    if (riga) eliminaMisura('circonferenze', riga);
    if (u.prima) salvaCirconferenze(u.prima);
  },
};

export function annulla(u) {
  try {
    if (!DISFARE[u?.k]) return false;
    return DISFARE[u.k](u) !== false;
  } catch {
    return false;
  }
}
