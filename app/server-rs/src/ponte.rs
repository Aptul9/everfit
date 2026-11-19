//! Bridge between the phone and the scale (ponte.py): the phone asks the server for a weighing, the watcher on the
//! home PC picks it up, runs the scale and reports step by step. All in memory, one request at a time.

use crate::errore::{Esito, Problema};
use crate::log;
use serde_json::{Value, json};
use std::sync::{Condvar, Mutex};
use std::time::Duration;

pub const VIVA: f64 = 45.0;
pub const PRESA_ENTRO: f64 = 12.0;
pub const SILENZIO: f64 = 150.0;

pub const PC_ASSENTE: &str = "Il PC di casa che collega la bilancia non risponde. Di solito riparte da solo entro un minuto: riprova, \
oppure segna il peso a mano. Se sali sulla bilancia adesso, la pesata resta nella sua memoria e la recupero alla prossima.";

struct Lavoro {
    id: String,
    profilo: Value,
    eventi: Vec<Value>,
    esito: Option<Value>,
    presa: bool,
    annullata: bool,
    creata: f64,
    notizie: f64,
}

struct Stato {
    vista: f64,
    lavoro: Option<Lavoro>,
    assente: bool,
}

pub struct Ponte {
    st: Mutex<Stato>,
    cv: Condvar,
    orologio: fn() -> f64,
}

impl Default for Ponte {
    fn default() -> Self {
        Ponte::con_orologio(crate::py::ora)
    }
}

impl Ponte {
    pub fn con_orologio(orologio: fn() -> f64) -> Self {
        // right after a restart the watcher is assumed present: it reconnects within seconds
        Ponte {
            st: Mutex::new(Stato {
                vista: orologio(),
                lavoro: None,
                assente: false,
            }),
            cv: Condvar::new(),
            orologio,
        }
    }

    fn ora(&self) -> f64 {
        (self.orologio)()
    }

