//! The database (server.py, `Dati`): same schema, same migrations, same rows, so a fit.db made by the Python
//! server opens here unchanged and the other way round.

use crate::accesso;
use crate::errore::{Esito, Problema, errore};
use crate::log;
use crate::py;
use rusqlite::types::ValueRef;
use rusqlite::{Connection, OptionalExtension, Row, Transaction, TransactionBehavior, params};
use serde_json::{Map, Value};
use std::collections::HashSet;
use std::path::{Path, PathBuf};
use std::sync::Mutex;
use std::time::Duration;

pub const GIORNI_STORIA: i64 = 30;
pub const GIORNI_PRODOTTO: f64 = 60.0;
pub const MAX_PERSONE: i64 = 30;

const SCHEMA: &str = include_str!("../testi/schema.sql");
/// the tables that had a single owner before accounts: at start they all go to the admin
const DI_UNO: [&str; 4] = ["stato", "stato_storia", "pesate", "circonferenze"];

/// `_scrittura`: one writer at a time, as in Python
static SCRITTURA: Mutex<()> = Mutex::new(());

#[derive(Debug, Clone)]
pub struct Utente {
    pub id: i64,
    pub nome: String,
    pub capo: i64,
    pub utente: Option<String>,
}

impl Utente {
    fn da_riga(r: &Row) -> rusqlite::Result<Self> {
        Ok(Utente {
            id: r.get("id")?,
            nome: r.get("nome")?,
            capo: r.get("capo")?,
            utente: r.get("utente")?,
        })
    }
}

pub struct Dati {
    pub cartella: PathBuf,
    pub percorso: PathBuf,
    pub piani: PathBuf,
    pub segreto: String,
    pool: Mutex<Vec<Connection>>,
}

/// A connection borrowed from the pool, given back when dropped.
pub struct Con<'a> {
    c: Option<Connection>,
    d: &'a Dati,
}

impl std::ops::Deref for Con<'_> {
    type Target = Connection;
    #[expect(
        clippy::expect_used,
        reason = "`c` is only taken in drop, after the last use"
    )]
    fn deref(&self) -> &Connection {
        self.c.as_ref().expect("connection in use")
    }
}

impl std::ops::DerefMut for Con<'_> {
    #[expect(
        clippy::expect_used,
        reason = "`c` is only taken in drop, after the last use"
    )]
    fn deref_mut(&mut self) -> &mut Connection {
        self.c.as_mut().expect("connection in use")
    }
}

impl Drop for Con<'_> {
    fn drop(&mut self) {
        if let Some(c) = self.c.take() {
            let mut p = self.d.pool.lock().unwrap_or_else(|e| e.into_inner());
            if p.len() < 8 {
                p.push(c);
            }
        }
    }
}

/// `dict(row)`: column name -> value, in column order.
pub fn riga(r: &Row) -> Map<String, Value> {
    let st = r.as_ref();
    let mut m = Map::new();
    for i in 0..st.column_count() {
        let nome = st.column_name(i).unwrap_or("").to_string();
        let v = match r.get_ref(i) {
            Ok(ValueRef::Null) | Err(_) => Value::Null,
            Ok(ValueRef::Integer(n)) => Value::from(n),
            Ok(ValueRef::Real(f)) => py::n_f(f),
            Ok(ValueRef::Text(t)) | Ok(ValueRef::Blob(t)) => {
                Value::String(String::from_utf8_lossy(t).into_owned())
            }
        };
        m.insert(nome, v);
    }
    m
}

pub fn righe(
    c: &Connection,
    sql: &str,
    p: impl rusqlite::Params,
) -> Esito<Vec<Map<String, Value>>> {
    let mut st = c.prepare(sql)?;
    let mut fuori = Vec::new();
    let mut rs = st.query(p)?;
    while let Some(r) = rs.next()? {
        fuori.push(riga(r));
    }
    Ok(fuori)
}

fn colonne(c: &Connection, tabella: &str) -> Esito<Vec<String>> {
    let mut st = c.prepare(&format!("PRAGMA table_info({tabella})"))?;
    let v = st
        .query_map([], |r| r.get::<_, String>(1))?
        .collect::<Result<Vec<_>, _>>()?;
    Ok(v)
}

