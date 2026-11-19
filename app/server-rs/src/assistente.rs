//! The assistant (assistente.py): the chat about one's own diet and training, which can also do things in the app.
//! The app sends a summary of what is needed with every question; here the rules are added, everything is cut to
//! size and the conversation goes to the account's AI service. Actions are checked here and applied by the app.

use crate::ai::{self, Immagine, Schema};
use crate::assistente_azioni::{azione, conti_storti, forma_locale, solo_nominati};
use crate::chiavi::{Motore, locale_di};
use crate::conf::conf;
use crate::errore::{Esito, Problema};
use crate::py::{self, get};
use crate::{cibo, log};
use regex::Regex;
use serde_json::{Map, Value, json};
use std::collections::{HashMap, VecDeque};
use std::sync::{LazyLock, Mutex};

const MAX_MESSAGGI: usize = 8;
const MAX_MESSAGGI_LOCALE: usize = 4;
const MAX_TESTO: usize = 1500;
const MAX_VECCHIO: usize = 500;
pub const MAX_CONTESTO: usize = 60000;
const MAX_AZIONI: usize = 8;

const REGOLE: &str = include_str!("../testi/regole.txt");
const SERVE: &str = include_str!("../testi/serve.txt");
const TUTTO: &str = include_str!("../testi/tutto.txt");
const FORMATO: &str = include_str!("../testi/formato.txt");
const ESEMPI_BASE: &str = include_str!("../testi/esempi_base.txt");
const ESEMPI_TUTTO: &str = include_str!("../testi/esempi_tutto.txt");
pub const SISTEMA_LOCALE: &str = include_str!("../testi/sistema_locale.txt");

static BASE: LazyLock<String> = LazyLock::new(|| [REGOLE, SERVE, FORMATO, ESEMPI_BASE].concat());
static INTERE: LazyLock<String> = LazyLock::new(|| [REGOLE, TUTTO, FORMATO, ESEMPI_TUTTO].concat());
pub static STRUMENTO: LazyLock<Value> = LazyLock::new(|| {
    serde_json::from_str(include_str!("../testi/strumento_assistente.json")).unwrap_or(Value::Null)
});

/// The instructions for the service: "base" (light) or "tutto".
pub fn istruzioni(livello: &str) -> &'static str {
    if livello == "tutto" { &INTERE } else { &BASE }
}

// ---- barcodes in the question
fn codice_valido(c: &str) -> bool {
    let mut cifre: Vec<u32> = c.chars().filter_map(|x| x.to_digit(10)).collect();
    let Some(controllo) = cifre.pop() else {
        return false;
    };
    let somma: u32 = cifre
        .iter()
        .rev()
        .enumerate()
        .map(|(i, v)| v * if i % 2 == 1 { 1 } else { 3 })
        .sum();
    (10 - somma % 10) % 10 == controllo
}

/// `(?<!\d)(\d{13}|\d{12}|\d{8})(?!\d)`: whole runs of digits that are 13, 12 or 8 long.
fn codici_nel_testo(testo: &str) -> Vec<String> {
    testo
        .split(|c: char| !c.is_ascii_digit())
        .filter(|run| matches!(run.len(), 8 | 12 | 13))
        .map(String::from)
        .collect()
}

/// `("%.1f" % v).rstrip("0").rstrip(".")` for numbers, `str(v)` for the rest.
fn cifra(v: &Value) -> String {
    match v {
        Value::Number(_) | Value::Bool(_) => {
            let s = format!("{:.1}", py::float(v).unwrap_or(0.0));
            s.trim_end_matches('0').trim_end_matches('.').to_string()
        }
        other => py::testo(other),
    }
}

