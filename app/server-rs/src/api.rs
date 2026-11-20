//! The API (server.py `_api`, `_bilancia`): same paths, methods, status codes and JSON shapes.

use crate::chiavi::{self, Motore, motore_ai, motore_di, motore_di_v};
use crate::errore::{Esito, Problema, errore};
use crate::lavori::{self, Ritiro};
use crate::py::{self, get, vero};
use crate::server::{Ctx, Risposta, Via};
use crate::{accesso, assistente, cibo, parere, spinta};
use regex::Regex;
use serde_json::{Value, json};
use std::sync::{Arc, LazyLock};

static RE_PERSONA: LazyLock<Regex> =
    LazyLock::new(|| py::re(r"^/api/persone/([0-9]+)(/password)?$"));
static RE_ELIMINA: LazyLock<Regex> =
    LazyLock::new(|| py::re(r"^/api/(pesate|circonferenze)/([0-9]+)$"));
static RE_LAVORO: LazyLock<Regex> =
    LazyLock::new(|| py::re(r"^/api/chat/lavoro/([A-Za-z0-9_-]{8,40})$"));
static RE_TOGLI_CHIAVE: LazyLock<Regex> = LazyLock::new(|| py::re(r"^/api/ai/chiave/([a-z]+)$"));
static RE_EAN: LazyLock<Regex> = LazyLock::new(|| py::re(r"^/api/cibo/ean/([0-9]{8,14})$"));
static RE_EAN_CORPO: LazyLock<Regex> = LazyLock::new(|| py::re(r"^[0-9]{8,14}$"));

fn ok(v: Value) -> Esito<Risposta> {
    Ok(Risposta::json(200, &v))
}

/// `int(s)` of a path segment made of digits; out of range is a 404 like an unknown person.
fn id_da(s: &str) -> Esito<i64> {
    s.parse().map_err(|_| Problema::new(404, "non trovato"))
}

/// `dict(a, **b)`
fn unisci(mut a: Value, b: Value) -> Value {
    if let (Some(o), Value::Object(b)) = (a.as_object_mut(), b) {
        for (k, v) in b {
            o.insert(k, v);
        }
    }
    a
}

fn solo_capo(c: &Ctx) -> Esito<()> {
    if c.utente().capo == 0 {
        return errore(403, "Solo chi gestisce l'app puo' farlo");
    }
    Ok(())
}

/// The hand-written plan file for whoever asks (piani/<username>.json), if there is one.
fn file_piano(c: &Ctx) -> Option<std::path::PathBuf> {
    let u = accesso::nome_utente(c.utente().utente.as_deref().unwrap_or(""))?;
    let p = c.app.dati.piani.join(format!("{u}.json"));
    p.is_file().then_some(p)
}