impl Dati {
    pub fn new(cartella: &Path, piani: PathBuf) -> Esito<Dati> {
        std::fs::create_dir_all(cartella).map_err(|e| Problema::new(500, e.to_string()))?;
        let mut d = Dati {
            cartella: cartella.to_path_buf(),
            percorso: cartella.join("fit.db"),
            piani,
            segreto: String::new(),
            pool: Mutex::new(Vec::new()),
        };
        let segreto = {
            let mut c = d.con()?;
            // all or nothing: if the move to accounts breaks halfway, nothing is left behind
            let tx = Transaction::new(&mut c, TransactionBehavior::Immediate)?;
            prepara(&tx)?;
            let segreto: String = tx.query_row(
                "SELECT valore FROM impostazioni WHERE chiave = 'segreto'",
                [],
                |r| r.get(0),
            )?;
            let conf = crate::conf::conf();
            let codice = if conf.acceso {
                accesso::firma(&segreto, &conf.codice_capo)
            } else {
                "nessuno".to_string()
            };
            tx.execute(
                "INSERT OR IGNORE INTO utenti (id, nome, codice, capo) VALUES (?, ?, ?, 1)",
                params![accesso::CAPO, conf.nome_capo, codice],
            )?;
            tx.execute(
                "UPDATE utenti SET codice = ? WHERE id = ?",
                params![codice, accesso::CAPO],
            )?;
            tx.execute(
                "UPDATE utenti SET utente = ? WHERE id = ? AND utente IS NULL",
                params![conf.utente_capo, accesso::CAPO],
            )?;
            tx.execute(
                "DELETE FROM sessioni WHERE vista < ?",
                params![py::ora() - accesso::DURATA as f64],
            )?;
            tx.commit()?;
            segreto
        };
        d.segreto = segreto;
        d.importa_vecchio_stato();
        Ok(d)
    }

