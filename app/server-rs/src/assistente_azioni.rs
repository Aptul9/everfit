//! The assistant's actions (assistente.py `_azione`, `_operazione`, `forma_locale`, ...): the server only checks shape
//! and numbers and sends them back to the app, which applies them and verifies that the identifiers exist.

use crate::py::{self, get, vero};
use regex::Regex;
use serde_json::{Map, Value, json};
use std::sync::LazyLock;

pub const TIPI: [&str; 18] = [
    "mangiato",
    "pasto_fatto",
    "togli_voce",
    "acqua",
    "movimento",
    "peso",
    "cambia_pasto",
    "ripristina_pasto",
    "nuovo_piatto",
    "togli_piatto",
    "tema",
    "misure",
    "modifica",
    "obiettivo",
    "quantita",
    "orario",
    "dose",
    "cambia_voce",
];
/// the parts of the state a "modifica" may touch (same as RADICI in public/js/store.js, which really decides)
const RADICI: [&str; 8] = [
    "giorni", "cambi", "spesa", "sedute", "attivita", "opzioni", "profilo", "mie",
];
const VIETATE: [&str; 3] = ["__proto__", "prototype", "constructor"];
const MISURE: [&str; 8] = [
    "vita",
    "collo",
    "spalle",
    "petto",
    "braccio",
    "coscia",
    "fianchi",
    "polpaccio",
];
pub const ATTIVITA: [&str; 6] = ["camminata", "corsa", "bici", "casa", "nuoto", "altro"];
const REPARTI: [&str; 6] = [
    "Carne e pesce",
    "Frigo",
    "Frutta e verdura",
    "Surgelati",
    "Dispensa",
    "Integratori",
];
const MAX_VALORE: usize = 20000;