pub fn api(c: &mut Ctx, metodo: &str, path: &str) -> Esito<Risposta> {
    let u = c.utente().id;
    let cartella = c.app.dati.cartella.clone();
    let d = &c.app.dati;
    match (metodo, path) {
        ("GET", "/api/io") => {
            let motore = motore_ai(&cartella, u);
            let fila = chiavi::fila(&cartella, u);
            let io = c.utente();
            let attese = if io.capo != 0 { d.attese()?.len() } else { 0 };
            let r = json!({
                "id": u, "nome": io.nome, "utente": io.utente, "capo": io.capo != 0,
                "bilancia": io.capo != 0, "ai": !fila.is_empty(), "motore": motore.map(|m| m.nome), "fila": fila,
                "piano": file_piano(c).is_some(),
                "esci": matches!(c.via, Some(Via::Cookie)),
                "attese": attese,
            });
            return Ok(Risposta::json(200, &r).biscotti(c.biscotti()));
        }
        ("POST", "/api/io") => {
            let nome = d.rinomina(u, get(&c.corpo()?.1, "nome"))?;
            if let Some(io) = c.io.as_mut() {
                io.nome = nome.clone();
            }
            return Ok(
                Risposta::json(200, &json!({"ok": true, "nome": nome})).biscotti(c.biscotti())
            );
        }
        ("POST", "/api/esci") => {
            let mut r = json!({"ok": true});
            let mut cookie = accesso::biscotti_spenti();
            if crate::oidc::attivo() {
                // whoever leaves here is not signed in again silently, only with the form
                cookie.push(crate::oidc::biscotto_uscito());
            }
            if c.via == Some(Via::Cookie) {
                // a session from EverID ends at EverID too; the app shows the login page when it has no "dove"
                if let Some(dove) = crate::oidc::uscita(c)? {
                    r["dove"] = Value::String(dove);
                }
                d.chiudi_sessione(u, &c.gettone)?;
            }
            return Ok(Risposta::json(200, &r).biscotti(cookie));
        }
        ("GET", "/api/piano") => {
            // the hand-written plan for this person; whoever has none gets it computed by the app from the profile
            return Ok(match file_piano(c).and_then(|p| std::fs::read(p).ok()) {
                Some(b) => Risposta::new(200, b, "application/json; charset=utf-8"),
                None => Risposta::json(200, &json!({})),
            });
        }
        _ => {}
    }
    // ---- people: only the admin adds and removes them
    if path == "/api/persone" || path.starts_with("/api/persone/") {
        solo_capo(c)?;
        if path == "/api/persone" {
            match metodo {
                "GET" => return ok(json!({"persone": d.persone()?, "attese": d.attese()?})),
                "POST" => {
                    let b = c.corpo()?.1;
                    return ok(d.crea_persona(
                        get(&b, "nome"),
                        get(&b, "utente"),
                        get(&b, "password"),
                    )?);
                }
                _ => {}
            }
        }
        if let Some(m) = RE_PERSONA.captures(path) {
            let password = m.get(2).is_some();
            if metodo == "POST" && password {
                let id = id_da(&m[1])?;
                return ok(d.cambia_password(id, get(&c.corpo()?.1, "password"))?);
            }
            if metodo == "DELETE" && !password {
                d.elimina_persona(id_da(&m[1])?)?;
                return ok(json!({"ok": true}));
            }
        }
        return Ok(Risposta::json(404, &json!({"errore": "non trovato"})));
    }
    match (metodo, path) {
        // ---- state and measures
        ("GET", "/api/state") => {
            return Ok(Risposta::new(
                200,
                d.stato(u)?.into_bytes(),
                "application/json; charset=utf-8",
            ));
        }
        // phone and PC often ask "did anything change?": the date is enough, not the whole state
        ("GET", "/api/state/versione") => return ok(json!({"updatedAt": d.versione_stato(u)?})),
        ("PUT", "/api/state") => {
            let (testo, nuovo) = c.corpo()?;
            if let Some(piu_recente) = d.salva_stato(u, &testo, &nuovo)? {
                return Ok(Risposta::json(
                    409,
                    &json!({"errore": "stato piu' recente sul server", "stato": piu_recente}),
                ));
            }
            return ok(json!({"ok": true, "updatedAt": get(&nuovo, "updatedAt")}));
        }
        ("GET", "/api/misure") => return ok(d.misure(u)?),
        // ---- steps from the iPhone: the code for the shortcut (shown once, when created) and how it went
        ("GET", "/api/passi/codice") => return ok(d.stato_passi(u)?),
        ("POST", "/api/passi/codice") => return ok(json!({"codice": d.nuovo_codice_passi(u)?})),
        ("DELETE", "/api/passi/codice") => {
            d.togli_codice_passi(u)?;
            return ok(json!({"ok": true}));
        }
        ("POST", "/api/passi") => {
            let b = c.corpo()?.1;
            return ok(d.salva_passi(u, get(&b, "passi"), get(&b, "giorno"))?);
        }
        ("POST", "/api/pesate") => return ok(d.salva_pesata(u, &c.corpo()?.1)?),
        ("POST", "/api/circonferenze") => return ok(d.salva_circonferenze(u, &c.corpo()?.1)?),
        _ => {}
    }
    if metodo == "DELETE"
        && let Some(m) = RE_ELIMINA.captures(path)
    {
        let trovata = match m[2].parse::<i64>() {
            Ok(id) => d.elimina(u, &m[1], id)?,
            Err(_) => false,
        };
        return Ok(if trovata {
            Risposta::json(200, &json!({"ok": true}))
        } else {
            Risposta::json(404, &json!({"errore": "non trovato"}))
        });
    }
    match (metodo, path) {
        // ---- how the app looks on that device: screen sizes sent at start; they only go to the log
        ("POST", "/api/diagnosi") => {
            let b = c.corpo()?.1;
            crate::log!(
                "diagnosi u{} {}",
                u,
                py::taglia(&crate::pyjson::ascii_compatto(&b), 1200)
            );
            return ok(json!({"ok": true}));
        }
        // ---- AI: everyone with their own key
        ("GET", "/api/funzioni") => {
            let motore = motore_ai(&cartella, u);
            return ok(
                json!({"foto": motore.is_some(), "ai": !chiavi::fila(&cartella, u).is_empty(), "motore": motore.map(|m| m.nome)}),
            );
        }
        ("POST", "/api/cibo/parere") => {
            let b = c.corpo()?.1;
            let ean = py::testo_o(get(&b, "ean"));
            if !RE_EAN_CORPO.is_match(&ean) {
                return errore(400, "codice non valido");
            }
            return ok(d.parere(
                u,
                &ean,
                &py::testo_o(get(&b, "persona")),
                vero(get(&b, "rifai")),
            )?);
        }
        ("POST", "/api/chat") => return chat(c, u, &cartella),
        // ---- phone notifications
        ("GET", "/api/notifiche/chiave") => {
            return ok(json!({"chiave": spinta::chiave(&cartella).1}));
        }
        ("POST", "/api/notifiche/iscrizione") => {
            let b = c.corpo()?.1;
            let acceso = d.iscrivi(
                u,
                get(&b, "indirizzo"),
                get(&b, "fuso"),
                get(&b, "orari"),
                get(&b, "promemoria"),
            )?;
            return ok(json!({"ok": true, "promemoria": acceso}));
        }
        ("DELETE", "/api/notifiche/iscrizione") => {
            d.disiscrivi(&py::testo_o(get(&c.corpo()?.1, "indirizzo")), Some(u))?;
            return ok(json!({"ok": true}));
        }
        ("GET", "/api/notifiche/prossime") => return ok(json!({"notifiche": d.prossime(u)?})),
        ("POST", "/api/notifiche/prova") => {
            let etichetta = format!("prova-{}", py::int(py::ora() * 1000.0));
            let quanti = d.avvisa(
                u,
                &etichetta,
                "EverFit",
                "Le notifiche funzionano.",
                Some("./"),
            )?;
            return ok(json!({"ok": quanti > 0, "telefoni": quanti}));
        }
        // the person opened the assistant: if the VM's AI may have to answer, it gets ready meanwhile
        ("POST", "/api/chat/scalda") => {
            return ok(json!({"ok": assistente::scalda(u, get(&c.corpo()?.1, "contesto"))}));
        }
        _ => {}
    }
    if metodo == "GET"
        && let Some(m) = RE_LAVORO.captures(path)
    {
        return match lavori::ritira(u, &m[1]) {
            None => errore(404, "Questa risposta non c'e' piu': rifai la domanda"),
            Some(Ritiro::InCorso(v)) => ok(v),
            Some(Ritiro::Fatto(codice, r)) => {
                ok(unisci(r, json!({"fatto": true, "codice": codice})))
            }
        };
    }
    match (metodo, path) {
        // keys are written from the app; the server only says whether they exist, never returns them
        ("GET", "/api/ai") => return ok(chiavi::stato(&cartella, u)),
        ("POST", "/api/ai/chiave") => {
            let b = c.corpo()?.1;
            chiavi::salva_chiave(&cartella, u, get(&b, "motore"), get(&b, "chiave"))?;
            // the key just written is tested, not the service that answers first
            let esito = match motore_di_v(&cartella, u, get(&b, "motore")) {
                Some(m) => {
                    parere::prova(&m).map(|r| json!({"ok": true, "modello": get(&r, "modello")}))
                }
                None => Err(Problema::new(500, "chiave non salvata")),
            };
            let esito = match esito {
                Ok(v) => v,
                Err(e) if e.database => return Err(e),
                Err(e) => {
                    if e.chiave {
                        // a key the service refuses is not kept
                        if let Some(nome) = get(&b, "motore").as_str() {
                            chiavi::togli_chiave(&cartella, u, nome)?;
                        }
                    }
                    json!({"ok": false, "errore": e.testo})
                }
            };
            return ok(unisci(esito, chiavi::stato(&cartella, u)));
        }
        ("POST", "/api/ai/prova") => {
            let quale = c
                .corpo()
                .ok()
                .map(|(_, b)| get(&b, "motore").clone())
                .unwrap_or(Value::Null);
            // with a service name only that key is tested; without one, whoever answers first
            let motore = if vero(&quale) {
                motore_di_v(&cartella, u, &quale)
            } else {
                motore_ai(&cartella, u)
            };
            let Some(motore) = motore else {
                return errore(503, "Non c'e' nessuna chiave");
            };
            let esito = parere::prova(&motore)?;
            lavori::rimetti(&motore.nome);
            return ok(esito);
        }
        _ => {}
    }
    if metodo == "DELETE"
        && let Some(m) = RE_TOGLI_CHIAVE.captures(path)
    {
        chiavi::togli_chiave(&cartella, u, &m[1])?;
        return ok(unisci(json!({"ok": true}), chiavi::stato(&cartella, u)));
    }
    // ---- foods for the diary
    if metodo == "GET"
        && let Some(m) = RE_EAN.captures(path)
    {
        return ok(d.prodotto(&m[1])?);
    }
    match (metodo, path) {
        ("GET", "/api/cibo/cerca") => {
            let q = py::parse_qs(&c.req.query).remove("q").unwrap_or_default();
            let testo = py::taglia(&py::spazi(&q), 60);
            if testo.chars().count() < 2 {
                return errore(400, "scrivi almeno due lettere");
            }
            return ok(json!({"risultati": cibo::cerca(&testo)?}));
        }
        ("POST", "/api/foto") => {
            let b = c.corpo()?.1;
            let Some(motore) = motore_ai(&cartella, u) else {
                return errore(
                    503,
                    "Il riconoscimento da foto non e' attivo per questo account",
                );
            };
            return ok(cibo::riconosci(
                &motore,
                get(&b, "immagine"),
                get(&b, "nota"),
            )?);
        }
        _ => {}
    }
    // ---- scale: the phone asks, the watcher on the PC does (ponte.rs)
    if let Some(cosa) = path.strip_prefix("/api/bilancia/") {
        return bilancia(c, metodo, cosa);
    }
    Ok(Risposta::json(404, &json!({"errore": "non trovato"})))
}

