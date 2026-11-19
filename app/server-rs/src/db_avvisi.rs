//! Phone notifications, meal reminders, barcode products and written reviews (server.py, `Dati`, last part).

use crate::db::{Dati, righe};
use crate::errore::{Esito, errore};
use crate::log;
use crate::py;
use regex::Regex;
use rusqlite::{OptionalExtension, params};
use serde_json::{Map, Value};
use std::collections::HashSet;
use std::sync::LazyLock;

static RE_ORA: LazyLock<Regex> = LazyLock::new(|| crate::py::re(r"^[0-2]\d:[0-5]\d$"));
static RE_ORA2: LazyLock<Regex> = LazyLock::new(|| crate::py::re(r"^(\d\d):(\d\d)$"));

/// `int(x)` for a JSON value, None where Python raises.
fn intero(v: &Value) -> Option<i64> {
    match v {
        Value::Bool(b) => Some(*b as i64),
        Value::Number(n) => n
            .as_i64()
            .or_else(|| n.as_f64().filter(|f| f.is_finite()).map(py::int)),
        Value::String(s) => {
            let t = s.trim();
            let t = t.strip_prefix('+').unwrap_or(t);
            let pulito: String = t.chars().filter(|c| *c != '_').collect();
            if pulito.is_empty() || t.starts_with('_') || t.ends_with('_') || t.contains("__") {
                return None;
            }
            pulito.parse().ok()
        }
        _ => None,
    }
}

impl Dati {
    /// Records (or updates) that person's phone. Returns whether meal reminders are on.
    pub fn iscrivi(
        &self,
        u: i64,
        indirizzo: &Value,
        fuso: &Value,
        orari: &Value,
        promemoria: &Value,
    ) -> Esito<bool> {
        let indirizzo_s = py::testo_o(indirizzo);
        if !crate::spinta::indirizzo_buono(&indirizzo_s) {
            return errore(400, "Questo telefono non si puo' iscrivere alle notifiche");
        }
        let mut puliti = Map::new();
        if let Some(o) = orari.as_object() {
            for (k, v) in o {
                if (k == "pranzo" || k == "cena") && RE_ORA.is_match(&py::testo(v)) {
                    puliti.insert(k.clone(), v.clone());
                }
            }
        }
        let fuso = intero(fuso).map(|f| f.clamp(-720, 840)).unwrap_or(120);
        let orari_json = crate::pyjson::ascii(&Value::Object(puliti));
        self.scrivi(|db| {
            let c_era: Option<i64> =
                db.query_row("SELECT promemoria FROM iscrizioni WHERE indirizzo = ?", [&indirizzo_s], |r| r.get(0)).optional()?;
            let acceso = if promemoria.is_null() { c_era.unwrap_or(1) } else { py::vero(promemoria) as i64 };
            db.execute(
                "INSERT INTO iscrizioni (indirizzo, utente, fuso, orari, promemoria, creata) VALUES (?, ?, ?, ?, ?, ?) \
                 ON CONFLICT(indirizzo) DO UPDATE SET utente = excluded.utente, fuso = excluded.fuso, orari = excluded.orari, promemoria = excluded.promemoria",
                params![indirizzo_s, u, fuso, orari_json, acceso, py::ora()],
            )?;
            Ok(acceso != 0)
        })
    }

    pub fn disiscrivi(&self, indirizzo: &str, u: Option<i64>) -> Esito<()> {
        self.scrivi(|db| {
            match u {
                None => db.execute("DELETE FROM iscrizioni WHERE indirizzo = ?", [indirizzo])?,
                Some(u) => db.execute(
                    "DELETE FROM iscrizioni WHERE indirizzo = ? AND utente = ?",
                    params![indirizzo, u],
                )?,
            };
            Ok(())
        })
    }