/// Models cannot read the digits of a barcode and guess in front of a package: if the last question has a code,
/// the product is looked up in the catalogue and written next to the question, with its values.
pub fn con_i_codici(messaggi: &Value) -> Value {
    let Some(lista) = messaggi.as_array() else {
        return messaggi.clone();
    };
    let Some(ultima) = lista
        .last()
        .filter(|m| m.is_object() && get(m, "r").as_str() == Some("io"))
    else {
        return messaggi.clone();
    };
    let testo = py::testo_o(get(ultima, "t"));
    let mut codici: Vec<String> = Vec::new();
    for c in codici_nel_testo(&testo) {
        let c = if c.len() == 12 { format!("0{c}") } else { c };
        if codice_valido(&c) && !codici.contains(&c) {
            codici.push(c);
        }
    }
    let (mut note, mut trovati) = (Vec::new(), 0);
    for c in codici.iter().take(2) {
        let p = match cibo::prodotto_ean(c) {
            Err(_) => {
                note.push(format!("[Codice a barre {c}: il catalogo dei prodotti adesso non risponde. Non indovinare il prodotto: chiedi cos'e'.]"));
                continue;
            }
            Ok(None) => {
                note.push(format!("[Codice a barre {c}: il catalogo dei prodotti non lo conosce. Non indovinare il prodotto: chiedi nome e valori dell'etichetta.]"));
                continue;
            }
            Ok(Some(p)) => p,
        };
        trovati += 1;
        let mut pezzi = vec![format!(
            "{}{}",
            py::testo(get(&p, "n")),
            if py::vero(get(&p, "marca")) {
                format!(" ({})", py::testo(get(&p, "marca")))
            } else {
                String::new()
            }
        )];
        if py::vero(get(&p, "conf")) {
            pezzi.push(format!("confezione da {} g", cifra(get(&p, "conf"))));
        }
        if py::vero(get(&p, "pz")) && py::vero(get(&p, "pzn")) {
            pezzi.push(format!(
                "un {} pesa {} g",
                py::testo(&get(&p, "pzn")[0]),
                cifra(get(&p, "pz"))
            ));
        }
        let valori = if get(&p, "kcal").is_null() {
            "nel catalogo mancano i valori: chiedili".to_string()
        } else {
            let v: Vec<String> = ["kcal", "p", "c", "f"]
                .iter()
                .map(|k| cifra(get(&p, k)))
                .collect();
            format!(
                "per 100 g {} kcal, proteine {} g, carboidrati {} g, grassi {} g",
                v[0], v[1], v[2], v[3]
            )
        };
        note.push(format!(
            "[Codice a barre {c}: e' {}; {valori} (dal catalogo Open Food Facts).]",
            pezzi.join(", ")
        ));
    }
    if note.is_empty() {
        return messaggi.clone();
    }
    // only how many in the log: what the person eats is not written there
    log!(
        "assistente: {} codici a barre nella domanda, {} trovati nel catalogo",
        note.len(),
        trovati
    );
    let mut nuova = ultima.clone();
    nuova["t"] = Value::String(format!("{testo}\n{}", note.join("\n")));
    let mut fuori = lista[..lista.len() - 1].to_vec();
    fuori.push(nuova);
    Value::Array(fuori)
}

static DOMANDE: LazyLock<Mutex<HashMap<i64, VecDeque<f64>>>> =
    LazyLock::new(|| Mutex::new(HashMap::new()));

fn frena(utente: i64) -> Esito<()> {
    let ora = py::ora();
    let mut d = DOMANDE.lock().unwrap_or_else(|e| e.into_inner());
    let coda = d.entry(utente).or_default();
    while coda.front().is_some_and(|t| ora - t > 3600.0) {
        coda.pop_front();
    }
    if coda.len() >= conf().all_ora {
        return Err(Problema::new(
            429,
            "Hai fatto tante domande di fila: riprova tra qualche minuto.",
        ));
    }
    coda.push_back(ora);
    Ok(())
}

/// The context from the app, split for the VM's AI: (still parts, ever longer; "ADESSO").
fn parti_locale(dati: &str) -> (Vec<String>, String) {
    let dati = py::taglia(dati, 16000);
    let (fisso, adesso) = dati.split_once("\n\nADESSO\n").unwrap_or((&dati, ""));
    let (testa, piano) = fisso
        .split_once("\n\nPIANO DI QUESTI GIORNI\n")
        .unwrap_or((fisso, ""));
    let mut tappe = vec![
        SISTEMA_LOCALE.to_string(),
        format!("{SISTEMA_LOCALE}\n\nCONTESTO\n{testa}"),
    ];
    if !piano.is_empty() {
        let ultima = format!("{}\n\nPIANO DI QUESTI GIORNI\n{piano}", tappe[1]);
        tappe.push(ultima);
    }
    (tappe, adesso.to_string())
}

