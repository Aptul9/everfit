//! FitAI jobs (assistente.py `avvia`, `ritira`, `catena`): a question becomes a job that the server carries to the
//! end by itself, trying the services one after the other, while the app polls "how far along are you?". If the
//! app is closed meanwhile, the answer waits to be collected and a notification goes out.

use crate::chiavi::Motore;
use crate::conf::conf;
use crate::errore::Problema;
use crate::{ai_gemini, log, py};
use base64::Engine;
use serde_json::{Value, json};
use std::collections::HashMap;
use std::panic::{AssertUnwindSafe, catch_unwind};
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::mpsc;
use std::sync::{Arc, LazyLock, Mutex, OnceLock};
use std::time::Duration;

const LAVORO_TENUTO: f64 = 6.0 * 3600.0;
const MAX_APERTI: usize = 4;
const FIACCO_PER: f64 = 300.0;

/// Where the job is: who is answering, why, and until when it waits; `superato` when a newer question came.
#[derive(Default, Clone)]
pub struct Stato {
    pub chi: Option<String>,
    pub nota: Option<String>,
    pub aspetto: Option<f64>,
    pub superato: bool,
}

pub struct Voce {
    utente: i64,
    inizio: f64,
    chiave: Option<String>,
    pub stato: Mutex<Stato>,
    esito: Mutex<Option<(u16, Value)>>,
    ritirato: AtomicBool,
}

impl Voce {
    pub fn stato(&self) -> std::sync::MutexGuard<'_, Stato> {
        self.stato.lock().unwrap_or_else(|e| e.into_inner())
    }

    fn esito(&self) -> Option<(u16, Value)> {
        self.esito.lock().unwrap_or_else(|e| e.into_inner()).clone()
    }
}

/// What a finished job nobody collected calls: (account, job number, status, answer).
pub type AlTermine = Box<dyn Fn(i64, &str, u16, &Value) + Send + Sync>;

static LAVORI: LazyLock<Mutex<HashMap<String, Arc<Voce>>>> =
    LazyLock::new(|| Mutex::new(HashMap::new()));
static AL_TERMINE: OnceLock<AlTermine> = OnceLock::new();
/// service name -> until when it stays at the back of the queue
static FIACCHI: LazyLock<Mutex<HashMap<String, f64>>> =
    LazyLock::new(|| Mutex::new(HashMap::new()));

pub fn al_termine(f: AlTermine) {
    let _ = AL_TERMINE.set(f);
}

fn lavori() -> std::sync::MutexGuard<'static, HashMap<String, Arc<Voce>>> {
    LAVORI.lock().unwrap_or_else(|e| e.into_inner())
}

fn fiacchi() -> std::sync::MutexGuard<'static, HashMap<String, f64>> {
    FIACCHI.lock().unwrap_or_else(|e| e.into_inner())
}

fn nome(chi: &str) -> String {
    match chi {
        "gemini" => "Gemini",
        "mistral" => "Mistral",
        "anthropic" => "Claude",
        "locale" => "L'AI sulla VM",
        altro => altro,
    }
    .to_string()
}

/// Starts `lavoro(voce)` in the background; it returns (status, answer) and meanwhile writes in `voce.stato` how far
/// it is. Returns the job number. The same `chiave` (the app's mark of the question) resumes the existing job; a new
/// question makes the person's earlier ones stop.
pub fn avvia(
    utente: i64,
    lavoro: impl FnOnce(&Voce) -> (u16, Value) + Send + 'static,
    chiave: Option<String>,
) -> Result<String, Problema> {
    let ora = py::ora();
    let (numero, voce) = {
        let mut l = lavori();
        l.retain(|_, v| ora - v.inizio <= LAVORO_TENUTO);
        if let Some(k) = &chiave
            && let Some((n, _)) = l
                .iter()
                .find(|(_, v)| v.utente == utente && v.chiave.as_ref() == Some(k))
        {
            return Ok(n.clone());
        }
        let aperti: Vec<&Arc<Voce>> = l
            .values()
            .filter(|v| v.utente == utente && v.esito().is_none())
            .collect();
        if aperti.len() >= MAX_APERTI {
            return Err(Problema::new(
                429,
                "Sto ancora rispondendo alle domande di prima: aspetta un momento.",
            ));
        }
        for v in aperti {
            v.stato().superato = true;
        }
        let numero = base64::engine::general_purpose::URL_SAFE_NO_PAD
            .encode(crate::accesso::casuali::<12>());
        let voce = Arc::new(Voce {
            utente,
            inizio: ora,
            chiave,
            stato: Mutex::new(Stato::default()),
            esito: Mutex::new(None),
            ritirato: AtomicBool::new(false),
        });
        l.insert(numero.clone(), voce.clone());
        (numero, voce)
    };
    let n = numero.clone();
    std::thread::spawn(move || {
        let esito = catch_unwind(AssertUnwindSafe(|| lavoro(&voce))).unwrap_or_else(|_| {
            // it must not stay "in progress" forever
            log!("assistente: lavoro fallito (panic)");
            (
                502,
                json!({"errore": "Non sono riuscito a rispondere. Riprova."}),
            )
        });
        *voce.esito.lock().unwrap_or_else(|e| e.into_inner()) = Some(esito.clone());
        // whoever asked is usually there and collects at once; if nobody came after a while (app closed) they are told
        if let Some(f) = AL_TERMINE.get()
            && !voce.stato().superato
        {
            std::thread::sleep(Duration::from_secs(12));
            if !voce.ritirato.load(Ordering::SeqCst)
                && catch_unwind(AssertUnwindSafe(|| f(utente, &n, esito.0, &esito.1))).is_err()
            {
                log!("assistente: avviso non partito (panic)");
            }
        }
    });
    Ok(numero)
}