static RE_CONTROLLO_T: LazyLock<Regex> = LazyLock::new(|| py::re(r"[\x00-\x1f<>]"));
static RE_CONTROLLO: LazyLock<Regex> = LazyLock::new(|| py::re(r"[\x00-\x1f]"));
static RE_ID: LazyLock<Regex> = LazyLock::new(|| py::re(r"^[A-Za-z0-9_.-]{1,48}$"));
static RE_GIORNO: LazyLock<Regex> = LazyLock::new(|| py::re(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$"));
static RE_QUANTITA: LazyLock<Regex> = LazyLock::new(|| py::re(r"^\s*[0-9]+(?:[.,][0-9]+)?"));
static RE_ORA: LazyLock<Regex> = LazyLock::new(|| py::re(r"^([01]?[0-9]|2[0-3])[:.]([0-5][0-9])$"));

/// `_n(v, minimo, massimo, cifre)`: a clamped, rounded float, or None. Python's round() with digits gives a float.
pub fn n(v: &Value, minimo: f64, massimo: f64, cifre: i32) -> Option<f64> {
    let f = match v {
        Value::Array(_) | Value::Object(_) | Value::Null => None,
        x => py::float(x),
    }?;
    f.is_finite()
        .then(|| py::round(f.clamp(minimo, massimo), cifre))
}

fn nv(x: Option<f64>) -> Value {
    x.map(py::n_f).unwrap_or(Value::Null)
}

/// `x or 0`: a missing or zero number becomes the integer 0, as in Python.
fn o_zero(v: &Value) -> Value {
    if vero(v) { v.clone() } else { Value::from(0) }
}

pub fn t(v: &Value, lungo: usize) -> String {
    py::taglia(
        RE_CONTROLLO_T.replace_all(&py::testo_o(v), " ").trim(),
        lungo,
    )
}

pub fn id(v: &Value) -> String {
    let s = py::testo_o(v).trim().to_string();
    if RE_ID.is_match(&s) { s } else { String::new() }
}

pub fn giorno(v: &Value) -> String {
    let s = py::testo_o(v).trim().to_string();
    if RE_GIORNO.is_match(&s) {
        s
    } else {
        String::new()
    }
}

pub fn lista(v: &Value, quanti: usize) -> &[Value] {
    v.as_array()
        .map(|a| &a[..a.len().min(quanti)])
        .unwrap_or(&[])
}

fn numero_non_bool(x: &Value) -> Option<f64> {
    match x {
        Value::Number(n) => n.as_f64(),
        _ => None,
    }
}

fn giorni(v: &Value) -> Vec<i64> {
    let mut fuori = Vec::new();
    for x in lista(v, 7) {
        if let Some(f) = numero_non_bool(x).filter(|f| f.is_finite()) {
            let i = py::int(f);
            if (0..=6).contains(&i) && !fuori.contains(&i) {
                fuori.push(i);
            }
        }
    }
    fuori
}

/// The same value without the keys that touch the prototype of objects in JavaScript, and not too deep.
fn pulito(v: &Value, livello: u32) -> Value {
    if livello > 12 {
        return Value::Null;
    }
    match v {
        Value::Object(o) => {
            let mut m = Map::new();
            for (k, x) in o {
                if !VIETATE.contains(&k.as_str()) {
                    m.insert(py::taglia(k, 60), pulito(x, livello + 1));
                }
            }
            Value::Object(m)
        }
        Value::Array(a) => {
            Value::Array(a.iter().take(400).map(|x| pulito(x, livello + 1)).collect())
        }
        x => x.clone(),
    }
}

/// One "modifica" operation cleaned, or None. Whether the path exists and the shape is right is the app's call.
fn operazione(o: &Value) -> Option<Value> {
    let op = get(o, "op")
        .as_str()
        .filter(|s| ["metti", "togli", "aggiungi"].contains(s))?;
    let grezzo = get(o, "percorso").as_array()?;
    let mut percorso = Vec::new();
    for k in grezzo {
        if k.is_boolean() || percorso.len() >= 9 {
            return None;
        }
        let k = match k {
            Value::Number(x)
                if x.as_i64().is_none() && x.as_f64().is_some_and(|f| f.fract() == 0.0) =>
            {
                x.as_f64()
                    .map(|f| {
                        if f.abs() < 1e18 {
                            Value::from(f as i64)
                        } else {
                            k.clone()
                        }
                    })
                    .unwrap_or(Value::Null)
            }
            other => other.clone(),
        };
        match &k {
            Value::Number(x) if x.as_i64().is_some_and(|i| (0..=100000).contains(&i)) => {
                percorso.push(k)
            }
            Value::String(s)
                if !s.is_empty()
                    && s.chars().count() <= 60
                    && !VIETATE.contains(&s.as_str())
                    && !RE_CONTROLLO.is_match(s) =>
            {
                percorso.push(k)
            }
            _ => return None,
        }
    }
    if !percorso
        .first()
        .and_then(Value::as_str)
        .is_some_and(|r| RADICI.contains(&r))
    {
        return None;
    }
    let mut fuori = json!({"op": op, "percorso": percorso});
    if op == "metti" || op == "aggiungi" {
        let valore = pulito(o.get("valore")?, 0);
        if crate::pyjson::largo(&valore).chars().count() > MAX_VALORE {
            return None;
        }
        fuori["valore"] = valore;
    } else if let Some(d) = get(o, "dove").as_object().filter(|d| !d.is_empty()) {
        let mut dove = Map::new();
        for (k, v) in d.iter().take(4) {
            if !v.is_array() && !v.is_object() {
                dove.insert(py::taglia(k, 40), v.clone());
            }
        }
        if !dove.is_empty() {
            fuori["dove"] = Value::Object(dove);
        }
    }
    Some(fuori)
}

fn macro_(x: &Value) -> [(&'static str, Option<f64>); 4] {
    [
        ("kcal", n(get(x, "kcal"), 0.0, 6000.0, 0)),
        ("p", n(get(x, "proteine"), 0.0, 500.0, 1)),
        ("c", n(get(x, "carboidrati"), 0.0, 900.0, 1)),
        ("f", n(get(x, "grassi"), 0.0, 500.0, 1)),
    ]
}

fn ids(v: &Value, quanti: usize) -> Vec<Value> {
    lista(v, quanti)
        .iter()
        .map(id)
        .filter(|i| !i.is_empty())
        .map(Value::String)
        .collect()
}

fn scelta<'a>(v: &'a Value, ammessi: &[&str], base: &'a str) -> &'a str {
    v.as_str().filter(|s| ammessi.contains(s)).unwrap_or(base)
}

/// One action cleaned, with only the fields of its type, or None if it does not stand up.
pub fn azione(x: &Value) -> Option<Value> {
    let tipo = get(x, "tipo").as_str().filter(|t| TIPI.contains(t))?;
    let mut a = Map::new();
    a.insert("tipo".into(), Value::String(tipo.into()));
    let s = |v: String| Value::String(v);
    if [
        "mangiato",
        "pasto_fatto",
        "togli_voce",
        "acqua",
        "movimento",
        "dose",
        "cambia_voce",
    ]
    .contains(&tipo)
    {
        a.insert("giorno".into(), s(giorno(get(x, "giorno")))); // empty = today: the app knows what day it is for the person
    }
    match tipo {
        "mangiato" => {
            let pasto = id(get(x, "pasto"));
            let pasto = if pasto.is_empty() {
                "fuori".to_string()
            } else {
                pasto
            };
            let nome = t(get(x, "nome"), 80);
            a.insert("pasto".into(), s(pasto.clone()));
            a.insert("nome".into(), s(nome.clone()));
            a.insert("quantita".into(), s(t(get(x, "quantita"), 40)));
            a.insert(
                "al_posto".into(),
                s(scelta(get(x, "al_posto"), &["niente", "tutto", "parte"], "niente").into()),
            );
            a.insert("tolti".into(), Value::Array(ids(get(x, "tolti"), 12)));
            a.insert("foto_di".into(), s(id(get(x, "foto_di"))));
            let m = macro_(x);
            for (k, v) in m {
                a.insert(k.into(), nv(v));
            }
            if nome.is_empty() || m[0].1.is_none() {
                return None;
            }
            for k in ["p", "c", "f"] {
                let v = o_zero(&a[k]);
                a.insert(k.into(), v);
            }
            if pasto == "fuori" {
                // outside meals there is no planned dish to replace
                a.insert("al_posto".into(), s("niente".into()));
                a.insert("tolti".into(), json!([]));
            }
        }
        "pasto_fatto" => {
            let pasto = id(get(x, "pasto"));
            let fatto = get(x, "fatto") != &Value::Bool(false);
            a.insert("pasto".into(), s(pasto.clone()));
            a.insert("fatto".into(), Value::Bool(fatto));
            if pasto.is_empty() {
                return None;
            }
            // eaten in part: the ingredients eaten (solo) or those left on the plate (senza)
            for k in ["solo", "senza"] {
                let l = ids(get(x, k), 12);
                if !l.is_empty() && fatto {
                    a.insert(k.into(), Value::Array(l));
                }
            }
        }
        "dose" => {
            let (pasto, cibo, grammi) = (
                id(get(x, "pasto")),
                id(get(x, "cibo")),
                n(get(x, "grammi"), 0.0, 3000.0, 1),
            );
            a.insert("pasto".into(), s(pasto.clone()));
            a.insert("cibo".into(), s(cibo.clone()));
            a.insert("grammi".into(), nv(grammi));
            if pasto.is_empty() || cibo.is_empty() || grammi.is_none() {
                return None;
            }
        }
        "cambia_voce" => {
            let (voce, quantita) = (id(get(x, "voce")), t(get(x, "quantita"), 40));
            a.insert("voce".into(), s(voce.clone()));
            a.insert("quantita".into(), s(quantita.clone()));
            if voce.is_empty() || !RE_QUANTITA.is_match(&quantita) {
                return None;
            }
            if !get(x, "kcal").is_null() {
                let m = macro_(x);
                if m[0].1.is_some() {
                    for (k, v) in m {
                        a.insert(k.into(), o_zero(&nv(v)));
                    }
                }
            }
        }
        "togli_voce" => {
            let voce = id(get(x, "voce"));
            a.insert("voce".into(), s(voce.clone()));
            if voce.is_empty() {
                return None;
            }
        }
        "acqua" => {
            let ml = n(get(x, "ml"), 0.0, 3000.0, 0);
            a.insert("ml".into(), nv(ml));
            if !ml.is_some_and(|m| m != 0.0) {
                return None;
            }
        }
        "movimento" => {
            let minuti = n(get(x, "minuti"), 0.0, 600.0, 0);
            a.insert(
                "attivita".into(),
                s(scelta(get(x, "attivita"), &ATTIVITA, "altro").into()),
            );
            a.insert("minuti".into(), nv(minuti));
            if !minuti.is_some_and(|m| m != 0.0) {
                return None;
            }
        }
        "peso" => {
            let kg = n(get(x, "kg"), 30.0, 250.0, 2);
            a.insert("kg".into(), nv(kg));
            if kg.is_none() || !vero(get(x, "kg")) {
                return None;
            }
        }
        "cambia_pasto" | "ripristina_pasto" => {
            let (g, pasto) = (giorni(get(x, "giorni")), id(get(x, "pasto")));
            a.insert("giorni".into(), json!(g));
            a.insert("pasto".into(), s(pasto.clone()));
            let mut ricetta_vuota = false;
            if tipo == "cambia_pasto" {
                let r = id(get(x, "ricetta"));
                ricetta_vuota = r.is_empty();
                a.insert("ricetta".into(), s(r));
            }
            if g.is_empty() || pasto.is_empty() || ricetta_vuota {
                return None;
            }
        }
        "nuovo_piatto" => {
            let mut ingredienti = Vec::new();
            for i in lista(get(x, "ingredienti"), 12) {
                if !i.is_object() {
                    continue;
                }
                let Some(grammi) = n(get(i, "grammi"), 0.0, 2000.0, 0).filter(|g| *g != 0.0) else {
                    continue;
                };
                let palestra = n(get(i, "grammi_palestra"), 0.0, 2000.0, 0)
                    .filter(|g| *g != 0.0)
                    .unwrap_or(grammi);
                let cibo = id(get(i, "cibo"));
                let mut voce = Map::new();
                voce.insert("cibo".into(), s(cibo.clone()));
                voce.insert("grammi".into(), py::n_f(grammi));
                voce.insert("grammi_palestra".into(), py::n_f(palestra));
                if cibo.is_empty() {
                    let m = macro_(i);
                    let nome = t(get(i, "nome"), 50);
                    voce.insert("nome".into(), s(nome.clone()));
                    voce.insert(
                        "reparto".into(),
                        s(scelta(get(i, "reparto"), &REPARTI, "Dispensa").into()),
                    );
                    for (k, v) in m {
                        voce.insert(k.into(), nv(v));
                    }
                    if nome.is_empty() || m[0].1.is_none() {
                        continue;
                    }
                    for k in ["p", "c", "f"] {
                        let v = o_zero(&voce[k]);
                        voce.insert(k.into(), v);
                    }
                }
                ingredienti.push(Value::Object(voce));
            }
            let (nome, pasto) = (t(get(x, "nome"), 60), id(get(x, "pasto")));
            let passi: Vec<String> = lista(get(x, "passi"), 6)
                .iter()
                .map(|p| t(p, 200))
                .filter(|p| !p.is_empty())
                .collect();
            let vuoti = ingredienti.is_empty();
            a.insert("nome".into(), s(nome.clone()));
            a.insert("pasto".into(), s(pasto.clone()));
            a.insert("ingredienti".into(), Value::Array(ingredienti));
            a.insert("passi".into(), json!(passi));
            // `_n(...) or 15`: missing or zero minutes become the integer 15
            let minuti = n(get(x, "minuti"), 0.0, 240.0, 0)
                .filter(|m| *m != 0.0)
                .map(py::n_f)
                .unwrap_or(Value::from(15));
            a.insert("minuti".into(), minuti);
            a.insert("foto_di".into(), s(id(get(x, "foto_di"))));
            a.insert("giorni".into(), json!(giorni(get(x, "giorni"))));
            if nome.is_empty() || pasto.is_empty() || vuoti {
                return None;
            }
        }
        "togli_piatto" => {
            let r = id(get(x, "ricetta"));
            a.insert("ricetta".into(), s(r.clone()));
            if r.is_empty() {
                return None;
            }
        }
        "tema" => {
            let aspetto = get(x, "aspetto")
                .as_str()
                .filter(|v| ["chiaro", "scuro"].contains(v))?;
            a.insert("aspetto".into(), s(aspetto.into()));
        }
        "misure" => {
            let cm = if get(x, "cm").is_object() {
                get(x, "cm")
            } else {
                x
            };
            let mut m = Map::new();
            for k in MISURE {
                if let Some(v) = n(get(cm, k), 10.0, 300.0, 1).filter(|v| *v != 0.0) {
                    m.insert(k.into(), py::n_f(v));
                }
            }
            if m.is_empty() {
                return None;
            }
            a.insert("cm".into(), Value::Object(m));
        }
        "obiettivo" => {
            // out-of-range numbers drop the action: silently fixing them would change a target nobody asked for
            let g = match py::testo_o(get(x, "giorni")).to_lowercase().as_str() {
                "palestra" | "train" | "allenamento" => "palestra",
                "riposo" | "rest" => "riposo",
                _ => "tutti",
            };
            a.insert("giorni".into(), s(g.into()));
            for (k, nome, lo, hi) in [
                ("kcal", "kcal", 800.0, 6000.0),
                ("p", "proteine", 20.0, 400.0),
                ("c", "carboidrati", 20.0, 900.0),
                ("f", "grassi", 10.0, 300.0),
            ] {
                let Some(v) = numero_non_bool(get(x, nome)).filter(|v| *v != 0.0) else {
                    continue;
                };
                if !(lo..=hi).contains(&v) {
                    return None;
                }
                a.insert(k.into(), Value::from(py::round_int(v)));
            }
            if a.len() < 3 {
                return None;
            }
        }
        "quantita" => {
            let grammi =
                numero_non_bool(get(x, "grammi")).filter(|g| (0.0..=2000.0).contains(g))?;
            let palestra = numero_non_bool(get(x, "grammi_palestra"))
                .filter(|g| (0.0..=2000.0).contains(g))
                .unwrap_or(grammi);
            let (ricetta, cibo) = (id(get(x, "ricetta")), id(get(x, "cibo")));
            a.insert("ricetta".into(), s(ricetta.clone()));
            a.insert("cibo".into(), s(cibo.clone()));
            a.insert("grammi".into(), Value::from(py::round_int(grammi)));
            a.insert(
                "grammi_palestra".into(),
                Value::from(py::round_int(palestra)),
            );
            if ricetta.is_empty() || cibo.is_empty() {
                return None;
            }
        }
        "orario" => {
            let testo = py::testo_o(get(x, "ora")).trim().to_string();
            let ora = RE_ORA
                .captures(&testo)
                .map(|c| format!("{:02}:{}", c[1].parse::<u32>().unwrap_or(0), &c[2]))
                .unwrap_or_default();
            let pasto = id(get(x, "pasto"));
            a.insert("pasto".into(), s(pasto.clone()));
            a.insert("ora".into(), s(ora.clone()));
            if pasto.is_empty() || ora.is_empty() {
                return None;
            }
        }
        "modifica" => {
            let operazioni: Vec<Value> = lista(get(x, "operazioni"), 12)
                .iter()
                .filter_map(operazione)
                .collect();
            // one discarded operation drops the whole change: doing only part of it would leave the data halfway
            let tutte = lista(get(x, "operazioni"), 99).len();
            let quante = operazioni.len();
            a.insert("descrizione".into(), s(t(get(x, "descrizione"), 160)));
            a.insert("operazioni".into(), Value::Array(operazioni));
            if quante == 0 || quante != tutte {
                return None;
            }
        }
        _ => {}
    }
    Some(Value::Object(a))
}

/// Foods whose grams of protein, carbs and fat would give more calories than written (some slack is normal).
/// Returns (index of the action, kcal the grams would give).
pub fn conti_storti(azioni: &Value) -> Vec<(usize, f64)> {
    let mut storti = Vec::new();
    for (i, x) in azioni.as_array().into_iter().flatten().enumerate() {
        if !x.is_object() || get(x, "tipo").as_str() != Some("mangiato") {
            continue;
        }
        let num = |k: &str| py::float(py::o(get(x, k), &Value::from(0)));
        let (Some(kcal), Some(p), Some(c), Some(f)) = (
            num("kcal"),
            num("proteine"),
            num("carboidrati"),
            num("grassi"),
        ) else {
            continue;
        };
        let dai_grammi = 4.0 * p + 4.0 * c + 9.0 * f;
        if kcal > 0.0 && dai_grammi > kcal * 1.2 + 25.0 {
            storti.push((i, dai_grammi));
        }
    }
    storti
}

const NOMINATI: [(&str, &str); 4] = [
    ("kcal", r"(?i)calori|kcal"),
    ("proteine", r"(?i)protein"),
    ("carboidrati", r"(?i)carbo"),
    ("grassi", r"(?i)grass"),
];
static RE_NOMINATI: LazyLock<Vec<(&'static str, Regex)>> =
    LazyLock::new(|| NOMINATI.iter().map(|(c, r)| (*c, py::re(r))).collect());

/// Whoever asks "calories to 2000" did not ask to touch protein, carbs and fat: of the "obiettivo" action only the
/// numbers the person talked about stay; if none was named it stays as it is.
pub fn solo_nominati(azioni: &mut Value, domanda: &str) {
    let nominati: Vec<&str> = RE_NOMINATI
        .iter()
        .filter(|(_, r)| r.is_match(domanda))
        .map(|(c, _)| *c)
        .collect();
    if nominati.is_empty() {
        return;
    }
    for x in azioni.as_array_mut().into_iter().flatten() {
        if let Some(o) = x
            .as_object_mut()
            .filter(|o| o.get("tipo").and_then(Value::as_str) == Some("obiettivo"))
        {
            for (campo, _) in NOMINATI {
                if !nominati.contains(&campo) {
                    o.shift_remove(campo);
                }
            }
        }
    }
}

// ---------- schema for the VM's AI ----------
fn elenco_id(v: &Value) -> Vec<Value> {
    ids(v, 300)
}

/// The schema the VM's AI answer must follow. Where an identifier is needed there are only the person's real ones.
pub fn forma_locale(ids_v: &Value) -> Value {
    let vuoto = json!({});
    let ids_v = if ids_v.is_object() { ids_v } else { &vuoto };
    let (pasti, ricette, cibi, voci) = (
        elenco_id(get(ids_v, "pasti")),
        elenco_id(get(ids_v, "ricette")),
        elenco_id(get(ids_v, "cibi")),
        elenco_id(get(ids_v, "voci")),
    );
    let date: Vec<Value> = lista(get(ids_v, "giorni"), 2)
        .iter()
        .map(giorno)
        .filter(|g| !g.is_empty())
        .map(Value::String)
        .collect();
    let testo = json!({"type": "string"});
    let numero = json!({"type": "number"});
    let uno_di = |valori: &Vec<Value>| {
        if valori.is_empty() {
            testo.clone()
        } else {
            json!({"type": "string", "enum": valori})
        }
    };
    let giorni = json!({"type": "array", "items": {"type": "integer", "enum": [0, 1, 2, 3, 4, 5, 6]}, "minItems": 1, "maxItems": 7});
    let azione = |tipo: &str, campi: Vec<(&str, Value)>, obbligatori: Option<Vec<&str>>| {
        let mut props = Map::new();
        props.insert("tipo".into(), json!({"type": "string", "enum": [tipo]}));
        let mut req = vec!["tipo".to_string()];
        let tutti: Vec<String> = campi.iter().map(|(k, _)| (*k).to_string()).collect();
        for (k, v) in campi {
            props.insert(k.into(), v);
        }
        req.extend(
            obbligatori
                .map(|o| o.into_iter().map(String::from).collect())
                .unwrap_or(tutti),
        );
        json!({"type": "object", "properties": props, "required": req, "additionalProperties": false})
    };
    let quando = |mut campi: Vec<(&'static str, Value)>| {
        if !date.is_empty() {
            campi.insert(0, ("giorno", json!({"type": "string", "enum": date})));
        }
        campi
    };
    let pasti_fuori: Vec<Value> = if pasti.is_empty() {
        vec![]
    } else {
        pasti.iter().cloned().chain([json!("fuori")]).collect()
    };
    let mut azioni = vec![
        azione(
            "mangiato",
            quando(vec![
                ("pasto", uno_di(&pasti_fuori)),
                ("nome", testo.clone()),
                ("quantita", testo.clone()),
                ("kcal", numero.clone()),
                ("proteine", numero.clone()),
                ("carboidrati", numero.clone()),
                ("grassi", numero.clone()),
                (
                    "al_posto",
                    json!({"type": "string", "enum": ["tutto", "niente", "parte"]}),
                ),
                (
                    "tolti",
                    json!({"type": "array", "items": uno_di(&cibi), "maxItems": 4}),
                ),
            ]),
            None,
        ),
        azione(
            "pasto_fatto",
            quando(vec![
                ("pasto", uno_di(&pasti)),
                ("fatto", json!({"type": "boolean"})),
                (
                    "senza",
                    json!({"type": "array", "items": uno_di(&cibi), "maxItems": 8}),
                ),
            ]),
            None,
        ),
        azione(
            "dose",
            quando(vec![
                ("pasto", uno_di(&pasti)),
                ("cibo", uno_di(&cibi)),
                ("grammi", numero.clone()),
            ]),
            None,
        ),
        azione("acqua", vec![("ml", numero.clone())], None),
        azione(
            "movimento",
            vec![
                ("attivita", json!({"type": "string", "enum": ATTIVITA})),
                ("minuti", numero.clone()),
            ],
            None,
        ),
        azione("peso", vec![("kg", numero.clone())], None),
        azione(
            "cambia_pasto",
            vec![
                ("giorni", giorni.clone()),
                ("pasto", uno_di(&pasti)),
                ("ricetta", uno_di(&ricette)),
            ],
            None,
        ),
        azione(
            "ripristina_pasto",
            vec![("giorni", giorni.clone()), ("pasto", uno_di(&pasti))],
            None,
        ),
        azione(
            "obiettivo",
            vec![
                (
                    "giorni",
                    json!({"type": "string", "enum": ["palestra", "riposo", "tutti"]}),
                ),
                ("kcal", numero.clone()),
                ("proteine", numero.clone()),
                ("carboidrati", numero.clone()),
                ("grassi", numero.clone()),
            ],
            Some(vec!["giorni"]),
        ),
        azione(
            "quantita",
            vec![
                ("ricetta", uno_di(&ricette)),
                ("cibo", uno_di(&cibi)),
                ("grammi", numero.clone()),
                ("grammi_palestra", numero.clone()),
            ],
            None,
        ),
        azione(
            "orario",
            vec![("pasto", uno_di(&pasti)), ("ora", testo.clone())],
            None,
        ),
    ];
    if !voci.is_empty() {
        azioni.push(azione("togli_voce", vec![("voce", uno_di(&voci))], None));
        azioni.push(azione(
            "cambia_voce",
            vec![("voce", uno_di(&voci)), ("quantita", testo.clone())],
            None,
        ));
    }
    json!({"type": "object", "properties": {"azioni": {"type": "array", "items": {"anyOf": azioni}, "maxItems": 4}, "risposta": testo},
           "required": ["azioni", "risposta"], "additionalProperties": false})
}

#[cfg(test)]
mod test {
    use super::*;

    #[test]
    fn azioni_come_prova_server() {
        let pizza = azione(&json!({"tipo": "mangiato", "pasto": "cena", "nome": "Pizza margherita", "quantita": "1 pizza", "kcal": 820,
            "proteine": 33, "carboidrati": 105, "grassi": 28, "al_posto": "tutto", "foto_di": "cena-libera"})).unwrap();
        assert_eq!(
            crate::pyjson::compatto(&pizza),
            r#"{"tipo":"mangiato","giorno":"","pasto":"cena","nome":"Pizza margherita","quantita":"1 pizza","al_posto":"tutto","tolti":[],"foto_di":"cena-libera","kcal":820.0,"p":33.0,"c":105.0,"f":28.0}"#
        );
        assert!(azione(&json!({"tipo": "dose", "pasto": "pranzo", "cibo": "riso"})).is_none());
        assert!(
            azione(&json!({"tipo": "cambia_voce", "voce": "abc123", "quantita": "tanta"}))
                .is_none()
        );
        assert_eq!(
            azione(&json!({"tipo": "orario", "pasto": "cena", "ora": "21.00"})).unwrap()["ora"],
            "21:00"
        );
        assert_eq!(
            azione(&json!({"tipo": "misure", "cm": {"vita": 78.5, "collo": 37}})).unwrap(),
            json!({"tipo": "misure", "cm": {"vita": 78.5, "collo": 37.0}})
        );
        let piatto = azione(&json!({"tipo": "nuovo_piatto", "nome": "Riso", "pasto": "cena", "giorni": [1],
            "ingredienti": [{"cibo": "", "nome": "Ceci in scatola", "grammi": 120, "kcal": 120, "proteine": 7, "carboidrati": 15, "grassi": 2.5}]})).unwrap();
        assert_eq!(piatto["minuti"], 15);
        assert_eq!(piatto["ingredienti"][0]["p"], 7.0);
        let pollo = azione(&json!({"tipo": "mangiato", "pasto": "pranzo", "nome": "Petto di pollo", "quantita": "137 g", "kcal": 148,
            "proteine": 32, "carboidrati": 0, "grassi": 2, "al_posto": "parte", "tolti": ["pollo"]})).unwrap();
        assert_eq!(
            (
                pollo["al_posto"].as_str(),
                pollo["tolti"].clone(),
                pollo["c"].clone()
            ),
            (Some("parte"), json!(["pollo"]), json!(0))
        );
        assert!(azione(&json!({"tipo": "modifica", "descrizione": "x", "operazioni": [{"op": "metti", "percorso": ["chat", 0, "t"], "valore": "ciao"}]})).is_none());
        let m = azione(&json!({"tipo": "modifica", "descrizione": "x", "operazioni": [{"op": "metti", "percorso": ["mie", "obiettivi", "train", "kcal"], "valore": 2500}]})).unwrap();
        assert_eq!(
            m["operazioni"][0],
            json!({"op": "metti", "percorso": ["mie", "obiettivi", "train", "kcal"], "valore": 2500})
        );
    }

    #[test]
    fn obiettivo_solo_nominati() {
        // raw model output, as in guidata: the long names, before `azione` shortens them
        let pieno = || json!([{"tipo": "obiettivo", "giorni": "palestra", "kcal": 2000, "proteine": 150, "carboidrati": 200, "grassi": 55}]);
        let mut a = pieno();
        solo_nominati(&mut a, "porta le calorie a 2000, obiettivo pieno");
        assert_eq!(
            a,
            json!([{"tipo": "obiettivo", "giorni": "palestra", "kcal": 2000}])
        );
        let mut a = pieno();
        solo_nominati(&mut a, "calorie a 2000 e proteine a 150, obiettivo pieno");
        assert_eq!(
            azione(&a[0]).unwrap(),
            json!({"tipo": "obiettivo", "giorni": "palestra", "kcal": 2000, "p": 150})
        );
    }

    #[test]
    fn forma_come_prova_server() {
        let f = forma_locale(
            &json!({"pasti": ["pranzo"], "cibi": ["pollo", "riso"], "giorni": ["2026-10-26"]}),
        );
        let mangiato = &f["properties"]["azioni"]["items"]["anyOf"][0];
        assert_eq!(
            mangiato["properties"]["tolti"]["items"]["enum"],
            json!(["pollo", "riso"])
        );
        assert_eq!(mangiato["required"][1], "giorno");
    }
}