static SCALDATE: LazyLock<Mutex<HashMap<i64, f64>>> = LazyLock::new(|| Mutex::new(HashMap::new()));

/// The app calls it when the person opens the assistant: in the background the VM's AI reads the still part of
/// the context. No more than once every five minutes per person. Returns at once.
pub fn scalda(utente: i64, contesto: &Value) -> bool {
    if locale_di(utente).is_none() {
        return false;
    }
    let ora = py::ora();
    {
        let mut s = SCALDATE.lock().unwrap_or_else(|e| e.into_inner());
        if ora - s.get(&utente).copied().unwrap_or(0.0) < 300.0 {
            return true;
        }
        s.insert(utente, ora);
    }
    let (tappe, _) = parti_locale(&py::taglia(py::testo_o(contesto).trim(), MAX_CONTESTO));
    std::thread::spawn(move || {
        let _ = crate::ai_locale::scalda(&tappe);
    });
    true
}

/// A request "held by the hand", for small models (the VM's AI, Mistral's ministral): short instructions, light
/// context, the answer closed in the schema made of the person's real identifiers and, when grams and calories of
/// a food do not add up, a second request.
fn guidata(
    motore: &Motore,
    utente: i64,
    dati: &str,
    scambio: &[(String, String)],
    ids: &Value,
    foto: Option<&Immagine>,
) -> Esito<Option<Value>> {
    let locale = motore.nome == "locale";
    // full data (level "tutto") is useless to them: they do not do the free "modifica"
    let (tappe, adesso) = parti_locale(dati.split("\n\nSTATO (JSON:").next().unwrap_or(""));
    let mut sistema = tappe.last().cloned().unwrap_or_default();
    let mut scambio = scambio.to_vec();
    let domanda = scambio.last().map(|s| s.1.clone()).unwrap_or_default();
    if !adesso.is_empty() && locale && conf().locale_segnalibri {
        if let Some(ultimo) = scambio.last_mut() {
            ultimo.1 = format!("ADESSO\n{}\n\nDOMANDA\n{}", adesso.trim(), ultimo.1);
        }
    } else if !adesso.is_empty() {
        sistema = format!("{sistema}\n\nADESSO\n{adesso}");
    }
    let forma = forma_locale(ids);
    let chiedi = |messaggi: &[(String, String)], immagine: Option<&Immagine>| {
        ai::chiedi_struttura(
            motore,
            &sistema,
            messaggi,
            &STRUMENTO,
            700,
            Schema::Forma(&forma),
            immagine,
            &tappe,
        )
    };
    let mut esito = chiedi(&scambio, foto)?;
    let storti = esito
        .as_ref()
        .filter(|e| e.is_object())
        .map(|e| conti_storti(get(e, "azioni")))
        .unwrap_or_default();
    if let (false, Some(e)) = (storti.is_empty(), esito.as_mut()) {
        // the numbers do not add up: it is told and asked again, once
        log!(
            "assistente u{} ({}): grammi e calorie non tornano, lo richiedo",
            utente,
            motore.nome
        );
        let nomi: Vec<String> = storti
            .iter()
            .map(|(i, _)| {
                py::taglia(
                    &py::testo(py::o(
                        get(&e["azioni"][*i], "nome"),
                        &Value::String("quel cibo".into()),
                    )),
                    60,
                )
            })
            .collect();
        let richiamo = format!(
            "Controlla i numeri di {}: proteine e carboidrati valgono 4 kcal al grammo, i grassi 9, e insieme non possono \
             dare piu' delle kcal che hai scritto. Riscrivi la stessa risposta con i numeri giusti.",
            nomi.join(", ")
        );
        let mut ancora = scambio.clone();
        ancora.push(("ai".into(), crate::pyjson::largo(e)));
        ancora.push(("io".into(), richiamo));
        let secondo = chiedi(&ancora, None).ok().flatten();
        let buono = secondo.as_ref().is_some_and(|s| {
            s.is_object() && py::vero(get(s, "azioni")) && conti_storti(get(s, "azioni")).is_empty()
        });
        if buono {
            esito = secondo;
        } else if let Some(azioni) = e.get_mut("azioni").and_then(Value::as_array_mut) {
            // not fixed: the calories stay, the grams shrink in proportion
            for (i, dai_grammi) in &storti {
                let x = &mut azioni[*i];
                let kcal = py::float(get(x, "kcal")).unwrap_or(0.0);
                for k in ["proteine", "carboidrati", "grassi"] {
                    let v = py::float(py::o(get(x, k), &Value::from(0))).unwrap_or(0.0);
                    x[k] = py::n_f(py::round(v * kcal / dai_grammi, 1));
                }
            }
        }
    }
    if let Some(e) = esito.as_mut().filter(|e| e.is_object())
        && let Some(a) = e.get_mut("azioni")
    {
        solo_nominati(a, &domanda);
    }
    Ok(esito)
}