pub enum Ritiro {
    InCorso(Value),
    Fatto(u16, Value),
}

/// None if that number does not exist or belongs to someone else; while working the progress; then the answer.
pub fn ritira(utente: i64, numero: &str) -> Option<Ritiro> {
    let voce = lavori().get(numero).cloned()?;
    if voce.utente != utente {
        return None;
    }
    match voce.esito() {
        None => {
            let ora = py::ora();
            let s = voce.stato().clone();
            let attesa = s
                .aspetto
                .filter(|a| *a != 0.0)
                .map(|a| py::round_int(a - ora).max(0));
            Some(Ritiro::InCorso(
                json!({"in_corso": true, "secondi": py::int(ora - voce.inizio), "chi": s.chi, "nota": s.nota, "aspetto": attesa}),
            ))
        }
        Some((codice, r)) => {
            voce.ritirato.store(true, Ordering::SeqCst);
            Some(Ritiro::Fatto(codice, r))
        }
    }
}

/// How the chain asks one service: (engine, level "base" | "tutto", whether the question counts for the rate limit).
pub type Chiedi = Arc<dyn Fn(&Motore, &str, bool) -> Result<Value, Problema> + Send + Sync>;

/// One question to the end. `motori` in order: the services with a key and, last, the VM's AI. The first is asked;
/// if it is silent for SPINTA seconds the next is asked too, and so on: the first good answer wins. The VM's AI
/// starts when all services gave up, or after LOCALE_DOPO seconds without answers. If all say "wait", it waits
/// as long as the first asks and goes round once more.
pub fn catena(motori: &[Motore], subito: bool, voce: &Voce, chiedi: Chiedi) -> (u16, Value) {
    let (spinta, locale_dopo) = (conf().spinta_ai, conf().locale_dopo);
    catena_con(motori, subito, voce, chiedi, spinta, locale_dopo)
}

type Arrivo = (String, Result<Value, Problema>);

fn superata() -> (u16, Value) {
    (
        409,
        json!({"errore": "C'e' una domanda piu' nuova: rispondo a quella."}),
    )
}

