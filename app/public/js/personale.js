// Dal profilo di una persona al suo piano: quante calorie, in quali giorni si allena, quali ricette e in che quantita'.
// Serve a chi entra con un account suo e non ha un piano scritto a mano (quello arriva dal server e non passa di qui).
// Tutto parte dal catalogo (data/plan.json): stesse ricette, quantita' ricalcolate sulle calorie di chi lo usa.

export const SCOPI = {
  dimagrire: ['Perdere grasso', 'Mangi un po\' meno di quello che consumi, con tante proteine per non perdere muscolo'],
  tonificare: ['Rimodellarmi', 'Mangi circa quanto consumi: più muscolo, meno grasso, peso quasi fermo'],
  massa: ['Mettere muscolo', 'Mangi un po\' più di quello che consumi, per crescere'],
  mantenere: ['Mantenermi', 'Mangi quanto consumi, solo meglio'],
};
// nome, esempio, quanto moltiplica il metabolismo di base
export const LAVORI = {
  seduto: ['Seduto', 'Scrivania, studio, guida', 1.3],
  piedi: ['In piedi', 'Negozio, casa, sempre in giro', 1.45],
  fisico: ['Di fatica', 'Cantiere, magazzino, campagna', 1.65],
};
const GIORNI_BASE = { 1: [2], 2: [0, 3], 3: [0, 2, 4], 4: [0, 1, 3, 4], 5: [0, 1, 2, 3, 4], 6: [0, 1, 2, 3, 4, 5] };
export const giorniPer = (quanti) => GIORNI_BASE[Math.max(1, Math.min(6, quanti))];

const copia = (x) => (typeof structuredClone === 'function' ? structuredClone(x) : JSON.parse(JSON.stringify(x)));
const tondo = (x, passo) => Math.round(x / passo) * passo;

// Metabolismo di base (Mifflin-St Jeor) e calorie del giorno, di riposo e di allenamento.
export function calorie(pr) {
  const base = 10 * pr.peso + 6.25 * pr.altezza - 5 * pr.eta + (pr.sesso === 'f' ? -161 : 5);
  const fermo = base * (LAVORI[pr.lavoro] || LAVORI.seduto)[2];
  const allenato = fermo + 4 * pr.peso;   // una seduta con i pesi: circa 4 kcal per chilo
  const taglio = { dimagrire: [0.82, 0.82], tonificare: [0.95, 1.03], massa: [1.08, 1.1], mantenere: [1, 1] }[pr.obiettivo] || [1, 1];
  const minimo = Math.max(base * 1.08, pr.sesso === 'f' ? 1250 : 1500);   // sotto non si scende: il piano deve restare sostenibile
  return {
    base: Math.round(base),
    rest: tondo(Math.max(minimo, fermo * taglio[0]), 10),
    train: tondo(Math.max(minimo + 150, allenato * taglio[1]), 10),
  };
}

export function pesoObiettivo(pr) {
  const k = { dimagrire: 0.94, massa: 1.04 }[pr.obiettivo] || 1;
  return Math.round(pr.peso * k * 2) / 2;
}

function macroRicetta(P, rid, tipo) {
  const r = P.ricette[rid];
  if (!r) return { kcal: 0, p: 0, c: 0, f: 0 };
  if (r.libero) return { ...r.stima };
  const i = tipo === 'train' ? 2 : 1;
  const t = { kcal: 0, p: 0, c: 0, f: 0 };
  for (const ing of r.ing) for (const k in t) t[k] += P.cibi[ing[0]][k] * ing[i] / 100;
  return t;
}

function mediaGiorni(P, giorni, tipo, conShake) {
  const t = { kcal: 0, p: 0, c: 0, f: 0 };
  if (!giorni.length) return null;
  for (const g of giorni) {
    for (const rid of Object.values(g.pasti)) { const m = macroRicetta(P, rid, tipo); for (const k in t) t[k] += m[k]; }
    if (conShake && tipo === 'train') { const m = macroRicetta(P, 'shake', 'train'); for (const k in t) t[k] += m[k]; }
  }
  for (const k in t) t[k] /= giorni.length;
  return t;
}