    /// Stores a notification for that person and wakes their phones, which come and fetch it. The same label never
    /// makes it twice. Returns how many phones were woken.
    pub fn avvisa(
        &self,
        u: i64,
        etichetta: &str,
        titolo: &str,
        testo: &str,
        dove: Option<&str>,
    ) -> Esito<i64> {
        let (nuova, telefoni) = self.scrivi(|db| {
            let nuova = db.execute(
                "INSERT OR IGNORE INTO notifiche (utente, etichetta, titolo, testo, dove, creata) VALUES (?, ?, ?, ?, ?, ?)",
                params![u, etichetta, py::taglia(titolo, 80), py::taglia(testo, 240), dove, py::ora()],
            )?;
            db.execute("DELETE FROM notifiche WHERE creata < ?", [py::ora() - 7.0 * 86400.0])?;
            let mut st = db.prepare("SELECT indirizzo FROM iscrizioni WHERE utente = ?")?;
            let t = st.query_map([u], |r| r.get::<_, String>(0))?.collect::<Result<Vec<_>, _>>()?;
            Ok((nuova, t))
        })?;
        if nuova == 0 {
            return Ok(0);
        }
        let mut svegliati = 0;
        for indirizzo in &telefoni {
            let codice = crate::spinta::spingi(&self.cartella, indirizzo);
            if codice == 404 || codice == 410 {
                // the subscription is no longer valid (app removed, permission revoked)
                self.disiscrivi(indirizzo, None)?;
            }
            if (200..300).contains(&codice) {
                svegliati += 1;
            }
        }
        let cosa = if etichetta.starts_with("fitai") {
            etichetta.split('-').next().unwrap_or("")
        } else {
            etichetta
        };
        log!(
            "notifiche: u{} {}, telefoni svegliati {} su {}",
            u,
            cosa,
            svegliati,
            telefoni.len()
        );
        Ok(svegliati)
    }

    /// The notifications that person has not received yet (last twelve hours): from now on they are delivered.
    pub fn prossime(&self, u: i64) -> Esito<Vec<Value>> {
        self.scrivi(|db| {
            let r = righe(
                db,
                "SELECT id, etichetta, titolo, testo, dove FROM notifiche WHERE utente = ? AND consegnata = 0 AND creata > ? ORDER BY id",
                params![u, py::ora() - 12.0 * 3600.0],
            )?;
            db.execute("UPDATE notifiche SET consegnata = 1 WHERE utente = ? AND consegnata = 0", [u])?;
            Ok(r.into_iter().map(Value::Object).collect())
        })
    }

    /// Whoever should have had lunch or dinner by now and has not marked it gets one reminder, 45 minutes after the
    /// meal time and for the next two hours.
    pub fn giro_promemoria(&self) -> Esito<()> {
        let (telefoni, gia) = self.leggi(|db| {
            let t = righe(
                db,
                "SELECT utente, fuso, orari FROM iscrizioni WHERE promemoria = 1 GROUP BY utente",
                [],
            )?;
            let mut st = db.prepare("SELECT utente, etichetta FROM notifiche WHERE creata > ?")?;
            let g = st
                .query_map([py::ora() - 2.0 * 86400.0], |r| {
                    Ok((r.get::<_, i64>(0)?, r.get::<_, String>(1)?))
                })?
                .collect::<Result<HashSet<_>, _>>()?;
            Ok((t, g))
        })?;
        for t in telefoni {
            let u = t.get("utente").and_then(Value::as_i64).unwrap_or(0);
            let fuso = t.get("fuso").and_then(Value::as_i64).unwrap_or(120);
            let now = jiff::Timestamp::now();
            let li = now
                .checked_add(jiff::Span::new().minutes(fuso.clamp(-720, 840)))
                .unwrap_or(now)
                .to_zoned(jiff::tz::TimeZone::UTC);
            let oggi = li.date().to_string();
            let minuti = i64::from(li.hour()) * 60 + i64::from(li.minute());
            let orari: Value = serde_json::from_str(
                t.get("orari")
                    .and_then(Value::as_str)
                    .filter(|s| !s.is_empty())
                    .unwrap_or("{}"),
            )
            .unwrap_or_else(|_| Value::Object(Map::new()));
            for (pasto, titolo, cosa) in [
                ("pranzo", "Hai pranzato?", "il pranzo"),
                ("cena", "Hai cenato?", "la cena"),
            ] {
                let ora = py::testo_o(py::get(&orari, pasto));
                let Some(c) = RE_ORA2.captures(&ora) else {
                    continue;
                };
                let quando =
                    c[1].parse::<i64>().unwrap_or(0) * 60 + c[2].parse::<i64>().unwrap_or(0) + 45;
                let etichetta = format!("{oggi}-{pasto}");
                if !(quando <= minuti && minuti < quando + 120)
                    || gia.contains(&(u, etichetta.clone()))
                {
                    continue;
                }
                let stato: Value = serde_json::from_str(&self.stato(u)?).unwrap_or(Value::Null);
                let giorno = py::o(py::get(py::get(&stato, "giorni"), &oggi), &Value::Null).clone();
                let pasti = py::get(&giorno, "pasti");
                let segnato = py::vero(py::get(pasti, pasto))
                    || py::get(&giorno, "extra").as_array().is_some_and(|e| {
                        e.iter()
                            .any(|x| x.is_object() && py::get(x, "mom").as_str() == Some(pasto))
                    });
                if !segnato {
                    self.avvisa(
                        u,
                        &etichetta,
                        titolo,
                        &format!("Segna {cosa} su EverFit: basta un tocco."),
                        Some("./#/oggi"),
                    )?;
                }
            }
        }
        Ok(())
    }