pub fn catena_con(
    motori: &[Motore],
    subito: bool,
    voce: &Voce,
    chiedi: Chiedi,
    spinta: f64,
    locale_dopo: f64,
) -> (u16, Value) {
    let (tx, rx) = mpsc::channel::<Arrivo>();
    let mut conta = true; // a question counts once, even if several services are asked to answer it
    let mut ultimo: Option<Problema> = None;
    for giro in 0..2 {
        let mut limite: Option<Problema> = None;
        // whoever just fell goes to the back of the queue: no time lost at every question
        let adesso = py::ora();
        let mut in_ordine = motori.to_vec();
        {
            let f = fiacchi();
            in_ordine.sort_by_key(|m| {
                ai_gemini::fermo(&m.nome) || f.get(&m.nome).is_some_and(|t| *t > adesso)
            });
        }
        if let (Some(a), Some(b)) = (in_ordine.first(), motori.first())
            && a.nome != b.nome
        {
            voce.stato().nota = Some(format!("{} non risponde da un po'", nome(&b.nome)));
        }
        let (mut remoti, mut locali): (Vec<Motore>, Vec<Motore>) =
            in_ordine.into_iter().partition(|m| m.nome != "locale");
        remoti.reverse();
        locali.reverse();
        let inizio = py::ora();
        let mut in_corso = 0usize;
        let parti = |m: Motore, conta: &mut bool, in_corso: &mut usize| {
            let (tx, chiedi, c) = (tx.clone(), chiedi.clone(), *conta);
            voce.stato().chi = Some(m.nome.clone());
            *conta = false;
            *in_corso += 1;
            std::thread::spawn(move || {
                let chi = m.nome.clone();
                let esito = catch_unwind(AssertUnwindSafe(|| -> Result<Value, Problema> {
                    let mut r = chiedi(
                        &m,
                        if subito && chi != "locale" {
                            "tutto"
                        } else {
                            "base"
                        },
                        c,
                    )?;
                    if py::vero(py::get(&r, "serve")) && chi != "locale" {
                        r = chiedi(&m, "tutto", false)?;
                    }
                    if py::vero(py::get(&r, "serve")) {
                        return Err(Problema::new(
                            502,
                            "Non sono riuscito a rispondere. Riprova.",
                        ));
                    }
                    Ok(r)
                }))
                .unwrap_or_else(|_| {
                    // a program error inside one service must not stop the others
                    log!("assistente: {} si e' rotto (panic)", chi);
                    Err(Problema::new(
                        502,
                        "Non sono riuscito a rispondere. Riprova.",
                    ))
                });
                let _ = tx.send((chi, esito));
            });
        };
        // starts the next in the queue: a service, or the VM's AI when all services gave up (`forza`) or are silent
        let il_prossimo = |forza: bool,
                           conta: &mut bool,
                           in_corso: &mut usize,
                           remoti: &mut Vec<Motore>,
                           locali: &mut Vec<Motore>| {
            if let Some(m) = remoti.pop() {
                parti(m, conta, in_corso);
                return true;
            }
            if !locali.is_empty()
                && (forza || *in_corso == 0 || py::ora() - inizio >= locale_dopo)
                && let Some(m) = locali.pop()
            {
                parti(m, conta, in_corso);
                return true;
            }
            false
        };
        let forza = remoti.is_empty();
        il_prossimo(forza, &mut conta, &mut in_corso, &mut remoti, &mut locali);
        while in_corso > 0 {
            if voce.stato().superato {
                return superata();
            }
            let attesa = if !remoti.is_empty() {
                spinta
            } else if !locali.is_empty() {
                (locale_dopo - (py::ora() - inizio)).max(0.5)
            } else {
                5.0
            };
            let (chi, esito) = match rx.recv_timeout(crate::ai_http::durata(attesa)) {
                Ok(a) => a,
                Err(_) => {
                    let lento = voce.stato().chi.clone().unwrap_or_default();
                    if il_prossimo(false, &mut conta, &mut in_corso, &mut remoti, &mut locali) {
                        let ora_chi = voce.stato().chi.clone().unwrap_or_default();
                        voce.stato().nota = Some(format!(
                            "{} ci mette troppo: chiedo anche a {}",
                            nome(&lento),
                            nome(&ora_chi)
                        ));
                    }
                    continue;
                }
            };
            in_corso -= 1;
            let e = match esito {
                Ok(r) => {
                    fiacchi().remove(&chi);
                    return (200, r);
                }
                Err(e) => e,
            };
            if e.per_tutti() {
                return (e.codice, json!({"errore": e.testo})); // a wrong question (or too many) is wrong for all
            }
            fiacchi().insert(chi.clone(), py::ora() + FIACCO_PER);
            if e.remoto == Some(429) && !e.giornaliero && limite.is_none() {
                limite = Some(e.clone());
            }
            let perche = e.perche.clone().unwrap_or_else(|| {
                if e.giornaliero {
                    "ha finito le richieste di oggi"
                } else if e.remoto == Some(429) {
                    "ha troppe richieste in questo momento"
                } else {
                    "non risponde"
                }
                .to_string()
            });
            voce.stato().nota = Some(format!("{} {}", nome(&chi), perche));
            ultimo = Some(e);
            let forza = remoti.is_empty() && in_corso == 0;
            il_prossimo(forza, &mut conta, &mut in_corso, &mut remoti, &mut locali);
        }
        let Some(limite) = limite.filter(|_| giro == 0) else {
            break;
        };
        let attesa = (limite
            .attesa
            .filter(|a| *a != 0.0)
            .map(py::int)
            .unwrap_or(20))
        .clamp(5, 60) as f64;
        let fino = py::ora() + attesa;
        {
            let mut s = voce.stato();
            s.chi = None;
            s.nota = None;
            s.aspetto = Some(fino);
        }
        while py::ora() < fino {
            if voce.stato().superato {
                return superata();
            }
            std::thread::sleep(Duration::from_secs(1));
        }
        voce.stato().aspetto = None;
    }
    let codice = if ultimo.as_ref().is_some_and(|u| u.remoto == Some(429)) {
        429
    } else {
        502
    };
    (
        codice,
        json!({"errore": ultimo.map(|u| u.testo).unwrap_or_else(|| "Non sono riuscito a rispondere. Riprova.".into())}),
    )
}