    fn lock(&self) -> std::sync::MutexGuard<'_, Stato> {
        self.st.lock().unwrap_or_else(|e| e.into_inner())
    }

    fn in_corso(&self, s: &Stato) -> bool {
        s.lavoro
            .as_ref()
            .is_some_and(|l| l.esito.is_none() && l.presa && self.ora() - l.notizie < 20.0)
    }

    /// The watcher has just been heard. If it had vanished, the log says for how long.
    fn si_sente(&self, s: &mut Stato) -> f64 {
        let ora = self.ora();
        if ora - s.vista >= VIVA {
            log!(
                "bilancia: la sentinella e' tornata dopo {} s di silenzio",
                crate::py::int(ora - s.vista)
            );
        }
        s.vista = ora;
        s.assente = false;
        ora
    }

    pub fn sentinella(&self) -> Value {
        let mut s = self.lock();
        let ora = self.ora();
        let online = ora - s.vista < VIVA;
        if !online && !s.assente {
            s.assente = true;
            log!(
                "bilancia: il telefono la cerca e la sentinella non si sente da {} s",
                crate::py::int(ora - s.vista)
            );
        }
        json!({"online": online, "occupata": self.in_corso(&s)})
    }

    // ---- from the phone
    pub fn chiedi(&self, profilo: &Value) -> Esito<Value> {
        let mut s = self.lock();
        if self.ora() - s.vista >= VIVA {
            return Err(Problema::new(503, PC_ASSENTE));
        }
        if self.in_corso(&s) {
            return Err(Problema::new(
                409,
                "C'e' gia' una pesata in corso: aspetta che finisca.",
            ));
        }
        let ora = self.ora();
        let id = hex::encode(crate::accesso::casuali::<6>());
        s.lavoro = Some(Lavoro {
            id: id.clone(),
            profilo: if profilo.is_object() {
                profilo.clone()
            } else {
                json!({})
            },
            eventi: vec![],
            esito: None,
            presa: false,
            annullata: false,
            creata: ora,
            notizie: ora,
        });
        self.cv.notify_all();
        Ok(json!({"id": id}))
    }

    pub fn segui(&self, ident: &str, dopo: usize, attesa: f64) -> Value {
        let fine = self.ora() + attesa;
        let mut s = self.lock();
        loop {
            let ora = self.ora();
            let Some(l) = s.lavoro.as_mut().filter(|l| l.id == ident) else {
                return json!({"eventi": [], "prossimo": dopo, "esito": {"ok": false, "errore": "Pesata scaduta: riprova."}});
            };
            if l.esito.is_none() {
                if !l.presa && ora - l.creata > PRESA_ENTRO {
                    l.esito = Some(json!({"ok": false, "errore": PC_ASSENTE}));
                } else if l.presa && ora - l.notizie > SILENZIO {
                    l.esito = Some(
                        json!({"ok": false, "errore": "Il PC ha smesso di rispondere a meta' pesata. Riprova."}),
                    );
                }
            }
            if l.eventi.len() > dopo || l.esito.is_some() {
                let eventi: Vec<Value> = l.eventi.iter().skip(dopo).cloned().collect();
                return json!({"eventi": eventi, "prossimo": l.eventi.len(), "esito": l.esito.clone().unwrap_or(Value::Null)});
            }
            if ora >= fine {
                return json!({"eventi": [], "prossimo": dopo, "esito": null});
            }
            s = self
                .cv
                .wait_timeout(s, Duration::from_secs_f64((fine - ora).min(2.0)))
                .unwrap_or_else(|e| e.into_inner())
                .0;
        }
    }

    pub fn annulla(&self, ident: &Value) -> Value {
        let mut s = self.lock();
        if let Some(l) = s.lavoro.as_mut()
            && ident.as_str() == Some(l.id.as_str())
            && l.esito.is_none()
        {
            l.annullata = true;
            l.esito = Some(json!({"ok": false, "annullata": true, "errore": "Pesata annullata."}));
            self.cv.notify_all();
        }
        json!({"ok": true})
    }

    // ---- from the watcher
    pub fn prendi(&self, attesa: f64) -> Option<Value> {
        let fine = self.ora() + attesa;
        let mut s = self.lock();
        loop {
            let ora = self.si_sente(&mut s);
            if let Some(l) = s.lavoro.as_mut()
                && !l.presa
                && l.esito.is_none()
            {
                l.presa = true;
                l.notizie = ora;
                let r = json!({"id": l.id, "profilo": l.profilo});
                self.cv.notify_all();
                return Some(r);
            }
            if ora >= fine {
                return None;
            }
            s = self
                .cv
                .wait_timeout(s, Duration::from_secs_f64((fine - ora).min(5.0)))
                .unwrap_or_else(|e| e.into_inner())
                .0;
        }
    }

    pub fn riferisci(&self, ident: &Value, evento: &Value, esito: &Value) -> Value {
        let mut s = self.lock();
        let ora = self.si_sente(&mut s);
        let Some(l) = s
            .lavoro
            .as_mut()
            .filter(|l| ident.as_str() == Some(l.id.as_str()))
        else {
            return json!({"annullata": true});
        };
        l.notizie = ora;
        if evento.is_object() && l.eventi.len() < 2000 {
            let fase = crate::py::taglia(&crate::py::testo(crate::py::get(evento, "fase")), 20);
            l.eventi
                .push(json!({"fase": fase, "kg": crate::py::get(evento, "kg")}));
        }
        if esito.is_object() && l.esito.is_none() {
            l.esito = Some(esito.clone());
        }
        let annullata = l.annullata;
        self.cv.notify_all();
        json!({"annullata": annullata})
    }
}

#[cfg(test)]
mod test {
    //! prova_ponte.py, same checks with a fake clock
    use super::*;
    use std::sync::atomic::{AtomicU64, Ordering};

    static ORA: AtomicU64 = AtomicU64::new(1_000_000);
    fn orologio() -> f64 {
        ORA.load(Ordering::SeqCst) as f64
    }
    fn avanti(s: u64) {
        ORA.fetch_add(s, Ordering::SeqCst);
    }

    #[test]
    fn ponte_come_prova_ponte() {
        let p = Ponte::con_orologio(orologio);
        assert_eq!(p.sentinella()["online"], true);
        avanti(VIVA as u64 - 1);
        assert_eq!(p.sentinella()["online"], true);
        avanti(2);
        assert_eq!(p.sentinella()["online"], false);
        avanti(100);
        p.prendi(0.0);
        assert_eq!(p.sentinella()["online"], true);
        let lavoro = p.chiedi(&json!({"sesso": "m"})).unwrap();
        let preso = p.prendi(0.0).unwrap();
        assert_eq!(preso["id"], lavoro["id"]);
        avanti(30);
        p.riferisci(&lavoro["id"], &json!({"fase": "cerca"}), &Value::Null);
        avanti(30);
        assert_eq!(p.sentinella()["online"], true);
        p.riferisci(
            &lavoro["id"],
            &Value::Null,
            &json!({"ok": true, "peso": 61.2}),
        );
        assert_eq!(
            p.segui(lavoro["id"].as_str().unwrap(), 0, 0.0)["esito"]["peso"],
            61.2
        );
        avanti(VIVA as u64 + 5);
        let e = p.chiedi(&json!({})).unwrap_err();
        assert!(e.codice == 503 && e.testo.contains("riparte da solo"));
    }
}