static DICE_FATTO: LazyLock<Regex> = LazyLock::new(|| {
    py::re(
        r"(?i)^\W*(fatto|segnat[oaie]|aggiunt[oaie]|tolt[oaie]|cambiat[oaie]|spostat[oaie]|impostat[oaie]|registrat[oaie]|aggiornat[oaie]|(l'|li |le |lo |la )?ho (segnat|aggiunt|tolt|cambiat|mess|spostat|registrat|impostat|portat|modificat|aggiornat))",
    )
});
static ORDINE: LazyLock<Regex> = LazyLock::new(|| {
    py::re(concat!(
        r"(?i)\b(?:segn[ai]|togli|lev[ai]|aggiungi|aggiorn[ai]|metti|cambia?|modific(?:a|hi)|sostituisci|spost[ai]|port[ai]|aument[ai]|",
        r"diminuisci|riduci|abbass[ai]|alz[ai]|elimin[ai]|rimuovi|cancell[ai]|impost[ai]|registr[ai]|spunt[ai]|correggi|ricalcol[ai]|",
        r"fai|rifai|fall[ao])(?:mi|lo|la|li|le|ne|gli)?\b|\b(?:puoi|potresti|riesci)\b|\b(?:mangiat|bevut)|",
        r"\bho (?:pres|fatt|mess|cors|camminat|pesat)|\b(?:s[iì]|vai|ok)\b"
    ))
});
static DOMANDA: LazyLock<Regex> = LazyLock::new(|| {
    py::re(concat!(
        r"(?i)^(?:ma\s+|e\s+|quindi\s+|allora\s+)*(?:posso|quanto|quanta|quanti|quante|quale|quali|come|perch[eé]|cosa|chi|dove|quando|",
        r"va bene|sicuro|sicura|devo|dovrei|conviene)\b"
    ))
});
static PARENTESI: LazyLock<Regex> = LazyLock::new(|| py::re(r"\[[^\]]*\]"));
static PAROLE: LazyLock<Regex> = LazyLock::new(|| py::re(r"[^\W\d_]+(?:'[^\W\d_]+)?"));
const CENNI: [&str; 16] = [
    "ok",
    "okay",
    "va",
    "bene",
    "meglio",
    "capito",
    "perfetto",
    "grazie",
    "ottimo",
    "giusto",
    "certo",
    "si",
    "sì",
    "vai",
    "chiaro",
    "d'accordo",
];

/// True if the last message does not ask to change anything: then no action must start, whatever the model says.
fn senza_permesso(scambio: &[(String, String)]) -> bool {
    let Some(ultimo) = scambio.last() else {
        return false;
    };
    let pulito = PARENTESI.replace_all(&ultimo.1, " ").trim().to_string();
    if (pulito.ends_with('?') || DOMANDA.is_match(&pulito)) && !ORDINE.is_match(&pulito) {
        return true;
    }
    let minuscolo = pulito.to_lowercase();
    let parole: Vec<&str> = PAROLE.find_iter(&minuscolo).map(|m| m.as_str()).collect();
    if !parole.is_empty() && parole.iter().all(|p| CENNI.contains(p)) {
        let prima = match scambio.len().checked_sub(2).map(|i| &scambio[i]) {
            Some((chi, t)) if chi == "ai" => PARENTESI.replace_all(t, " ").trim().to_string(),
            _ => String::new(),
        };
        return !prima.ends_with('?');
    }
    false
}