#[cfg(test)]
mod test {
    //! prova_catena.py: fake services that answer, stay silent, give up or break.
    use super::*;
    use std::sync::Mutex as M;
    use std::time::Instant;

    #[derive(Clone)]
    enum Copione {
        Risponde(f64),
        Muto(f64),
        Basta(Problema),
        Rotto,
    }

    static SERIALE: M<()> = M::new(());

    fn motori() -> Vec<Motore> {
        vec![
            Motore::uno("gemini", "k"),
            Motore::uno("mistral", "k"),
            Motore::uno("locale", ""),
        ]
    }

    fn voce() -> Voce {
        Voce {
            utente: 1,
            inizio: py::ora(),
            chiave: None,
            stato: Mutex::new(Stato::default()),
            esito: Mutex::new(None),
            ritirato: AtomicBool::new(false),
        }
    }

    fn finto(
        copione: HashMap<&'static str, Copione>,
        chiamati: Arc<M<Vec<(String, bool)>>>,
    ) -> Chiedi {
        Arc::new(move |m: &Motore, _liv: &str, conta: bool| {
            chiamati.lock().unwrap().push((m.nome.clone(), conta));
            match copione[m.nome.as_str()].clone() {
                Copione::Risponde(s) => {
                    std::thread::sleep(Duration::from_secs_f64(s));
                    Ok(json!({"testo": format!("risposta di {}", m.nome), "motore": m.nome}))
                }
                Copione::Muto(s) => {
                    std::thread::sleep(Duration::from_secs_f64(s));
                    Err(Problema::new(
                        502,
                        "Il servizio di AI non risponde. Riprova tra poco.",
                    ))
                }
                Copione::Basta(e) => Err(e),
                Copione::Rotto => panic!("rotto"),
            }
        })
    }

    fn gira(g: Copione, m: Copione, l: Copione) -> (u16, Value, f64, Vec<String>, Stato) {
        fiacchi().clear();
        let chiamati = Arc::new(M::new(Vec::new()));
        let v = voce();
        let inizio = Instant::now();
        let (c, j) = catena_con(
            &motori(),
            false,
            &v,
            finto(
                HashMap::from([("gemini", g), ("mistral", m), ("locale", l)]),
                chiamati.clone(),
            ),
            0.3,
            1.2,
        );
        let chi = chiamati
            .lock()
            .unwrap()
            .iter()
            .map(|x| x.0.clone())
            .collect();
        (c, j, inizio.elapsed().as_secs_f64(), chi, v.stato().clone())
    }

    fn remoto(codice: u16, r: i64) -> Problema {
        Problema {
            codice,
            testo: "x".into(),
            remoto: Some(r),
            ..Default::default()
        }
    }