fn chat(c: &Ctx, u: i64, cartella: &std::path::Path) -> Esito<Risposta> {
    let dati = c.corpo()?.1;
    // Who answers, in order. The app asks one at a time, by name ("motore"), so it knows and shows who is answering,
    // and when one gives up it moves on by itself ("prossimo"). Without a name the services are tried here.
    let fila = chiavi::fila(cartella, u);
    if fila.is_empty() {
        return errore(
            503,
            "L'assistente e' spento: serve la chiave di un servizio di AI",
        );
    }
    let mut nome = get(&dati, "motore")
        .as_str()
        .filter(|n| fila.iter().any(|f| f == n))
        .map(String::from);
    let motore = match &nome {
        Some(n) => motore_di(cartella, u, n),
        None => motore_ai(cartella, u),
    };
    let motore = match motore {
        Some(m) => m,
        None => {
            // no key, but there is the VM's AI
            nome = Some("locale".into());
            chiavi::locale_di(u).unwrap_or_else(|| Motore::uno("locale", ""))
        }
    };
    let lento = motore.nome == "locale";
    let dati = Arc::new(dati);
    let chiedi = {
        let (dati, motore, fila, nome) = (dati.clone(), motore.clone(), fila.clone(), nome.clone());
        move || -> (u16, Value) {
            let r = assistente::rispondi(
                &motore,
                u,
                get(&dati, "contesto"),
                get(&dati, "messaggi"),
                get(&dati, "immagine"),
                get(&dati, "livello"),
                get(&dati, "ids"),
                true,
            );
            match r {
                Ok(v) => (200, v),
                Err(e) if e.database => (500, json!({"errore": "database non disponibile"})),
                // a wrong question is wrong for everyone: just the error
                Err(e) if e.per_tutti() => (e.codice, json!({"errore": e.testo})),
                Err(e) => {
                    // the service is full, silent or answered badly: the app knows how long to wait and whom to ask now
                    let dopo = nome
                        .as_ref()
                        .and_then(|n| fila.iter().position(|f| f == n))
                        .and_then(|i| fila.get(i + 1))
                        .cloned();
                    let codice = if e.remoto == Some(429) { 429 } else { e.codice };
                    (
                        codice,
                        json!({"errore": e.testo, "attesa": e.attesa, "giornaliero": e.giornaliero,
                        "motore": nome.clone().unwrap_or_else(|| motore.nome.clone()), "prossimo": dopo, "perche": e.perche}),
                    )
                }
            }
        }
    };
    if vero(get(&dati, "lavoro")) {
        // the current app: the question becomes a job the server carries to the end, one service after the other;
        // "id" is the mark of the question: if the phone sends it again (network lost) the same job resumes
        let motori: Vec<Motore> = fila
            .iter()
            .filter_map(|n| motore_di(cartella, u, n))
            .collect();
        let k = py::taglia(&py::testo_o(get(&dati, "id")), 40);
        let k = (!k.is_empty()).then_some(k);
        let subito = get(&dati, "livello").as_str() == Some("tutto");
        let numero = lavori::avvia(
            u,
            move |voce| {
                let messaggi = assistente::con_i_codici(get(&dati, "messaggi"));
                let contesto = get(&dati, "contesto").clone();
                let intero = match get(&dati, "mondo") {
                    m if vero(m) => {
                        Value::String(format!("{}\n\n{}", py::testo(&contesto), py::testo(m)))
                    }
                    _ => contesto.clone(),
                };
                let d2 = dati.clone();
                let ask: lavori::Chiedi =
                    Arc::new(move |m: &Motore, livello: &str, conta: bool| {
                        let ctx = if livello == "tutto" {
                            &intero
                        } else {
                            &contesto
                        };
                        assistente::rispondi(
                            m,
                            u,
                            ctx,
                            &messaggi,
                            get(&d2, "immagine"),
                            &Value::String(livello.into()),
                            get(&d2, "ids"),
                            conta,
                        )
                    });
                lavori::catena(&motori, subito, voce, ask)
            },
            k,
        )?;
        return Ok(Risposta::json(
            202,
            &json!({"lavoro": numero, "fila": fila}),
        ));
    }
    if lento {
        // the answer is collected later: see lavori::avvia
        let numero = lavori::avvia(u, move |_| chiedi(), None)?;
        return Ok(Risposta::json(
            202,
            &json!({"lavoro": numero, "motore": "locale"}),
        ));
    }
    let (codice, risposta) = chiedi();
    Ok(Risposta::json(codice, &risposta))
}