// Una quantita' che si riesce a pesare: a pezzi interi (mezza barretta o mezzo uovo non li mangia nessuno),
// altrimenti a 5 o 10 grammi.
function pesabile(cibo, g) {
  if (g <= 0) return 0;
  if (cibo.pz) return Math.max(1, Math.round(g / cibo.pz)) * cibo.pz;
  return g < 60 ? Math.max(5, tondo(g, 5)) : tondo(g, 10);
}

function guida(pr, allena) {
  const strategia = {
    dimagrire: ['Per perdere grasso serve mangiare un po\' meno di quello che consumi: il piano lo fa già, senza fame.',
      'Le proteine sono alte apposta: così quello che perdi è grasso e non muscolo.',
      'Mezzo chilo a settimana è il ritmo giusto. Più veloce di così di solito non dura.'],
    tonificare: ['Non devi pesare meno: devi cambiare di cosa sei fatto. Per questo mangi circa quanto consumi.',
      'Tante proteine e allenamenti che diventano via via più impegnativi: il peso resta lì, la forma cambia.',
      'Guardati allo specchio e misura il giro vita: la bilancia qui dice poco.'],
    massa: ['Per mettere muscolo serve mangiare un po\' più di quello che consumi, non molto di più.',
      'Un quarto di chilo a settimana è il ritmo giusto: più veloce di così è soprattutto grasso.',
      'Il muscolo lo costruiscono gli allenamenti: il cibo lo rende possibile.'],
    mantenere: ['Mangi quanto consumi: l\'obiettivo è stare bene e tenere il peso dove sta.',
      'Proteine a ogni pasto e verdure tutti i giorni: il resto viene da sé.',
      'Se il peso si sposta di più di un chilo in un mese, ritocca le quantità.'],
  }[pr.obiettivo] || [];
  const tarare = {
    dimagrire: 'Se in due settimane non sei sceso di almeno mezzo chilo, togli 100-150 kcal: un po\' meno riso, pasta o patate.',
    massa: 'Se in due settimane il peso non si è mosso, aggiungi 100-150 kcal: un po\' più riso, pasta o patate.',
  }[pr.obiettivo] || 'Se il peso si sposta più di quanto vuoi, ritocca riso, pasta o patate di 20-30 grammi a pasto.';
  const voci = [
    { id: 'strategia', t: 'La strategia', icona: 'target', p: strategia },
    { id: 'dieta', t: 'Come usare il piano', icona: 'fork', p: [
      'Le quantità sono calcolate su di te. Pesa a crudo le prime volte, poi andrai a occhio.',
      'Un pasto non ti va? Toccalo e scegli Sostituisci: i conti restano in pari.',
      'Hai mangiato altro o sei fuori? Segnalo con "Ho mangiato altro": l\'anello delle calorie ti dice quanto resta.',
      'Spunta i pasti man mano: a fine giornata vedi subito com\'è andata.'] },
    { id: 'tarare', t: 'Come tarare le quantità', icona: 'scale', p: [
      'Pesati al mattino, a digiuno, due o tre volte a settimana, e guarda la media.', tarare,
      'Cambia una cosa sola per volta e aspetta due settimane prima di giudicare.'] },
  ];
  if (allena) {
    voci.push({ id: 'progressione', t: 'Come progredire in palestra', icona: 'trend', p: [
      'Ogni esercizio ha un intervallo di ripetizioni, per esempio 8-12.',
      'Quando chiudi tutte le serie al massimo dell\'intervallo, la volta dopo sali di carico e riparti dal minimo.',
      'Fermati una o due ripetizioni prima di non farcela più.',
      'L\'app ti propone i numeri giusti partendo dall\'ultima volta: se li hai fatti, basta una spunta.'] });
  }
  voci.push({ id: 'movimento', t: 'Movimento e sonno', icona: 'walk', p: [
    allena ? 'Nei giorni senza palestra fai mezz\'ora di camminata svelta: aiuta il recupero e brucia senza stancare.'
      : 'Punta a 150 minuti di movimento a settimana: mezz\'ora di camminata svelta, cinque giorni su sette, basta.',
    'Segna camminate, corse e allenamenti a casa nella sezione del movimento: vedi la settimana riempirsi.',
    'Dormi almeno sette ore: è lì che il corpo si sistema.'] });
  return voci;
}