/// {"testo", "azioni", "motore", "modello"}, or {"serve": "tutto"} when at the base level the assistant says it needs
/// the full data. Plus "scartate", "vuoto" and "bloccate" when something does not add up.
#[expect(
    clippy::too_many_arguments,
    reason = "same parameters as the Python function it ports, kept for side-by-side review"
)]
pub fn rispondi(
    motore: &Motore,
    utente: i64,
    contesto: &Value,
    messaggi: &Value,
    immagine: &Value,
    livello: &Value,
    ids: &Value,
    conta: bool,
) -> Esito<Value> {
    let Some(messaggi) = messaggi.as_array() else {
        return Err(Problema::new(400, "manca la domanda"));
    };
    let locale = motore.nome == "locale";
    let mut livello = if locale {
        "locale"
    } else if livello.as_str() == Some("tutto") {
        "tutto"
    } else {
        "base"
    };
    let quanti = if locale {
        MAX_MESSAGGI_LOCALE
    } else {
        MAX_MESSAGGI
    };
    let ultimi: Vec<&Value> = messaggi[messaggi.len().saturating_sub(quanti)..]
        .iter()
        .filter(|m| m.is_object() && matches!(get(m, "r").as_str(), Some("io" | "ai")))
        .collect();
    let mut scambio: Vec<(String, String)> = Vec::new();
    for (i, m) in ultimi.iter().enumerate() {
        // the current question whole, the earlier ones shortened: they serve the thread, not word for word
        let lungo = if i + 1 == ultimi.len() {
            MAX_TESTO
        } else {
            MAX_VECCHIO
        };
        let testo = py::taglia(py::testo_o(get(m, "t")).trim(), lungo);
        if !testo.is_empty() {
            scambio.push((py::testo(get(m, "r")), testo));
        }
    }
    while scambio.first().is_some_and(|s| s.0 != "io") {
        scambio.remove(0); // the conversation must start with a question
    }
    if scambio.last().is_none_or(|s| s.0 != "io") {
        return Err(Problema::new(400, "manca la domanda"));
    }
    let foto = if py::vero(immagine) {
        Some(cibo::immagine_buona(immagine)?)
    } else {
        None
    };
    if conta {
        frena(utente)?;
    }
    let dati = py::taglia(py::testo_o(contesto).trim(), MAX_CONTESTO);
    let dati = if dati.is_empty() {
        "Nessun dato disponibile.".to_string()
    } else {
        dati
    };
    let sistema = |liv: &str| format!("{}\n\nCONTESTO\n{dati}", istruzioni(liv));
    let esito = if locale {
        guidata(motore, utente, &dati, &scambio, ids, foto.as_ref())?
    } else {
        // to Gemini and the big Mistral models only "answer in JSON", the shape explained in the instructions
        match ai::chiedi_struttura(
            motore,
            &sistema(livello),
            &scambio,
            &STRUMENTO,
            8192,
            Schema::No,
            foto.as_ref(),
            &[],
        ) {
            Ok(e) => e,
            Err(e) => {
                // Mistral: if the plan does not include the big models (or they are full, or silent), the small ones answer
                let di_mistral = std::iter::once(motore.coppia())
                    .chain(motore.riserve.iter().cloned())
                    .find(|m| m.0 == "mistral");
                let Some(dm) = di_mistral.filter(|_| e.chiuso || ai::stanco(&e)) else {
                    return Err(e);
                };
                match guidata(
                    &Motore::uno(&dm.0, &dm.1),
                    utente,
                    &dati,
                    &scambio,
                    ids,
                    foto.as_ref(),
                ) {
                    Ok(r) => {
                        livello = "guidato";
                        r
                    }
                    Err(secondo) => {
                        return Err(if e.chiuso && motore.nome == "mistral" {
                            secondo
                        } else {
                            e
                        });
                    }
                }
            }
        }
    };
    let Some(esito) = esito else {
        // no second request: it would cost as many token and the per-minute limits would refuse it
        return Err(Problema::new(
            502,
            "La risposta non e' arrivata intera. Riprova, magari chiedendo una cosa alla volta.",
        ));
    };
    if py::vero(get(&esito, "serve"))
        && !py::vero(get(&esito, "risposta"))
        && !py::vero(get(&esito, "azioni"))
    {
        if livello == "base" {
            log!("assistente u{}: servono i dati completi", utente);
            return Ok(json!({"serve": "tutto"}));
        }
        return Err(Problema::new(
            502,
            "Non sono riuscito a rispondere. Riprova.",
        ));
    }
    let mut testo = py::testo_o(get(&esito, "risposta")).trim().to_string();
    let grezze: &[Value] = get(&esito, "azioni")
        .as_array()
        .map(|a| &a[..a.len().min(MAX_AZIONI)])
        .unwrap_or(&[]);
    let tutte_grezze = get(&esito, "azioni").as_array().map(Vec::len).unwrap_or(0);
    let mut azioni: Vec<Value> = grezze.iter().filter_map(azione).collect();
    // in the log only the shape of what happened, never what the person ate
    let mut scartate: Vec<String> = grezze
        .iter()
        .filter(|x| azione(x).is_none())
        .map(|x| match x.as_object() {
            Some(o) => {
                let mut k: Vec<String> = o.keys().cloned().collect();
                k.sort();
                py::repr(&json!(k))
            }
            None => py::repr(&Value::String(tipo_python(x).into())),
        })
        .collect();
    let vuoto = tutte_grezze == 0 && DICE_FATTO.is_match(&testo);
    let bloccate = if tutte_grezze > 0 && senza_permesso(&scambio) {
        tutte_grezze
    } else {
        0
    };
    if bloccate > 0 {
        azioni.clear();
        scartate.clear();
        let mut ancora = scambio.clone();
        ancora.push((
            "ai".into(),
            if testo.is_empty() {
                "...".into()
            } else {
                testo.clone()
            },
        ));
        ancora.push(("io".into(), "Non ti ho chiesto di cambiare niente. Rispondi solo a quello che ti ho detto, con azioni vuote e senza dire di aver fatto qualcosa.".into()));
        let secondo = if livello == "locale" || livello == "guidato" {
            guidata(motore, utente, &dati, &ancora, ids, foto.as_ref())
        } else {
            ai::chiedi_struttura(
                motore,
                &sistema(livello),
                &ancora,
                &STRUMENTO,
                8192,
                Schema::No,
                foto.as_ref(),
                &[],
            )
        }
        .ok()
        .flatten();
        let pulita = secondo
            .filter(|s| s.is_object() && !py::vero(get(s, "azioni")))
            .map(|s| py::testo_o(get(&s, "risposta")).trim().to_string())
            .unwrap_or_default();
        testo = if pulita.is_empty() {
            "Non ho cambiato niente, perche' non me l'hai chiesto. Se vuoi che lo faccia, dimmelo."
                .into()
        } else {
            pulita
        };
    }
    let mut campi: Vec<&String> = esito
        .as_object()
        .map(|o| o.keys().collect())
        .unwrap_or_default();
    campi.sort();
    log!(
        "assistente u{} ({}): campi {}, azioni proposte {}, valide {}{}{}{}",
        utente,
        livello,
        py::repr(&json!(campi)),
        tutte_grezze,
        py::repr(&json!(
            azioni.iter().map(|a| a["tipo"].clone()).collect::<Vec<_>>()
        )),
        if scartate.is_empty() {
            String::new()
        } else {
            format!(", scartate [{}]", scartate.join(", "))
        },
        if vuoto {
            ", dice fatto senza azioni"
        } else {
            ""
        },
        if bloccate > 0 {
            ", bloccate: non le aveva chieste"
        } else {
            ""
        }
    );
    if testo.is_empty() && azioni.is_empty() {
        return Err(Problema::new(
            502,
            "Non sono riuscito a rispondere. Riprova.",
        ));
    }
    let mut r = Map::new();
    r.insert(
        "testo".into(),
        Value::String(py::taglia(
            if testo.is_empty() { "Fatto." } else { &testo },
            6000,
        )),
    );
    r.insert("azioni".into(), Value::Array(azioni));
    r.insert("motore".into(), Value::String(ai::chi_ha_risposto(motore)));
    r.insert(
        "modello".into(),
        ai::quale_modello()
            .map(Value::String)
            .unwrap_or(Value::Null),
    );
    if !scartate.is_empty() {
        r.insert("scartate".into(), Value::from(scartate.len()));
    }
    if vuoto {
        r.insert("vuoto".into(), Value::Bool(true));
    }
    if bloccate > 0 {
        r.insert("bloccate".into(), Value::from(bloccate));
    }
    Ok(Value::Object(r))
}