    #[test]
    fn come_prova_catena() {
        let _s = SERIALE.lock().unwrap();
        use Copione::*;
        let (c, j, _, chi, _) = gira(Risponde(0.05), Risponde(0.05), Risponde(0.05));
        assert!(c == 200 && j["motore"] == "gemini" && chi == ["gemini"]);
        let (c, j, d, chi, st) = gira(Muto(3.0), Risponde(0.1), Risponde(0.1));
        assert!(c == 200 && j["motore"] == "mistral" && chi == ["gemini", "mistral"] && d < 1.0);
        assert!(
            st.nota
                .unwrap_or_default()
                .contains("chiedo anche a Mistral")
        );
        let (c, j, d, _, _) = gira(Basta(remoto(429, 429)), Risponde(0.05), Risponde(0.05));
        assert!(c == 200 && j["motore"] == "mistral" && d < 0.25);
        let (c, j, d, _, _) = gira(
            Basta(remoto(502, 503)),
            Basta(remoto(502, 500)),
            Risponde(0.05),
        );
        assert!(c == 200 && j["motore"] == "locale" && d < 0.5);
        let (c, j, d, _, _) = gira(Muto(5.0), Muto(5.0), Risponde(0.05));
        assert!(
            c == 200 && j["motore"] == "locale" && 1.1 < d && d < 2.0,
            "{d}"
        );
        let (c, j, _, _, _) = gira(Rotto, Risponde(0.05), Risponde(0.05));
        assert!(c == 200 && j["motore"] == "mistral");
        let (c, _, _, chi, _) = gira(
            Basta(Problema::new(400, "manca la domanda")),
            Risponde(0.05),
            Risponde(0.05),
        );
        assert!(c == 400 && chi == ["gemini"]);
        let (c, j, _, chi, _) = gira(Muto(0.05), Muto(0.05), Muto(0.05));
        assert!(c == 502 && chi == ["gemini", "mistral", "locale"] && j.get("errore").is_some());

        // every question counts once; whoever just fell goes to the back
        fiacchi().clear();
        let chiamati = Arc::new(M::new(Vec::new()));
        let copione = HashMap::from([
            ("gemini", Muto(3.0)),
            ("mistral", Risponde(0.05)),
            ("locale", Risponde(0.05)),
        ]);
        catena_con(
            &motori(),
            false,
            &voce(),
            finto(copione, chiamati.clone()),
            0.3,
            1.2,
        );
        assert_eq!(
            chiamati
                .lock()
                .unwrap()
                .iter()
                .map(|x| x.1)
                .collect::<Vec<_>>(),
            [true, false]
        );
        let copione = HashMap::from([
            ("gemini", Basta(remoto(502, 503))),
            ("mistral", Risponde(0.05)),
            ("locale", Risponde(0.05)),
        ]);
        catena_con(
            &motori(),
            false,
            &voce(),
            finto(copione, Arc::new(M::new(Vec::new()))),
            0.3,
            1.2,
        );
        let chiamati = Arc::new(M::new(Vec::new()));
        let copione = HashMap::from([
            ("gemini", Risponde(0.05)),
            ("mistral", Risponde(0.05)),
            ("locale", Risponde(0.05)),
        ]);
        let (_, j) = catena_con(
            &motori(),
            false,
            &voce(),
            finto(copione, chiamati.clone()),
            0.3,
            1.2,
        );
        assert!(chiamati.lock().unwrap()[0].0 == "mistral" && j["motore"] == "mistral");
    }

    #[test]
    fn superata_smette_subito() {
        let _s = SERIALE.lock().unwrap();
        fiacchi().clear();
        let v = Arc::new(voce());
        let v2 = v.clone();
        std::thread::spawn(move || {
            std::thread::sleep(Duration::from_millis(400));
            v2.stato().superato = true;
        });
        let inizio = Instant::now();
        let copione = HashMap::from([
            ("gemini", Copione::Muto(3.0)),
            ("mistral", Copione::Muto(3.0)),
            ("locale", Copione::Muto(3.0)),
        ]);
        let (c, _) = catena_con(
            &motori(),
            false,
            &v,
            finto(copione, Arc::new(M::new(Vec::new()))),
            0.3,
            1.2,
        );
        assert!(c == 409 && inizio.elapsed().as_secs_f64() < 1.5);
    }

    #[test]
    fn avvia_e_ritira() {
        let (tx, rx) = mpsc::channel::<()>();
        let primo = avvia(
            7,
            move |_| {
                let _ = rx.recv_timeout(Duration::from_secs(3));
                (200, json!({"testo": "a"}))
            },
            Some("q1".into()),
        )
        .unwrap();
        let di_nuovo = avvia(
            7,
            |_| (200, json!({"testo": "doppione"})),
            Some("q1".into()),
        )
        .unwrap();
        assert_eq!(primo, di_nuovo);
        let secondo = avvia(7, |_| (200, json!({"testo": "b"})), Some("q2".into())).unwrap();
        assert_ne!(secondo, primo);
        assert!(lavori()[&primo].stato().superato);
        let _ = tx.send(());
        std::thread::sleep(Duration::from_millis(200));
        assert!(
            matches!(ritira(7, &secondo), Some(Ritiro::Fatto(200, ref v)) if v == &json!({"testo": "b"}))
        );
        assert!(ritira(8, &secondo).is_none());
    }
}
