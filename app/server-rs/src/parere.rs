//! The written review of a product and the key test (parere.py).

use crate::ai;
use crate::chiavi::Motore;
use crate::cibo::pulisci;
use crate::errore::{Esito, Problema};
use crate::py::{self, get};
use serde_json::{Map, Value, json};
use std::sync::LazyLock;

const SISTEMA: &str = include_str!("../testi/sistema_parere.txt");
static STRUMENTO: LazyLock<Value> = LazyLock::new(|| {
    serde_json::from_str(include_str!("../testi/strumento_parere.json")).unwrap_or(Value::Null)
});
static PROVA: LazyLock<Value> = LazyLock::new(|| {
    serde_json::from_str(include_str!("../testi/strumento_prova.json")).unwrap_or(Value::Null)
});

fn righe(valore: &Value, quante: usize, lunghe: usize) -> Vec<String> {
    valore
        .as_array()
        .map(|a| {
            a.iter()
                .filter_map(Value::as_str)
                .filter(|s| !s.trim().is_empty())
                .map(|s| pulisci(s, lunghe))
                .take(quante)
                .collect()
        })
        .unwrap_or_default()
}

/// `v not in (None, [], False, "")` in Python: since `0 == False`, zero numbers are left out too.
fn vuoto(v: &Value) -> bool {
    matches!(v, Value::Null | Value::Bool(false))
        || v.as_array().is_some_and(Vec::is_empty)
        || v.as_str() == Some("")
        || v.as_f64() == Some(0.0)
}

/// {"riassunto", "forti", "deboli", "consigli", "motore"} for that product and that person.
pub fn scrivi(motore: &Motore, prodotto: &Value, persona: &str) -> Esito<Value> {
    let mut fatti = Map::new();
    for k in ["n", "marca", "kcal", "p", "c", "f", "pz", "conf"] {
        fatti.insert(k.into(), get(prodotto, k).clone());
    }
    if let Some(x) = py::o(get(prodotto, "x"), &Value::Null).as_object() {
        for (k, v) in x {
            if !vuoto(v) {
                fatti.insert(k.clone(), v.clone());
            }
        }
    }
    let testo = format!(
        "PERSONA\n{}\n\nPRODOTTO (kcal, p = proteine, c = carboidrati, f = grassi, sat = grassi saturi, zuc = zuccheri, \
         fib = fibre, sale: tutti per 100 g; pz = grammi di un pezzo o di una porzione; conf = grammi della confezione; \
         nutri = Nutri-Score; nova = gruppo NOVA)\n{}",
        pulisci(persona, 900),
        crate::pyjson::largo(&Value::Object(fatti))
    );
    let esito = ai::chiedi_json(motore, SISTEMA, &testo, &STRUMENTO, None, 900)?;
    let Some(esito) =
        esito.filter(|e| e.is_object() && !py::testo_o(get(e, "riassunto")).trim().is_empty())
    else {
        return Err(Problema::new(
            502,
            "Non sono riuscito a scrivere il parere. Riprova.",
        ));
    };
    Ok(json!({
        "riassunto": pulisci(&py::testo(get(&esito, "riassunto")), 500),
        "forti": righe(get(&esito, "forti"), 4, 180), "deboli": righe(get(&esito, "deboli"), 4, 180),
        "consigli": righe(get(&esito, "consigli"), 3, 240), "motore": ai::chi_ha_risposto(motore),
    }))
}

/// A tiny question to the service: if the key does not work, the error says why. `modello` is who answered.
pub fn prova(motore: &Motore) -> Esito<Value> {
    match motore.nome.as_str() {
        "mistral" => crate::ai_mistral::dimentica(&motore.chiave),
        "gemini" => crate::ai_gemini::riprova(),
        _ => {}
    }
    let esito = ai::chiedi_json(
        motore,
        "Questa e' una prova di collegamento.",
        "Rispondi con ok = true.",
        &PROVA,
        None,
        100,
    )?;
    if !esito.as_ref().is_some_and(Value::is_object) {
        return Err(Problema::new(
            502,
            "Il servizio ha risposto in modo strano. Riprova.",
        ));
    }
    Ok(json!({"ok": true, "motore": motore.nome, "modello": ai::quale_modello()}))
}