/// `type(x).__name__` for JSON values
fn tipo_python(v: &Value) -> &'static str {
    match v {
        Value::Null => "NoneType",
        Value::Bool(_) => "bool",
        Value::Number(n) if n.is_f64() => "float",
        Value::Number(_) => "int",
        Value::String(_) => "str",
        Value::Array(_) => "list",
        Value::Object(_) => "dict",
    }
}

#[cfg(test)]
mod test {
    use super::*;

    fn s(v: &[(&str, &str)]) -> Vec<(String, String)> {
        v.iter()
            .map(|(a, b)| (a.to_string(), b.to_string()))
            .collect()
    }

    #[test]
    fn istruzioni_come_prova_server() {
        for liv in ["base", "tutto"] {
            let t = istruzioni(liv);
            for pezzo in [
                "non la vedi piu'",
                "ha ragione la persona",
                "dettati a voce",
                "il piano non cambia",
                "mai da quello che c'e' nel piano",
                "non aggiungere un'altra voce",
                "- dose:",
                "- cambia_voce:",
            ] {
                assert!(t.contains(pezzo), "{liv}: {pezzo}");
            }
        }
        // the base level is much shorter than "tutto" (the 11000-character threshold of prova_server.py is stale)
        let (base, tutto) = (
            istruzioni("base").chars().count(),
            istruzioni("tutto").chars().count(),
        );
        assert!(base * 4 < tutto * 3, "{base} {tutto}");
        for regola in [
            "9. Una foto la vedi solo",
            "10. Se ti corregge",
            "11. I messaggi spesso",
            "12. Quanto ha messo oggi",
        ] {
            assert!(SISTEMA_LOCALE.contains(regola));
        }
    }