// Il piano di una persona. `pr` = quello che ha detto di se': nome, sesso, eta, altezza, peso, obiettivo, lavoro,
// allena, giorni (0 = lunedi'), esclusi (gruppi di cibi), lattosio, shake, pesoObiettivo, dal (data d'inizio).
export function personalizza(base, pr) {
  const P = copia(base);
  const allena = pr.allena !== false;
  const giorniAll = allena ? (pr.giorni?.length ? pr.giorni : GIORNI_BASE[3]) : [];
  const modelli = { train: base.settimana.filter((g) => g.tipo === 'train'), rest: base.settimana.filter((g) => g.tipo === 'rest') };

  // 1. la settimana: i giorni di allenamento dove li vuole lui, con i pasti dei giorni dello stesso tipo
  const preso = { train: 0, rest: 0 };
  P.settimana = Array.from({ length: 7 }, (_, wd) => {
    const tipo = giorniAll.includes(wd) ? 'train' : 'rest';
    const m = modelli[tipo][preso[tipo]++ % modelli[tipo].length];
    return { tipo, pasti: { ...m.pasti } };
  });

  // 2. via i piatti con dentro quello che non mangia: al loro posto un altro dello stesso tipo
  const vietati = new Set((pr.esclusi || []).flatMap((g) => base.gruppi?.[g]?.cibi || []));
  const vaBene = (rid) => !P.ricette[rid].ing.some((i) => vietati.has(i[0]));
  if (vietati.size) {
    // tra quelli che vanno bene prende ogni volta il meno usato nella settimana, cosi' non torna sempre lo stesso
    const usi = new Map();
    const conta = (rid) => usi.set(rid, (usi.get(rid) || 0) + 1);
    for (const g of P.settimana) for (const rid of Object.values(g.pasti)) if (vaBene(rid)) conta(rid);
    for (const g of P.settimana) {
      for (const [mom, rid] of Object.entries(g.pasti)) {
        if (vaBene(rid)) continue;
        const tipo = P.ricette[rid].tipo;
        const oggi = new Set(Object.values(g.pasti));
        const scelte = Object.keys(P.ricette).filter((id) => P.ricette[id].tipo === tipo && !P.ricette[id].libero && !P.ricette[id].personale && vaBene(id));
        const libere = scelte.filter((id) => !oggi.has(id));
        const rosa = libere.length ? libere : scelte;
        if (!rosa.length) continue;
        g.pasti[mom] = rosa.reduce((meglio, id) => ((usi.get(id) || 0) < (usi.get(meglio) || 0) ? id : meglio), rosa[0]);
        conta(g.pasti[mom]);
      }
    }
  }

  // 3. le quantita'. Ogni ricetta ha i grammi per il giorno di riposo e per quello di allenamento, pensati per un'altra
  // persona: li porto alle calorie e alle proteine di questa. Due manopole: una per i cibi proteici (carne, pesce,
  // uova: almeno il 35% delle loro calorie viene dalle proteine) e una per tutto il resto. Cosi' chi ha bisogno di
  // tante calorie non si ritrova con il doppio delle proteine che gli servono, e chi ne ha poche non resta senza.
  const kcal = calorie(pr);
  const conShake = allena && !!pr.shake;
  const dei = (tipo) => { const suoi = P.settimana.filter((g) => g.tipo === tipo); return suoi.length ? suoi : modelli[tipo]; };
  const perChilo = (allena ? { dimagrire: 2, tonificare: 2, massa: 1.8, mantenere: 1.6 }
    : { dimagrire: 1.7, tonificare: 1.6, massa: 1.6, mantenere: 1.3 })[pr.obiettivo] || 1.6;
  const proteico = (id) => { const c = P.cibi[id]; return c.kcal > 0 && (c.p * 4) / c.kcal >= 0.35; };
  const originali = Object.fromEntries(Object.entries(P.ricette).map(([id, r]) => [id, r.ing]));
  const fra = (x, a, b) => Math.max(a, Math.min(b, Number.isFinite(x) ? x : 1));
  const scala = {};
  for (const tipo of ['rest', 'train']) {
    const i = tipo === 'train' ? 2 : 1;
    const giorni = dei(tipo);
    // calorie (K) e proteine (P) che nella media di questi giorni vengono dai cibi proteici (p) e dagli altri (c)
    const m = { Kp: 0, Kc: 0, Pp: 0, Pc: 0 };
    for (const g of giorni) {
      for (const rid of Object.values(g.pasti)) {
        if (P.ricette[rid].libero) { m.Kc += P.ricette[rid].stima.kcal; m.Pc += P.ricette[rid].stima.p; continue; }
        for (const ing of originali[rid]) {
          const c = P.cibi[ing[0]];
          if (proteico(ing[0])) { m.Kp += c.kcal * ing[i] / 100; m.Pp += c.p * ing[i] / 100; } else { m.Kc += c.kcal * ing[i] / 100; m.Pc += c.p * ing[i] / 100; }
        }
      }
    }
    for (const k in m) m[k] /= giorni.length;
    const shake = conShake && tipo === 'train' ? macroRicetta(P, 'shake', 'train') : { kcal: 0, p: 0 };   // lo shake e' un misurino: non si scala
    const K = kcal[tipo] - shake.kcal;
    const proteine = Math.min(pr.peso * perChilo, kcal[tipo] * 0.35 / 4) - shake.p;
    const det = m.Pp * m.Kc - m.Pc * m.Kp;
    const sp = fra((proteine * m.Kc - m.Pc * K) / det, 0.5, 2);
    scala[tipo] = { p: sp, c: fra((K - sp * m.Kp) / m.Kc, 0.4, 2.6), Kc: m.Kc };
  }
  // Arrotondando a pezzi interi e a 10 grammi le calorie si spostano: tre passate, e lo scarto lo assorbono i cibi
  // non proteici (riso, pasta, patate), che sono quelli che si pesano meglio.
  for (let passata = 0; passata < 3; passata++) {
    for (const [id, r] of Object.entries(P.ricette)) {
      if (r.libero || r.tipo === 'post') continue;
      r.ing = originali[id].map(([cibo, riposo, palestra]) => {
        const quale = proteico(cibo) ? 'p' : 'c';
        return [cibo, pesabile(P.cibi[cibo], riposo * scala.rest[quale]), pesabile(P.cibi[cibo], palestra * scala.train[quale])];
      });
    }
    for (const tipo of ['rest', 'train']) {
      const media = mediaGiorni(P, dei(tipo), tipo, conShake);
      scala[tipo].c = fra(scala[tipo].c + (kcal[tipo] - media.kcal) / scala[tipo].Kc, 0.4, 2.6);
    }
  }

  // 4. gli obiettivi: le calorie calcolate, e i grammi di proteine, carboidrati e grassi che il piano porta davvero
  P.obiettivi = { camminataMin: 30, acqua: { rest: tondo(pr.peso * 35, 100), train: tondo(pr.peso * 35, 100) + 500 } };
  for (const tipo of ['rest', 'train']) {
    const m = mediaGiorni(P, dei(tipo), tipo, conShake);
    P.obiettivi[tipo] = { kcal: kcal[tipo], p: tondo(m.p, 5), c: tondo(m.c, 5), f: tondo(m.f, 1) };
  }

  // 5. le schede di palestra nei suoi giorni
  Object.values(P.schede).filter((s) => !s.casa).forEach((s, i) => { s.giorno = giorniAll.length ? giorniAll[i % giorniAll.length] : null; });

  const scopo = (SCOPI[pr.obiettivo] || SCOPI.mantenere)[0].toLowerCase();
  P.profilo = {
    nome: pr.nome, sesso: pr.sesso, eta: pr.eta, altezza: pr.altezza, pesoIniziale: pr.peso, dataInizio: pr.dal,
    pesoObiettivo: pr.pesoObiettivo || pesoObiettivo(pr), metabolismoBasale: kcal.base,
    lattosio: !!pr.lattosio, allena, shake: conShake, creatina: false, generato: true, obiettivo: pr.obiettivo,
    note: `Obiettivo: ${scopo}. Lavoro ${(LAVORI[pr.lavoro] || LAVORI.seduto)[0].toLowerCase()}. `
      + (allena ? `Si allena ${giorniAll.length} ${giorniAll.length === 1 ? 'giorno' : 'giorni'} a settimana. ` : 'Non si allena in palestra. ')
      + (pr.lattosio ? 'Intollerante al lattosio. ' : '')
      + (pr.esclusi?.length ? `Non mangia: ${pr.esclusi.map((g) => base.gruppi?.[g]?.n.toLowerCase()).filter(Boolean).join(', ')}.` : ''),
  };
  P.puntiCarenti = [];
  P.guida = guida(pr, allena);
  return P;
}
