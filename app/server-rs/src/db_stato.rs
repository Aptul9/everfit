//! State of the app, measures and steps (server.py, `Dati`, second half).

use crate::accesso;
use crate::db::{Dati, riga, righe};
use crate::errore::{Esito, errore};
use crate::py;
use jiff::{Span, Timestamp, civil::Date};

fn oggi() -> Date {
    Timestamp::now()
        .to_zoned(crate::conf::conf().fuso.clone())
        .date()
}
use regex::Regex;
use rusqlite::{OptionalExtension, params};
use serde_json::{Map, Value};
use std::sync::LazyLock;

static RE_QUANDO: LazyLock<Regex> =
    LazyLock::new(|| crate::py::re(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(:\d{2})?"));
static RE_GIORNO: LazyLock<Regex> = LazyLock::new(|| crate::py::re(r"^\d{4}-\d{2}-\d{2}"));

#[derive(Clone, Copy)]
enum Tipo {
    Int,
    Float,
}

/// field -> (type, min, max as Python prints them). Everything else in the request body is ignored.
const CAMPI_PESATA: [(&str, Tipo, f64, f64, &str, &str); 15] = [
    ("peso", Tipo::Float, 20.0, 300.0, "20", "300"),
    ("impedenza", Tipo::Int, 0.0, 3000.0, "0", "3000"),
    ("altezza", Tipo::Int, 80.0, 250.0, "80", "250"),
    ("eta", Tipo::Int, 5.0, 120.0, "5", "120"),
    ("imc", Tipo::Float, 5.0, 100.0, "5", "100"),
    ("grasso", Tipo::Float, 1.0, 75.0, "1", "75"),
    ("muscolo", Tipo::Float, 5.0, 100.0, "5", "100"),
    ("scheletrico", Tipo::Float, 5.0, 100.0, "5", "100"),
    ("acqua", Tipo::Float, 5.0, 100.0, "5", "100"),
    ("proteine", Tipo::Float, 1.0, 60.0, "1", "60"),
    ("ossa_kg", Tipo::Float, 0.2, 10.0, "0.2", "10"),
    ("sottocutaneo", Tipo::Float, 0.0, 75.0, "0", "75"),
    ("viscerale", Tipo::Float, 0.0, 60.0, "0", "60"),
    ("bmr", Tipo::Int, 300.0, 6000.0, "300", "6000"),
    ("eta_corporea", Tipo::Int, 5.0, 120.0, "5", "120"),
];
const CAMPI_CIRC: [&str; 8] = [
    "collo",
    "spalle",
    "petto",
    "vita",
    "fianchi",
    "braccio",
    "coscia",
    "polpaccio",
];
const FONTI: [&str; 4] = ["bilancia", "memoria", "manuale", "starfit"];

/// `RE.match` with the `$` of Python: the end, or just before a final newline.
fn combacia_fino_in_fondo(re: &Regex, s: &str) -> bool {
    re.find(s)
        .is_some_and(|m| m.end() == s.len() || (m.end() + 1 == s.len() && s.ends_with('\n')))
}

/// `numero(valore, tipo, minimo, massimo, campo)`
fn numero(
    valore: &Value,
    tipo: Tipo,
    lo: f64,
    hi: f64,
    lo_s: &str,
    hi_s: &str,
    campo: &str,
) -> Esito<Value> {
    if valore.is_null() || valore.as_str() == Some("") {
        return Ok(Value::Null);
    }
    let Some(f) = (match valore {
        Value::Array(_) | Value::Object(_) => None,
        v => py::float(v),
    }) else {
        return errore(400, format!("{campo} non e' un numero"));
    };
    let (v, json) = match tipo {
        Tipo::Int => {
            if !f.is_finite() {
                return errore(400, format!("{campo} non e' un numero"));
            }
            let i = py::int(f);
            (i as f64, Value::from(i))
        }
        Tipo::Float => (f, py::n_f(f)),
    };
    if !(lo <= v && v <= hi) {
        return errore(400, format!("{campo} fuori dai limiti ({lo_s}-{hi_s})"));
    }
    Ok(json)
}

fn sql_val(v: &Value) -> rusqlite::types::Value {
    use rusqlite::types::Value as S;
    match v {
        Value::Null => S::Null,
        Value::Number(n) if n.is_f64() => S::Real(n.as_f64().unwrap_or(0.0)),
        Value::Number(n) => S::Integer(n.as_i64().unwrap_or(0)),
        Value::String(s) => S::Text(s.clone()),
        Value::Bool(b) => S::Integer(*b as i64),
        other => S::Text(other.to_string()),
    }
}

/// The steps the iPhone shortcut sends: a number, or the text Shortcuts makes of Health samples. None if not understood.
pub fn conta_passi(valore: &Value) -> Option<i64> {
    static RE_RIGHE: LazyLock<Regex> = LazyLock::new(|| crate::py::re(r"[\r\n;]+"));
    static RE_DEC: LazyLock<Regex> = LazyLock::new(|| crate::py::re(r"[.,]\d{1,2}(\D|$)"));
    let n = match valore {
        Value::Null | Value::Bool(_) => return None,
        Value::Number(x) => py::int(x.as_f64()?),
        Value::Array(a) => {
            let parti: Vec<Option<i64>> = a.iter().take(2000).map(conta_passi).collect();
            if parti.is_empty() || parti.iter().any(Option::is_none) {
                return None;
            }
            parti.into_iter().flatten().sum()
        }
        Value::String(s) => {
            let righe: Vec<&str> = RE_RIGHE.split(s).filter(|r| !r.trim().is_empty()).collect();
            if righe.is_empty() || righe.len() > 2000 {
                return None;
            }
            let mut n = 0i64;
            for r in righe {
                // decimals away ("8432,0"), then the digits left are those of the number ("8.432" is 8432)
                let senza = togli_decimali(&RE_DEC, r);
                let cifre: String = senza.chars().filter(|c| c.is_ascii_digit()).collect();
                if cifre.is_empty() {
                    return None;
                }
                n = n.saturating_add(cifre.parse::<i64>().unwrap_or(i64::MAX));
            }
            n
        }
        Value::Object(_) => return None,
    };
    (0..=200000).contains(&n).then_some(n)
}

/// `re.sub(r"[.,]\d{1,2}(?!\d)", "", r)`: the regex crate has no lookahead, so the following char is put back.
fn togli_decimali(re: &Regex, r: &str) -> String {
    let mut out = String::new();
    let mut da = 0;
    let mut i = 0;
    while let Some(m) = re.find_at(r, i) {
        let testo = m.as_str();
        // m = sep + 1-2 digits + (non-digit | end). Greedy \d{1,2} followed by \D: try 2 digits first, then 1.
        let Some(ultimo) = testo.chars().last() else {
            break;
        };
        let tenuto = if ultimo.is_ascii_digit() {
            0
        } else {
            ultimo.len_utf8()
        };
        out.push_str(&r[da..m.start()]);
        da = m.end() - tenuto;
        i = da.max(m.start() + 1);
        if i > r.len() {
            break;
        }
    }
    out.push_str(&r[da..]);
    out
}

impl Dati {
    // ---- app state
    pub fn stato(&self, u: i64) -> Esito<String> {
        self.leggi(|db| {
            Ok(db
                .query_row("SELECT json FROM stato WHERE utente = ?", [u], |r| {
                    r.get::<_, String>(0)
                })
                .optional()?
                .unwrap_or_else(|| "{}".into()))
        })
    }

    pub fn versione_stato(&self, u: i64) -> Esito<Value> {
        self.leggi(|db| {
            Ok(db
                .query_row("SELECT aggiornato FROM stato WHERE utente = ?", [u], |r| {
                    r.get::<_, f64>(0)
                })
                .optional()?
                .map(py::n_f)
                .unwrap_or(Value::from(0)))
        })
    }

    /// None if saved; otherwise the state on the server, which the device must take instead of its own.
    pub fn salva_stato(&self, u: i64, testo: &str, nuovo: &Value) -> Esito<Option<Value>> {
        let di = py::get(nuovo, "di");
        let agg = py::float(py::o(py::get(nuovo, "updatedAt"), &Value::from(0))).unwrap_or(0.0);
        self.scrivi(|db| {
            let r: Option<(f64, String)> =
                db.query_row("SELECT aggiornato, json FROM stato WHERE utente = ?", [u], |r| Ok((r.get(0)?, r.get(1)?))).optional()?;
            let carica = |j: &str| serde_json::from_str::<Value>(j).unwrap_or(Value::Null);
            // a state written for another account (phone passed hands) must not end up here
            let di_altro = match di {
                Value::Null => u != accesso::CAPO,
                Value::Number(n) => n.as_f64() != Some(u as f64),
                Value::Bool(b) => (*b as i64) != u,
                _ => true,
            };
            if di_altro {
                return Ok(Some(match &r {
                    Some((_, j)) => carica(j),
                    None => serde_json::json!({"di": u, "updatedAt": 0}),
                }));
            }
            if let Some((a, j)) = &r {
                if *a > agg {
                    return Ok(Some(carica(j))); // the server has a newer version: it wins
                }
                let giorno = jiff::Zoned::now().date().to_string();
                db.execute("INSERT OR IGNORE INTO stato_storia (utente, giorno, json) VALUES (?, ?, ?)", params![u, giorno, j])?;
                db.execute(
                    "DELETE FROM stato_storia WHERE utente = ? AND giorno NOT IN \
                     (SELECT giorno FROM stato_storia WHERE utente = ? ORDER BY giorno DESC LIMIT ?)",
                    params![u, u, crate::db::GIORNI_STORIA],
                )?;
            }
            db.execute(
                "INSERT INTO stato (utente, aggiornato, json) VALUES (?, ?, ?) \
                 ON CONFLICT(utente) DO UPDATE SET aggiornato = excluded.aggiornato, json = excluded.json",
                params![u, agg, testo],
            )?;
            Ok(None)
        })
    }

    // ---- measures
    pub fn misure(&self, u: i64) -> Esito<Value> {
        let da = oggi().saturating_sub(Span::new().days(120)).to_string();
        self.leggi(|db| {
            let pesate = righe(db, "SELECT * FROM pesate WHERE utente = ? ORDER BY quando", [u])?;
            let circ = righe(db, "SELECT * FROM circonferenze WHERE utente = ? ORDER BY giorno", [u])?;
            let passi = righe(db, "SELECT giorno, passi, aggiornato FROM passi WHERE utente = ? AND giorno >= ? ORDER BY giorno", params![u, da])?;
            let mut m = Map::new();
            m.insert("pesate".into(), Value::Array(pesate.into_iter().map(Value::Object).collect()));
            m.insert("circonferenze".into(), Value::Array(circ.into_iter().map(Value::Object).collect()));
            m.insert("passi".into(), Value::Array(passi.into_iter().map(Value::Object).collect()));
            Ok(Value::Object(m))
        })
    }

    // ---- steps from the iPhone shortcut, which has its own code (a session of type "passi")
    pub fn salva_passi(&self, u: i64, valore: &Value, giorno: &Value) -> Esito<Value> {
        let Some(n) = conta_passi(valore) else {
            return errore(
                400,
                "passi: serve un numero (anche come testo, per esempio \"8.432\")",
            );
        };
        let oggi = oggi();
        let g = if py::vero(giorno) {
            match Date::strptime("%Y-%m-%d", py::testo(giorno)) {
                Ok(d) => d,
                _ => return errore(400, "giorno deve essere AAAA-MM-GG"),
            }
        } else {
            oggi
        };
        let intervallo =
            oggi.saturating_sub(Span::new().days(7))..=oggi.saturating_add(Span::new().days(1));
        if !intervallo.contains(&g) {
            return errore(400, "giorno troppo lontano da oggi");
        }
        let g = g.to_string();
        self.scrivi(|db| {
            db.execute(
                "INSERT INTO passi (utente, giorno, passi, aggiornato) VALUES (?, ?, ?, ?) \
                 ON CONFLICT(utente, giorno) DO UPDATE SET passi = excluded.passi, aggiornato = excluded.aggiornato",
                params![u, g, n, py::ora()],
            )?;
            Ok(())
        })?;
        Ok(serde_json::json!({"ok": true, "giorno": g, "passi": n}))
    }

    pub fn utente_dei_passi(&self, codice: &str) -> Esito<Option<i64>> {
        if codice.is_empty() {
            return Ok(None);
        }
        let imp = accesso::impronta(codice);
        let r: Option<(i64, f64)> = self.leggi(|db| {
            Ok(db
                .query_row(
                    "SELECT utente, vista FROM sessioni WHERE impronta = ? AND tipo = 'passi'",
                    [&imp],
                    |r| Ok((r.get(0)?, r.get(1)?)),
                )
                .optional()?)
        })?;
        if let Some((_, vista)) = r
            && py::ora() - vista > 3600.0
        {
            self.scrivi(|db| {
                db.execute(
                    "UPDATE sessioni SET vista = ? WHERE impronta = ?",
                    params![py::ora(), imp],
                )?;
                Ok(())
            })?;
        }
        Ok(r.map(|(u, _)| u))
    }

    pub fn nuovo_codice_passi(&self, u: i64) -> Esito<String> {
        self.togli_codice_passi(u)?;
        self.apri_sessione(u, "passi", None, None)
    }

    pub fn togli_codice_passi(&self, u: i64) -> Esito<()> {
        self.scrivi(|db| {
            db.execute(
                "DELETE FROM sessioni WHERE utente = ? AND tipo = 'passi'",
                [u],
            )?;
            Ok(())
        })
    }

    pub fn stato_passi(&self, u: i64) -> Esito<Value> {
        self.leggi(|db| {
            let attivo = db.query_row("SELECT 1 FROM sessioni WHERE utente = ? AND tipo = 'passi'", [u], |_| Ok(())).optional()?.is_some();
            let ultimo = db
                .query_row("SELECT giorno, passi, aggiornato FROM passi WHERE utente = ? ORDER BY aggiornato DESC LIMIT 1", [u], |r| Ok(riga(r)))
                .optional()?;
            Ok(serde_json::json!({"attivo": attivo, "ultimo": ultimo.map(Value::Object).unwrap_or(Value::Null)}))
        })
    }

    pub fn salva_pesata(&self, u: i64, d: &Value) -> Esito<Value> {
        let mut quando = py::testo_o(py::get(d, "quando"));
        if !combacia_fino_in_fondo(&RE_QUANDO, &quando) {
            return errore(400, "quando deve essere AAAA-MM-GGTHH:MM:SS");
        }
        if quando.chars().count() == 16 {
            quando.push_str(":00");
        }
        let scelta = |k: &str, ammessi: &[&str]| -> Option<String> {
            py::get(d, k)
                .as_str()
                .filter(|s| ammessi.contains(s))
                .map(String::from)
        };
        let fonte = scelta("fonte", &FONTI).unwrap_or_else(|| "manuale".into());
        let mut riga_n: Vec<(&str, Value)> = vec![
            ("utente", Value::from(u)),
            ("quando", Value::String(quando.clone())),
            ("giorno", Value::String(py::taglia(&quando, 10))),
            ("fonte", Value::String(fonte)),
            (
                "sesso",
                scelta("sesso", &["m", "f"])
                    .map(Value::String)
                    .unwrap_or(Value::Null),
            ),
            ("algoritmo", testo_breve(py::get(d, "algoritmo"), 40)),
            ("nota", testo_breve(py::get(d, "nota"), 300)),
        ];
        for (campo, tipo, lo, hi, lo_s, hi_s) in CAMPI_PESATA {
            riga_n.push((
                campo,
                numero(py::get(d, campo), tipo, lo, hi, lo_s, hi_s, campo)?,
            ));
        }
        if riga_n.iter().any(|(k, v)| *k == "peso" && v.is_null()) {
            return errore(400, "manca il peso");
        }
        let sql = upsert("pesate", &riga_n, &["utente", "quando"]);
        self.scrivi(|db| {
            let valori: Vec<_> = riga_n.iter().map(|(_, v)| sql_val(v)).collect();
            db.execute(&sql, rusqlite::params_from_iter(valori))?;
            Ok(Value::Object(db.query_row(
                "SELECT * FROM pesate WHERE utente = ? AND quando = ?",
                params![u, quando],
                |r| Ok(riga(r)),
            )?))
        })
    }

    pub fn salva_circonferenze(&self, u: i64, d: &Value) -> Esito<Value> {
        let giorno = py::testo_o(py::get(d, "giorno"));
        if !combacia_fino_in_fondo(&RE_GIORNO, &giorno) {
            return errore(400, "giorno deve essere AAAA-MM-GG");
        }
        let mut riga_n: Vec<(&str, Value)> = vec![
            ("utente", Value::from(u)),
            ("giorno", Value::String(giorno.clone())),
            ("nota", testo_breve(py::get(d, "nota"), 300)),
        ];
        for campo in CAMPI_CIRC {
            riga_n.push((
                campo,
                numero(
                    py::get(d, campo),
                    Tipo::Float,
                    10.0,
                    250.0,
                    "10",
                    "250",
                    campo,
                )?,
            ));
        }
        if riga_n
            .iter()
            .filter(|(k, _)| CAMPI_CIRC.contains(k))
            .all(|(_, v)| v.is_null())
        {
            return errore(400, "serve almeno una misura");
        }
        let sql = upsert("circonferenze", &riga_n, &["utente", "giorno"]);
        self.scrivi(|db| {
            let valori: Vec<_> = riga_n.iter().map(|(_, v)| sql_val(v)).collect();
            db.execute(&sql, rusqlite::params_from_iter(valori))?;
            Ok(Value::Object(db.query_row(
                "SELECT * FROM circonferenze WHERE utente = ? AND giorno = ?",
                params![u, giorno],
                |r| Ok(riga(r)),
            )?))
        })
    }

    pub fn elimina(&self, u: i64, tabella: &str, ident: i64) -> Esito<bool> {
        let tabella = if tabella == "pesate" {
            "pesate"
        } else {
            "circonferenze"
        };
        self.scrivi(|db| {
            Ok(db.execute(
                &format!("DELETE FROM {tabella} WHERE id = ? AND utente = ?"),
                params![ident, u],
            )? > 0)
        })
    }
}

/// `str(d["x"])[:n] if d.get("x") else None`
fn testo_breve(v: &Value, n: usize) -> Value {
    if py::vero(v) {
        Value::String(py::taglia(&py::testo(v), n))
    } else {
        Value::Null
    }
}

fn upsert(tabella: &str, riga: &[(&str, Value)], chiavi: &[&str]) -> String {
    let colonne: Vec<&str> = riga.iter().map(|(k, _)| *k).collect();
    format!(
        "INSERT INTO {tabella} ({}) VALUES ({}) ON CONFLICT({}) DO UPDATE SET {}",
        colonne.join(", "),
        colonne.iter().map(|_| "?").collect::<Vec<_>>().join(", "),
        chiavi.join(", "),
        colonne
            .iter()
            .filter(|c| !chiavi.contains(c))
            .map(|c| format!("{c} = excluded.{c}"))
            .collect::<Vec<_>>()
            .join(", ")
    )
}

#[cfg(test)]
mod test {
    use super::*;
    use serde_json::json;

    #[test]
    fn passi_come_python() {
        assert_eq!(conta_passi(&json!("8.432 passi")), Some(8432));
        assert_eq!(conta_passi(&json!("1200\n2300,0")), Some(3500));
        assert_eq!(conta_passi(&json!("8432,0")), Some(8432));
        assert_eq!(conta_passi(&json!("8 432")), Some(8432));
        assert_eq!(conta_passi(&json!("molti")), None);
        assert_eq!(conta_passi(&json!(10)), Some(10));
        assert_eq!(conta_passi(&json!(true)), None);
        assert_eq!(conta_passi(&json!([1, "2"])), Some(3));
        assert_eq!(conta_passi(&json!(300000)), None);
        assert_eq!(conta_passi(&json!("1.5")), Some(1));
    }

    #[test]
    fn quando() {
        assert!(combacia_fino_in_fondo(&RE_QUANDO, "2026-10-10T08:00:00"));
        assert!(combacia_fino_in_fondo(&RE_QUANDO, "2026-10-10T08:00"));
        assert!(!combacia_fino_in_fondo(&RE_QUANDO, "2026-10-10T08:00:00Z"));
    }
}