    /// Opens (or reuses) a connection: WAL, synchronous NORMAL, 15 s busy timeout like `sqlite3.connect(timeout=15)`.
    pub fn con(&self) -> Esito<Con<'_>> {
        let c = self.pool.lock().unwrap_or_else(|e| e.into_inner()).pop();
        let c = match c {
            Some(c) => c,
            None => {
                let c = Connection::open(&self.percorso)?;
                c.busy_timeout(Duration::from_secs(15))?;
                let _: String = c.query_row("PRAGMA journal_mode=WAL", [], |r| r.get(0))?;
                c.execute_batch("PRAGMA synchronous=NORMAL")?;
                c
            }
        };
        Ok(Con {
            c: Some(c),
            d: self,
        })
    }

    /// `with self.apri() as db:` for reading
    pub fn leggi<T>(&self, f: impl FnOnce(&Connection) -> Esito<T>) -> Esito<T> {
        let c = self.con()?;
        f(&c)
    }

    /// `with _scrittura, self.apri() as db:`: one transaction, committed if `f` succeeds
    pub fn scrivi<T>(&self, f: impl FnOnce(&Transaction) -> Esito<T>) -> Esito<T> {
        let _g = SCRITTURA.lock().unwrap_or_else(|e| e.into_inner());
        let mut c = self.con()?;
        let tx = c.transaction()?;
        let r = f(&tx)?;
        tx.commit()?;
        Ok(r)
    }

    /// Before the database the state lived in state.json: it is brought in once.
    fn importa_vecchio_stato(&self) {
        let vecchio = self.cartella.join("state.json");
        if !vecchio.exists() {
            return;
        }
        let esito = (|| -> Result<(), String> {
            let byte = std::fs::read(&vecchio).map_err(|e| e.to_string())?;
            let testo = String::from_utf8(byte).map_err(|e| e.to_string())?;
            let dati: Value = serde_json::from_str(&testo).map_err(|e| e.to_string())?;
            self.scrivi(|db| {
                let c_e = db
                    .query_row(
                        "SELECT 1 FROM stato WHERE utente = ?",
                        [accesso::CAPO],
                        |_| Ok(()),
                    )
                    .optional()?
                    .is_some();
                if !c_e && dati.as_object().is_some_and(|o| !o.is_empty()) {
                    let agg = py::float(py::o(py::get(&dati, "updatedAt"), &Value::from(0)))
                        .unwrap_or(0.0);
                    db.execute(
                        "INSERT INTO stato (utente, aggiornato, json) VALUES (?, ?, ?)",
                        params![accesso::CAPO, agg, testo],
                    )?;
                }
                Ok(())
            })
            .map_err(|e| e.testo)?;
            let mut nuovo = vecchio.clone().into_os_string();
            nuovo.push(".importato");
            std::fs::rename(&vecchio, nuovo).map_err(|e| e.to_string())
        })();
        if let Err(e) = esito {
            log!("stato vecchio non importato: {}", e);
        }
    }

    // ---- accounts and devices
    pub fn utente(&self, ident: i64) -> Esito<Option<Utente>> {
        self.leggi(|db| {
            Ok(db
                .query_row(
                    "SELECT id, nome, capo, utente FROM utenti WHERE id = ?",
                    [ident],
                    Utente::da_riga,
                )
                .optional()?)
        })
    }

    /// The account matching username and password, or None. Without a username only the admin code counts.
    pub fn entra(&self, nome: &str, segreto: &str) -> Esito<Option<Utente>> {
        let nome = nome.trim().to_lowercase();
        if segreto.is_empty() {
            return Ok(None);
        }
        let del_capo = accesso::firma(&self.segreto, &accesso::pulisci_codice(segreto));
        type Riga = (Utente, Option<String>, String);
        let r: Option<Riga> = self.leggi(|db| {
            if nome.is_empty() {
                return Ok(db
                    .query_row(
                        "SELECT id, nome, capo, utente FROM utenti WHERE codice = ? AND capo = 1",
                        [&del_capo],
                        Utente::da_riga,
                    )
                    .optional()?
                    .map(|u| (u, None, String::new())));
            }
            Ok(db
                .query_row(
                    "SELECT id, nome, capo, utente, password, codice FROM utenti WHERE utente = ?",
                    [&nome],
                    |r| {
                        Ok((
                            Utente::da_riga(r)?,
                            r.get::<_, Option<String>>("password")?,
                            r.get::<_, String>("codice")?,
                        ))
                    },
                )
                .optional()?)
        })?;
        if nome.is_empty() {
            return Ok(r.map(|(u, _, _)| u));
        }
        let Some((u, password, codice)) = r else {
            accesso::combacia(segreto, &accesso::FINTO); // same time as when the username exists
            return Ok(None);
        };
        let pw = password.as_deref().filter(|p| !p.is_empty());
        if pw.is_some_and(|p| accesso::combacia(segreto, p))
            || (u.capo != 0 && accesso::uguali(&codice, &del_capo))
        {
            return Ok(Some(u));
        }
        Ok(None)
    }

    /// The account this cookie (or this "casa" key) belongs to, or None.
    pub fn sessione(&self, gettone: &str, tipo: &str) -> Esito<Option<Utente>> {
        if gettone.is_empty() {
            return Ok(None);
        }
        let imp = accesso::impronta(gettone);
        let r = self.leggi(|db| {
            Ok(db
                .query_row(
                    "SELECT u.id, u.nome, u.capo, u.utente, s.vista FROM sessioni s JOIN utenti u ON u.id = s.utente \
                     WHERE s.impronta = ? AND s.tipo = ?",
                    params![imp, tipo],
                    |r| Ok((Utente::da_riga(r)?, r.get::<_, f64>("vista")?)),
                )
                .optional()?)
        })?;
        let Some((u, vista)) = r else { return Ok(None) };
        if py::ora() - vista > 3600.0 {
            // "last seen": updating it once in a while is enough
            self.scrivi(|db| {
                db.execute(
                    "UPDATE sessioni SET vista = ? WHERE impronta = ?",
                    params![py::ora(), imp],
                )?;
                db.execute(
                    "UPDATE utenti SET visto = datetime('now', 'localtime') WHERE id = ?",
                    [u.id],
                )?;
                Ok(())
            })?;
        }
        Ok(Some(u))
    }

    pub fn apri_sessione(
        &self,
        utente: i64,
        tipo: &str,
        gettone: Option<String>,
        da: Option<String>,
    ) -> Esito<String> {
        let gettone = gettone.unwrap_or_else(accesso::nuovo_gettone);
        let ora = py::ora();
        self.scrivi(|db| {
            db.execute(
                "INSERT OR IGNORE INTO sessioni (impronta, utente, tipo, da, creata, vista) VALUES (?, ?, ?, ?, ?, ?)",
                params![accesso::impronta(&gettone), utente, tipo, da, ora, ora],
            )?;
            db.execute("UPDATE utenti SET visto = datetime('now', 'localtime') WHERE id = ?", [utente])?;
            Ok(())
        })?;
        Ok(gettone)
    }

    fn casa(&self, utente: i64, seme: &str) -> String {
        py::taglia(
            &accesso::firma(&self.segreto, &format!("casa:{utente}:{seme}")),
            48,
        )
    }

    /// The key the Home screen icon carries in its start address: always the same for the same cookie.
    pub fn chiave_casa(&self, utente: i64, seme: &str) -> Esito<String> {
        let k = self.casa(utente, seme);
        if self.sessione(&k, "casa")?.is_none() {
            self.apri_sessione(utente, "casa", Some(k.clone()), None)?;
        }
        Ok(k)
    }

    /// Leaves this device: away the cookie, the key it came from and the key born from it.
    pub fn chiudi_sessione(&self, utente: i64, gettone: &str) -> Esito<()> {
        let imp = accesso::impronta(gettone);
        let casa = accesso::impronta(&self.casa(utente, gettone));
        self.scrivi(|db| {
            let da: Option<String> = db
                .query_row("SELECT da FROM sessioni WHERE impronta = ?", [&imp], |r| {
                    r.get(0)
                })
                .optional()?
                .flatten();
            db.execute(
                "DELETE FROM sessioni WHERE impronta IN (?, ?, ?)",
                params![imp, da.unwrap_or_default(), casa],
            )?;
            Ok(())
        })
    }

    /// The list for whoever runs the app: when and how much each person uses it, never what.
    pub fn persone(&self) -> Esito<Vec<Value>> {
        let utc = |v: &Value| match v.as_str() {
            Some(s) if !s.is_empty() => Value::String(s.replace(' ', "T") + "Z"),
            _ => Value::Null,
        };
        let righe = self.leggi(|db| {
            righe(
                db,
                "SELECT u.id, u.nome, u.utente, u.capo, u.creato, u.visto, \
                 (SELECT COUNT(*) FROM sessioni s WHERE s.utente = u.id AND s.tipo = 'cookie') AS dispositivi, \
                 (SELECT MAX(s.vista) FROM sessioni s WHERE s.utente = u.id AND s.tipo != 'passi') AS vista, \
                 (SELECT COUNT(*) FROM pesate p WHERE p.utente = u.id) AS pesate, \
                 (SELECT MAX(p.giorno) FROM pesate p WHERE p.utente = u.id) AS ultima_pesata, \
                 (SELECT st.aggiornato FROM stato st WHERE st.utente = u.id) AS attivo, \
                 (SELECT st.json FROM stato st WHERE st.utente = u.id) AS json \
                 FROM utenti u ORDER BY u.id",
                [],
            )
        })?;
        let mut fuori = Vec::new();
        for mut p in righe {
            let json = p.shift_remove("json").unwrap_or(Value::Null);
            let stato: Value =
                serde_json::from_str(json.as_str().filter(|s| !s.is_empty()).unwrap_or("{}"))
                    .unwrap_or_else(|_| Value::Object(Map::new()));
            let giorni_v = py::get(&stato, "giorni");
            let mut giorni: Vec<String> = Vec::new();
            let mut contati = 0;
            if let Some(g) = giorni_v.as_object() {
                for (k, v) in g {
                    if v.is_object()
                        && (py::vero(py::get(v, "pasti")) || py::vero(py::get(v, "extra")))
                    {
                        giorni.push(k.clone());
                    }
                    if v.is_object() && py::get(v, "gym") == &Value::Bool(true) {
                        contati += 1;
                    }
                }
            }
            giorni.sort();
            let sedute = match py::get(&stato, "sedute") {
                Value::Array(a) => a.len(),
                Value::Object(o) => o.len(),
                Value::String(s) => s.chars().count(),
                _ => 0,
            } + contati;
            let id = p.get("id").and_then(Value::as_i64).unwrap_or(0);
            let creato = utc(&p["creato"]);
            let visto = utc(&p["visto"]);
            p.insert("creato".into(), creato);
            p.insert("visto".into(), visto);
            let vista = match py::float(&p["vista"]) {
                Some(f) if f != 0.0 => Value::from(py::int(f * 1000.0)),
                _ => Value::Null,
            };
            p.insert("vista".into(), vista);
            let attivo = match py::float(&p["attivo"]) {
                Some(f) if f != 0.0 => Value::from(py::int(f)),
                _ => Value::Null,
            };
            p.insert("attivo".into(), attivo);
            p.insert("giorni".into(), Value::from(giorni.len()));
            p.insert(
                "ultimo_giorno".into(),
                giorni
                    .last()
                    .map(|g| Value::String(g.clone()))
                    .unwrap_or(Value::Null),
            );
            p.insert("sedute".into(), Value::from(sedute));
            p.insert(
                "domande".into(),
                Value::Bool(py::vero(py::get(&stato, "profilo"))),
            );
            p.insert(
                "ai".into(),
                Value::from(crate::chiavi::fila(&self.cartella, id)),
            );
            let utente = p
                .get("utente")
                .and_then(Value::as_str)
                .unwrap_or("")
                .to_string();
            let piano = !utente.is_empty() && self.piani.join(format!("{utente}.json")).is_file();
            p.insert("piano".into(), Value::Bool(piano));
            fuori.push(Value::Object(p));
        }
        Ok(fuori)
    }

    /// Deletes the assistant conversations of every account (weekly). Returns how many accounts had one.
    pub fn pulisci_chat(&self) -> Esito<i64> {
        self.scrivi(|db| {
            let tutte: Vec<(i64, String)> = {
                let mut st = db.prepare("SELECT utente, json FROM stato")?;

                st.query_map([], |r| Ok((r.get(0)?, r.get(1)?)))?
                    .collect::<Result<Vec<_>, _>>()?
            };
            let mut quanti = 0;
            for (u, json) in tutte {
                let Ok(mut stato) = serde_json::from_str::<Value>(&json) else {
                    continue;
                };
                if !stato.is_object() || !py::vero(py::get(&stato, "chat")) {
                    continue;
                }
                let giorno = chrono::Local::now().format("%Y-%m-%d").to_string();
                db.execute(
                    "INSERT OR IGNORE INTO stato_storia (utente, giorno, json) VALUES (?, ?, ?)",
                    params![u, giorno, json],
                )?;
                let agg = py::int(py::ora() * 1000.0) + 90000;
                stato["chat"] = Value::Array(vec![]);
                stato["updatedAt"] = Value::from(agg);
                db.execute(
                    "UPDATE stato SET aggiornato = ?, json = ? WHERE utente = ?",
                    params![agg as f64, crate::pyjson::compatto(&stato), u],
                )?;
                quanti += 1;
            }
            Ok(quanti)
        })
    }

    /// Reads (or writes, when there is a value) one server setting.
    pub fn impostazione(&self, k: &str, valore: Option<&str>) -> Esito<Option<String>> {
        self.scrivi(|db| {
            if let Some(v) = valore {
                db.execute(
                    "INSERT INTO impostazioni (chiave, valore) VALUES (?, ?) ON CONFLICT(chiave) DO UPDATE SET valore = excluded.valore",
                    params![k, v],
                )?;
                return Ok(Some(v.to_string()));
            }
            Ok(db.query_row("SELECT valore FROM impostazioni WHERE chiave = ?", [k], |r| r.get(0)).optional()?)
        })
    }

    /// Hand-written plans waiting for their account: {"utente", "nome"} for each file in piani without a person.
    pub fn attese(&self) -> Esito<Vec<Value>> {
        let presenti: HashSet<String> = self.leggi(|db| {
            let mut st = db.prepare("SELECT utente FROM utenti WHERE utente IS NOT NULL")?;
            let v = st
                .query_map([], |r| r.get::<_, String>(0))?
                .collect::<Result<HashSet<_>, _>>()?;
            Ok(v)
        })?;
        let mut nomi: Vec<String> = std::fs::read_dir(&self.piani)
            .map(|d| {
                d.filter_map(|e| e.ok())
                    .map(|e| e.file_name().to_string_lossy().into_owned())
                    .collect()
            })
            .unwrap_or_default();
        nomi.sort();
        let mut attese = Vec::new();
        for nome in nomi {
            let Some(base) = nome.strip_suffix(".json") else {
                continue;
            };
            let Some(utente) = accesso::nome_utente(base) else {
                continue;
            };
            if presenti.contains(&utente) {
                continue;
            }
            let Ok(testo) = std::fs::read_to_string(self.piani.join(&nome)) else {
                continue;
            };
            let Ok(piano) = serde_json::from_str::<Value>(&testo) else {
                continue;
            };
            let profilo = py::get(&piano, "profilo");
            let n = py::get(profilo, "nome");
            let nome_p = if py::vero(n) {
                py::testo(n)
            } else {
                capitalize(&utente)
            };
            attese.push(serde_json::json!({"utente": utente, "nome": py::taglia(&nome_p, 24)}));
        }
        Ok(attese)
    }

    fn password_valida(password: &Value) -> Esito<String> {
        let p = py::testo_o(password);
        let n = p.chars().count();
        if !(8..=100).contains(&n) {
            return errore(400, "La password deve avere almeno 8 caratteri");
        }
        Ok(p)
    }

    pub fn crea_persona(&self, nome: &Value, utente: &Value, password: &Value) -> Esito<Value> {
        let nome = nome_pulito(nome)?;
        let Some(utente) = accesso::nome_utente(&py::testo_o(utente)) else {
            return errore(
                400,
                "Il nome utente va scritto con lettere minuscole, cifre, punti o trattini (da 3 a 24)",
            );
        };
        let impasto = accesso::impasta(&Self::password_valida(password)?);
        let n: i64 =
            self.leggi(|db| Ok(db.query_row("SELECT COUNT(*) FROM utenti", [], |r| r.get(0))?))?;
        if n >= MAX_PERSONE {
            return errore(400, "Ci sono gia' troppe persone");
        }
        let codice = accesso::firma(&self.segreto, &accesso::nuovo_gettone());
        let esito = self.scrivi(|db| {
            db.execute(
                "INSERT INTO utenti (nome, utente, password, codice) VALUES (?, ?, ?, ?)",
                params![nome, utente, impasto, codice],
            )?;
            Ok(db.last_insert_rowid())
        });
        match esito {
            Ok(id) => Ok(serde_json::json!({"id": id, "nome": nome, "utente": utente})),
            Err(e) if e.database && e.testo.to_lowercase().contains("unique") => {
                errore(400, "Questo nome utente c'e' gia'")
            }
            Err(e) => Err(e),
        }
    }

    /// A new password for that person. Devices already in stay in.
    pub fn cambia_password(&self, ident: i64, password: &Value) -> Esito<Value> {
        if self.utente(ident)?.is_none() {
            return errore(400, "Persona sconosciuta");
        }
        let impasto = accesso::impasta(&Self::password_valida(password)?);
        self.scrivi(|db| {
            db.execute(
                "UPDATE utenti SET password = ? WHERE id = ?",
                params![impasto, ident],
            )?;
            Ok(())
        })?;
        Ok(serde_json::json!({"id": ident, "ok": true}))
    }

    pub fn rinomina(&self, ident: i64, nome: &Value) -> Esito<String> {
        let nome = nome_pulito(nome)?;
        self.scrivi(|db| {
            db.execute(
                "UPDATE utenti SET nome = ? WHERE id = ?",
                params![nome, ident],
            )?;
            Ok(())
        })?;
        Ok(nome)
    }

    pub fn elimina_persona(&self, ident: i64) -> Esito<()> {
        if ident == accesso::CAPO || self.utente(ident)?.is_none() {
            return errore(400, "Questo account non si puo' eliminare");
        }
        self.scrivi(|db| {
            for t in [
                "sessioni",
                "stato",
                "stato_storia",
                "pesate",
                "circonferenze",
                "passi",
                "pareri",
                "iscrizioni",
                "notifiche",
            ] {
                db.execute(&format!("DELETE FROM {t} WHERE utente = ?"), [ident])?;
            }
            db.execute("DELETE FROM utenti WHERE id = ?", [ident])?;
            Ok(())
        })?;
        for motore in crate::chiavi::MOTORI {
            let _ = crate::chiavi::togli_chiave(&self.cartella, ident, motore);
        }
        Ok(())
    }
}