fn bilancia(c: &Ctx, metodo: &str, cosa: &str) -> Esito<Risposta> {
    // the scale and the PC listening to it belong to the admin: for the others it is as if always off
    if c.utente().capo == 0 {
        if metodo == "GET" && cosa == "sentinella" {
            return ok(json!({"online": false, "occupata": false}));
        }
        return errore(403, "La bilancia e' collegata a un altro account");
    }
    let domanda = py::parse_qs(&c.req.query);
    let intero = |nome: &str, base: u64, massimo: u64| -> u64 {
        match domanda.get(nome) {
            Some(v) if !v.is_empty() && v.chars().all(|ch| ch.is_ascii_digit()) => {
                v.parse::<u64>().map(|n| n.min(massimo)).unwrap_or(massimo)
            }
            _ => base,
        }
    };
    let p = &c.app.ponte;
    match (metodo, cosa) {
        ("GET", "sentinella") => ok(p.sentinella()),
        ("POST", "richiesta") => ok(p.chiedi(get(&c.corpo()?.1, "profilo"))?),
        ("GET", "stato") => {
            let id = domanda.get("id").cloned().unwrap_or_default();
            ok(p.segui(
                &id,
                intero("dopo", 0, 100000) as usize,
                intero("attesa", 20, 25) as f64,
            ))
        }
        ("POST", "annulla") => ok(p.annulla(get(&c.corpo()?.1, "id"))),
        ("GET", "lavoro") => Ok(match p.prendi(intero("attesa", 25, 30) as f64) {
            Some(l) => Risposta::json(200, &l),
            None => Risposta::testo(204, b""),
        }),
        ("POST", "notizie") => {
            let b = c.corpo()?.1;
            ok(p.riferisci(get(&b, "id"), get(&b, "evento"), get(&b, "esito")))
        }
        _ => Ok(Risposta::json(404, &json!({"errore": "non trovato"}))),
    }
}