    // ---- barcode products
    pub fn prodotto(&self, ean: &str) -> Esito<Value> {
        let r: Option<(String, f64)> = self.leggi(|db| {
            Ok(db
                .query_row(
                    "SELECT json, preso FROM prodotti WHERE ean = ?",
                    [ean],
                    |r| Ok((r.get(0)?, r.get(1)?)),
                )
                .optional()?)
        })?;
        let carica = |j: &str| serde_json::from_str::<Value>(j).unwrap_or(Value::Null);
        // copies saved before the rest of the label ("x") existed are fetched again
        if let Some((j, preso)) = &r
            && py::ora() - preso < crate::db::GIORNI_PRODOTTO * 86400.0
            && j.contains("\"x\"")
        {
            return Ok(carica(j));
        }
        let voce = match crate::cibo::prodotto_ean(ean) {
            Ok(v) => v,
            Err(e) => {
                if let Some((j, _)) = &r {
                    return Ok(carica(j)); // the catalogue does not answer: better the old copy than nothing
                }
                return Err(e);
            }
        };
        let Some(voce) = voce else {
            return errore(404, "Questo codice non e' nel catalogo");
        };
        let testo = crate::pyjson::largo(&voce);
        self.scrivi(|db| {
            db.execute(
                "INSERT INTO prodotti (ean, json, preso) VALUES (?, ?, ?) \
                 ON CONFLICT(ean) DO UPDATE SET json = excluded.json, preso = excluded.preso",
                params![ean, testo, py::ora()],
            )?;
            Ok(())
        })?;
        Ok(voce)
    }

    // ---- written review of a product (parere.rs)
    pub fn parere(&self, u: i64, ean: &str, persona: &str, rifai: bool) -> Esito<Value> {
        let Some(motore) = crate::chiavi::motore_ai(&self.cartella, u) else {
            return errore(
                503,
                "Il parere scritto non e' attivo: serve la chiave di un servizio di AI",
            );
        };
        let r: Option<(String, String, f64)> = self.leggi(|db| {
            Ok(db
                .query_row(
                    "SELECT json, motore, quando FROM pareri WHERE utente = ? AND ean = ?",
                    params![u, ean],
                    |r| Ok((r.get(0)?, r.get(1)?, r.get(2)?)),
                )
                .optional()?)
        })?;
        if let Some((j, m, quando)) = &r
            && !rifai
            && *m == motore.nome
            && py::ora() - quando < 90.0 * 86400.0
        {
            return Ok(serde_json::from_str(j).unwrap_or(Value::Null));
        }
        let prodotto = self.prodotto(ean)?;
        let esito = crate::parere::scrivi(&motore, &prodotto, persona)?;
        let testo = crate::pyjson::largo(&esito);
        self.scrivi(|db| {
            db.execute(
                "INSERT INTO pareri (utente, ean, motore, json, quando) VALUES (?, ?, ?, ?, ?) \
                 ON CONFLICT(utente, ean) DO UPDATE SET motore = excluded.motore, json = excluded.json, quando = excluded.quando",
                params![u, ean, motore.nome, testo, py::ora()],
            )?;
            Ok(())
        })?;
        Ok(esito)
    }
}