/// Creates the tables; if it finds the ones from before accounts (one owner) it gives them to the admin.
fn prepara(db: &Connection) -> Esito<()> {
    let tabelle: HashSet<String> = {
        let mut st = db.prepare("SELECT name FROM sqlite_master WHERE type = 'table'")?;

        st.query_map([], |r| r.get::<_, String>(0))?
            .collect::<Result<HashSet<_>, _>>()?
    };
    let mut vecchie = Vec::new();
    for t in DI_UNO {
        if tabelle.contains(t) && !colonne(db, t)?.iter().any(|c| c == "utente") {
            vecchie.push(t);
        }
    }
    for t in &vecchie {
        db.execute_batch(&format!("ALTER TABLE {t} RENAME TO {t}_v1"))?;
    }
    if !vecchie.is_empty() {
        db.execute_batch("DROP INDEX IF EXISTS pesate_giorno")?;
    }
    if tabelle.contains("pareri") && !colonne(db, "pareri")?.iter().any(|c| c == "utente") {
        db.execute_batch("DROP TABLE pareri")?; // only a memory: rewritten at the next request
    }
    for istruzione in SCHEMA.split(";\n") {
        if !istruzione.trim().is_empty() {
            db.execute_batch(istruzione)?;
        }
    }
    for t in &vecchie {
        let nuove = colonne(db, t)?;
        let comuni: Vec<String> = colonne(db, &format!("{t}_v1"))?
            .into_iter()
            .filter(|c| nuove.contains(c) && !(*t == "stato" && c == "id"))
            .collect();
        let comuni = comuni.join(", ");
        db.execute_batch(&format!(
            "INSERT INTO {t} (utente, {comuni}) SELECT {}, {comuni} FROM {t}_v1",
            accesso::CAPO
        ))?;
        db.execute_batch(&format!("DROP TABLE {t}_v1"))?;
    }
    if !vecchie.is_empty() {
        log!(
            "database: passato agli account, i dati di prima sono del capo ({})",
            vecchie.join(", ")
        );
    }
    // accounts born with the code only had no username and password
    let cols = colonne(db, "utenti")?;
    for c in ["utente", "password"] {
        if !cols.iter().any(|x| x == c) {
            db.execute_batch(&format!("ALTER TABLE utenti ADD COLUMN {c} TEXT"))?;
        }
    }
    db.execute_batch("CREATE UNIQUE INDEX IF NOT EXISTS utenti_utente ON utenti (utente) WHERE utente IS NOT NULL")?;
    db.execute(
        "INSERT OR IGNORE INTO impostazioni (chiave, valore) VALUES ('segreto', ?)",
        [accesso::nuovo_gettone()],
    )?;
    Ok(())
}

/// `str.capitalize()`
pub fn capitalize(s: &str) -> String {
    let mut c = s.chars();
    match c.next() {
        Some(p) => p
            .to_uppercase()
            .chain(c.flat_map(|x| x.to_lowercase()))
            .collect(),
        None => String::new(),
    }
}

pub fn nome_pulito(nome: &Value) -> Esito<String> {
    let grezzo: String = py::testo_o(nome)
        .chars()
        .filter(|c| py::stampabile(*c) && !"<>\"&;=".contains(*c))
        .collect();
    let n = py::taglia(&py::spazi(&grezzo), 24).trim().to_string();
    if n.is_empty() {
        return errore(400, "Scrivi un nome");
    }
    Ok(n)
}