    #[test]
    fn permesso() {
        assert!(senza_permesso(&s(&[("io", "No e latte e nesq li butto?")])));
        assert!(senza_permesso(&s(&[("io", "ok meglio")])));
        assert!(!senza_permesso(&s(&[
            ("ai", "Vuoi che lo segni?"),
            ("io", "si")
        ])));
        assert!(!senza_permesso(&s(&[("io", "ho mangiato una mela")])));
        assert!(!senza_permesso(&s(&[("io", "me lo segni?")])));
    }

    #[test]
    fn codici() {
        assert_eq!(
            codici_nel_testo("ho mangiato 12345678 gallette e 5900020017421 x 123456789"),
            vec!["12345678", "5900020017421"]
        );
        assert!(codice_valido("5900020017420"));
        assert!(!codice_valido("5900020017421"));
        assert!(!codice_valido("12345678"));
        assert_eq!(cifra(&json!(6.7)), "6.7");
        assert_eq!(cifra(&json!(400)), "400");
        assert_eq!(cifra(&json!(25.0)), "25");
    }

    #[test]
    fn dice_fatto() {
        assert!(DICE_FATTO.is_match("Fatto: ho segnato tutto."));
        assert!(!DICE_FATTO.is_match("Ti mancano 60 g"));
    }
}
