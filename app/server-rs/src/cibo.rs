//! Foods for the diary (cibo.py): Open Food Facts products by barcode or name, reduced to the fields the app uses,
//! and the estimate of a dish from a photo.

use crate::ai::{self, Immagine};
use crate::ai_http;
use crate::chiavi::Motore;
use crate::errore::{Esito, Problema};
use crate::py::{self, get};
use base64::Engine;
use base64::engine::DecodePaddingMode;
use base64::engine::general_purpose::{GeneralPurpose, GeneralPurposeConfig, STANDARD};
use regex::Regex;
use serde_json::{Map, Value, json};
use std::collections::HashSet;
use std::sync::LazyLock;

const CAMPI: &str = "code,product_name,product_name_it,generic_name_it,brands,quantity,product_quantity,serving_size,serving_quantity,\
nutriments,image_front_url,image_front_small_url,image_url,\
nutriscore_grade,nova_group,additives_tags,allergens_tags,traces_tags,labels_tags,categories_tags,\
ingredients_text_it,ingredients_text";
const OFF_PRODOTTO: &str = "https://world.openfoodfacts.org/api/v2/product/";
const OFF_CERCA: &str = "https://search.openfoodfacts.org/search?";
const OFF_IMMAGINI: &str = "https://images.openfoodfacts.org/";
pub const MAX_FOTO: usize = 1_500_000;

const SISTEMA_FOTO: &str = include_str!("../testi/sistema_foto.txt");
pub static STRUMENTO_FOTO: LazyLock<Value> = LazyLock::new(|| {
    serde_json::from_str(include_str!("../testi/strumento_foto.json")).unwrap_or(Value::Null)
});

/// `base64.b64decode(s, validate=True)`: standard alphabet, padding required, nothing else allowed.
const B64_STRETTO: GeneralPurpose = GeneralPurpose::new(
    &base64::alphabet::STANDARD,
    GeneralPurposeConfig::new()
        .with_decode_padding_mode(DecodePaddingMode::RequireCanonical)
        .with_decode_allow_trailing_bits(true),
);

static RE_SPAZI: LazyLock<Regex> = LazyLock::new(|| py::re(r"\s+"));
static RE_CODA: LazyLock<Regex> = LazyLock::new(|| py::re(r"[\s(\[,;:\-]+$"));
static RE_MULTI: LazyLock<Regex> =
    LazyLock::new(|| py::re(r"(?i)(\d+)\s*[x×*]\s*(\d+(?:[.,]\d+)?)\s*(kg|gr|g|ml|cl|l)\b"));
static RE_SOLO: LazyLock<Regex> =
    LazyLock::new(|| py::re(r"(?i)(\d+(?:[.,]\d+)?)\s*(kg|gr|g|ml|cl|l)\b"));
static RE_RECINTO: LazyLock<Regex> = LazyLock::new(|| py::re(r"^```(?:json)?\s*|\s*```$"));
static RE_NON_CIFRE: LazyLock<Regex> = LazyLock::new(|| py::re(r"\D"));

/// `_num(v)`: a number, also written with a comma; None for anything else, NaN or infinite.
pub fn num(v: &Value) -> Option<f64> {
    let f = match v {
        Value::Number(n) => n.as_f64(),
        Value::String(s) => num_str(s),
        _ => None,
    }?;
    f.is_finite().then_some(f)
}

pub fn num_str(s: &str) -> Option<f64> {
    py::float_str(&s.replace(',', ".")).filter(|f| f.is_finite())
}

fn grammi(valore: &str, unita: &str) -> Option<f64> {
    let v = num_str(valore)?;
    Some(
        v * match unita.to_lowercase().as_str() {
            "kg" | "l" => 1000.0,
            "cl" => 10.0,
            _ => 1.0,
        },
    )
}

/// `_pulisci(testo, lungo)`: spaces collapsed, no trailing punctuation, ALL CAPS turned to Title Case, cut.
pub fn pulisci(testo: &str, lungo: usize) -> String {
    let t = RE_SPAZI.replace_all(testo, " ");
    let t = RE_CODA.replace(t.trim(), "").into_owned();
    let lettere: Vec<char> = t.chars().filter(|c| c.is_alphabetic()).collect();
    let maiuscole = lettere.iter().filter(|c| c.is_uppercase()).count();
    let t = if lettere.len() > 4 && maiuscole as f64 > 0.6 * lettere.len() as f64 {
        py::title(&t)
    } else {
        t
    };
    py::taglia(&t, lungo)
}

/// `_pulisci(v)` for any JSON value (`str(v or "")`).
pub fn pulisci_v(v: &Value, lungo: usize) -> String {
    pulisci(&py::testo_o(v), lungo)
}

fn pezzi(p: &Value) -> (Value, Value, Value) {
    let mut conf = num(get(p, "product_quantity"));
    let mut pz = num(get(p, "serving_quantity"));
    let mut nome = json!(["porzione", "porzioni"]);
    let testo = py::testo_o(get(p, "quantity"));
    if let Some(m) = RE_MULTI.captures(&testo) {
        // "4 x 20 g": four pieces of 20 grams
        let quanti: Option<i64> = m[1].parse().ok();
        let uno = grammi(&m[2], &m[3]);
        if let (Some(q), Some(u)) = (quanti, uno)
            && 1 < q
            && q <= 60
            && u != 0.0
        {
            pz = Some(u);
            nome = json!(["pezzo", "pezzi"]);
            if !conf.is_some_and(|c| c != 0.0) {
                conf = Some(q as f64 * u);
            }
        }
    }
    if !conf.is_some_and(|c| c != 0.0) {
        conf = RE_SOLO.captures(&testo).and_then(|m| grammi(&m[1], &m[2]));
    }
    if pz.is_some_and(|v| !(1.0..=1500.0).contains(&v)) {
        pz = None;
    }
    if conf.is_some_and(|v| !(1.0..=20000.0).contains(&v)) {
        conf = None;
    }
    let pz = pz
        .filter(|v| *v != 0.0)
        .map(|v| py::n_f(py::round(v, 1)))
        .unwrap_or(Value::Null);
    let conf = conf
        .filter(|v| *v != 0.0)
        .map(|v| Value::from(py::round_int(v)))
        .unwrap_or(Value::Null);
    (pz, nome, conf)
}

/// Iterating a JSON value as Python does in `for t in (v or [])`: list items, string characters, object keys.
fn voci(v: &Value) -> Vec<Value> {
    match v {
        Value::Array(a) => a.clone(),
        Value::String(s) => s.chars().map(|c| Value::String(c.to_string())).collect(),
        Value::Object(o) => o.keys().map(|k| Value::String(k.clone())).collect(),
        _ => vec![],
    }
}

fn extra(p: &Value) -> Value {
    let n = py::o(get(p, "nutriments"), &py::NULLA);
    let val = |k: &str| {
        num(get(n, k))
            .map(|v| py::n_f(py::round(v.clamp(0.0, 100.0), 2)))
            .unwrap_or(Value::Null)
    };
    let nomi = |k: &str, quanti: usize| -> Vec<String> {
        voci(get(p, k))
            .iter()
            .filter_map(Value::as_str)
            .map(|t| t.split_once(':').map(|(_, b)| b).unwrap_or(t).to_string())
            .take(quanti)
            .collect()
    };
    let mut sale = val("salt_100g");
    if sale.is_null()
        && let Some(sodio) = num(get(n, "sodium_100g"))
    {
        sale = py::n_f(py::round((sodio * 2.5).min(100.0), 2));
    }
    let voto = py::testo_o(get(p, "nutriscore_grade")).to_lowercase();
    let categorie = nomi("categories_tags", 40);
    let etichette = nomi("labels_tags", 40);
    let nova = match get(p, "nova_group") {
        Value::Number(x) if x.as_i64().is_some_and(|i| (1..=4).contains(&i)) => {
            Value::from(x.as_i64().unwrap_or(0))
        }
        Value::String(s) if ["1", "2", "3", "4"].contains(&s.as_str()) => {
            Value::from(s.parse::<i64>().unwrap_or(0))
        }
        _ => Value::Null,
    };
    let ingredienti = pulisci_v(
        py::o(get(p, "ingredients_text_it"), get(p, "ingredients_text")),
        700,
    );
    json!({
        "sat": val("saturated-fat_100g"), "zuc": val("sugars_100g"), "fib": val("fiber_100g"), "sale": sale,
        "alcol": val("alcohol_100g"),
        "nutri": if ["a", "b", "c", "d", "e"].contains(&voto.as_str()) { Value::String(voto) } else { Value::Null },
        "nova": nova,
        "additivi": nomi("additives_tags", 20).iter().map(|a| a.to_uppercase()).collect::<Vec<_>>(),
        "allergeni": nomi("allergens_tags", 12), "tracce": nomi("traces_tags", 12),
        "senza_lattosio": etichette.iter().any(|e| e.contains("lactose") || e.contains("lattosio")),
        "bevanda": categorie.iter().any(|c| c == "beverages" || c.ends_with("-beverages") || ["waters", "juices", "sodas", "beers", "wines"].contains(&c.as_str())),
        "ingredienti": if ingredienti.is_empty() { Value::Null } else { Value::String(ingredienti) },
    })
}

/// kcal per 100 g. When kcal and kJ disagree, the one closer to what proteins, carbs and fats give wins.
fn kcal_100g(n: &Value, pr: Option<f64>, ca: Option<f64>, gr: Option<f64>) -> Option<f64> {
    let kcal = num(get(n, "energy-kcal_100g"));
    let kj = num(get(n, "energy-kj_100g"))
        .filter(|v| *v != 0.0)
        .or_else(|| num(get(n, "energy_100g")));
    let da_kj = kj.filter(|v| *v != 0.0).map(|v| v / 4.184);
    let dai_grammi = match (pr, ca, gr) {
        (Some(p), Some(c), Some(g)) => Some(4.0 * p + 4.0 * c + 9.0 * g),
        _ => None,
    };
    let Some(kcal) = kcal else {
        return da_kj.or(dai_grammi);
    };
    if let (Some(dk), Some(dg)) = (da_kj, dai_grammi.filter(|v| *v != 0.0))
        && (kcal - dk).abs() > 15f64.max(dk * 0.15)
    {
        return Some(if (dk - dg).abs() < (kcal - dg).abs() {
            dk
        } else {
            kcal
        });
    }
    Some(kcal)
}

pub fn normalizza(p: &Value) -> Value {
    let n = py::o(get(p, "nutriments"), &py::NULLA);
    let (pr, ca, gr) = (
        num(get(n, "proteins_100g")),
        num(get(n, "carbohydrates_100g")),
        num(get(n, "fat_100g")),
    );
    let kcal = kcal_100g(n, pr, ca, gr).filter(|k| (0.0..=950.0).contains(k));
    let marca = match get(p, "brands") {
        Value::Array(a) => a.first().cloned().unwrap_or(Value::String(String::new())),
        v => v.clone(),
    };
    let marca_t = py::testo_o(&marca);
    let marca = pulisci(marca_t.split(',').next().unwrap_or(""), 40);
    let (pz, pzn, conf) = pezzi(p);
    let limita =
        |v: Option<f64>| py::n_f(v.map(|v| py::round(v.clamp(0.0, 100.0), 1)).unwrap_or(0.0));
    let foto = ["image_front_url", "image_front_small_url", "image_url"]
        .iter()
        .filter_map(|k| get(p, k).as_str())
        .find(|u| u.starts_with(OFF_IMMAGINI))
        .map(|u| Value::String(u.to_string()))
        .unwrap_or(Value::Null);
    let nome = pulisci_v(
        py::o(
            get(p, "product_name_it"),
            py::o(get(p, "product_name"), get(p, "generic_name_it")),
        ),
        80,
    );
    json!({
        "ean": py::testo_o(get(p, "code")),
        "n": if nome.is_empty() { "Prodotto senza nome".to_string() } else { nome },
        "marca": if marca.is_empty() { Value::Null } else { Value::String(marca) },
        "kcal": kcal.map(|k| Value::from(py::round_int(k))).unwrap_or(Value::Null),
        "p": limita(pr), "c": limita(ca), "f": limita(gr),
        "pz": pz, "pzn": pzn, "conf": conf, "img": foto, "fonte": "off", "x": extra(p),
    })
}

fn scarica(url: &str) -> Result<Value, Option<u16>> {
    ai_http::prendi(url, &[("Accept", "application/json")], 8.0)
}

/// The product with that barcode, or None if Open Food Facts does not know it.
pub fn prodotto_ean(ean: &str) -> Esito<Option<Value>> {
    let d = match scarica(&format!("{OFF_PRODOTTO}{ean}.json?fields={CAMPI}")) {
        Ok(d) => d,
        Err(Some(404)) => return Ok(None),
        Err(_) => {
            return Err(Problema::new(
                502,
                "Il catalogo dei prodotti non risponde. Riprova, oppure scrivi i valori dell'etichetta.",
            ));
        }
    };
    let stato_zero = matches!(get(&d, "status"), Value::Number(n) if n.as_f64() == Some(0.0))
        || get(&d, "status") == &Value::Bool(false);
    if !py::vero(get(&d, "product")) || stato_zero {
        return Ok(None);
    }
    let mut voce = normalizza(get(&d, "product"));
    if voce["kcal"].is_null() && voce["n"] == "Prodotto senza nome" {
        return Ok(None); // empty card: the code is there but nobody ever wrote anything
    }
    voce["ean"] = Value::String(ean.to_string());
    Ok(Some(voce))
}

/// Up to twelve products on sale matching the text, only those with calories.
pub fn cerca(testo: &str) -> Esito<Vec<Value>> {
    let url = format!(
        "{OFF_CERCA}q={}&langs=it&page_size=24&fields={}",
        py::quote_plus(testo),
        py::quote_plus(CAMPI)
    );
    let d = scarica(&url).map_err(|_| {
        Problema::new(
            502,
            "La ricerca dei prodotti non risponde. Riprova tra poco.",
        )
    })?;
    let mut visti = HashSet::new();
    let mut trovati = Vec::new();
    for voce in voci(py::o(get(&d, "hits"), &py::NULLA))
        .iter()
        .map(normalizza)
    {
        let n = voce["n"].as_str().unwrap_or("").to_string();
        let k = (
            n.to_lowercase(),
            voce["marca"].as_str().unwrap_or("").to_lowercase(),
        );
        if voce["kcal"].is_null()
            || voce["ean"].as_str().unwrap_or("").is_empty()
            || n == "Prodotto senza nome"
            || visti.contains(&k)
        {
            continue;
        }
        visti.insert(k);
        trovati.push(voce);
    }
    trovati.truncate(12);
    Ok(trovati)
}

// ---------- photo of the dish ----------
fn tipo_immagine(dati: &[u8]) -> Option<&'static str> {
    if dati.starts_with(b"\xff\xd8\xff") {
        Some("image/jpeg")
    } else if dati.starts_with(b"\x89PNG\r\n\x1a\n") {
        Some("image/png")
    } else if dati.len() >= 12 && &dati[..4] == b"RIFF" && &dati[8..12] == b"WEBP" {
        Some("image/webp")
    } else {
        None
    }
}

/// (type, base64) of a photo from the phone, after checking it really is an image and not too large.
pub fn immagine_buona(immagine_b64: &Value) -> Esito<Immagine> {
    let dati = B64_STRETTO
        .decode(py::testo_o(immagine_b64))
        .map_err(|_| Problema::new(400, "La foto non e' arrivata intera: riprova."))?;
    let tipo = tipo_immagine(&dati);
    match tipo {
        Some(t) if 1000 < dati.len() && dati.len() <= MAX_FOTO => {
            Ok((t.to_string(), STANDARD.encode(&dati)))
        }
        _ => Err(Problema::new(
            400,
            "Serve una foto JPEG o PNG, non troppo grande.",
        )),
    }
}

/// The dictionary written in a text that should be JSON, even between ``` or with something around it.
pub fn json_da(testo: &str) -> Option<Map<String, Value>> {
    let testo = RE_RECINTO.replace_all(testo.trim(), "").into_owned();
    let dentro = match (testo.find('{'), testo.rfind('}')) {
        (Some(a), Some(b)) if b >= a => &testo[a..=b],
        _ => "",
    };
    for pezzo in [testo.as_str(), dentro] {
        if let Ok(Value::Object(m)) = serde_json::from_str::<Value>(pezzo) {
            return Some(m);
        }
    }
    None
}

/// Has the service look at the photo: {"piatto", "voci": [{n, g, kcal, p, c, f}], "ean", "sicurezza", "nota"}.
pub fn riconosci(motore: &Motore, immagine_b64: &Value, nota: &Value) -> Esito<Value> {
    let foto = immagine_buona(immagine_b64)?;
    let mut testo =
        "Cosa c'e' in questa foto? Stima alimenti, pesi e valori nutrizionali.".to_string();
    if py::vero(nota) {
        testo.push_str(" Nota di chi ha mangiato: ");
        testo.push_str(&py::taglia(&py::testo(nota), 200));
    }
    let esito = ai::chiedi_json(
        motore,
        SISTEMA_FOTO,
        &testo,
        &STRUMENTO_FOTO,
        Some(&foto),
        1500,
    )?;
    let Some(esito) = esito.filter(Value::is_object) else {
        return Err(Problema::new(
            502,
            "Non sono riuscito a leggere la foto. Riprova con piu' luce.",
        ));
    };
    let entro = |v: &Value, massimo: f64| {
        num(v)
            .map(|v| py::round(v.clamp(0.0, massimo), 1))
            .unwrap_or(0.0)
    };
    let mut lista = Vec::new();
    for x in get(&esito, "voci")
        .as_array()
        .map(|a| &a[..a.len().min(12)])
        .unwrap_or(&[])
    {
        if !x.is_object() || py::testo_o(get(x, "nome")).trim().is_empty() {
            continue;
        }
        lista.push(json!({
            "n": pulisci_v(get(x, "nome"), 60),
            "g": py::round_int(entro(get(x, "grammi"), 3000.0)),
            "kcal": py::round_int(entro(get(x, "kcal"), 4000.0)),
            "p": py::n_f(entro(get(x, "proteine"), 400.0)),
            "c": py::n_f(entro(get(x, "carboidrati"), 600.0)),
            "f": py::n_f(entro(get(x, "grassi"), 400.0)),
        }));
    }
    let ean = RE_NON_CIFRE
        .replace_all(&py::testo_o(get(&esito, "ean")), "")
        .into_owned();
    let piatto = pulisci_v(get(&esito, "piatto"), 60);
    let sicurezza = get(&esito, "sicurezza")
        .as_str()
        .filter(|s| ["alta", "media", "bassa"].contains(s))
        .unwrap_or("media");
    let nota = pulisci_v(get(&esito, "nota"), 200);
    Ok(json!({
        "piatto": if piatto.is_empty() { "Pasto".to_string() } else { piatto },
        "voci": lista,
        "ean": if [8, 12, 13].contains(&ean.chars().count()) { Value::String(ean) } else { Value::Null },
        "sicurezza": sicurezza,
        "nota": if nota.is_empty() { Value::Null } else { Value::String(nota) },
    }))
}

#[cfg(test)]
mod test {
    use super::*;

    #[test]
    fn pulizia_e_pezzi() {
        assert_eq!(pulisci("  PASTA  DI  SEMOLA, ", 80), "Pasta Di Semola");
        assert_eq!(pulisci("Nutella", 80), "Nutella");
        let (pz, nome, conf) = pezzi(&json!({"quantity": "4 x 20 g"}));
        assert_eq!(
            (pz, nome, conf),
            (json!(20.0), json!(["pezzo", "pezzi"]), json!(80))
        );
        let (_, _, conf) = pezzi(&json!({"quantity": "1,5 kg"}));
        assert_eq!(conf, json!(1500));
    }

    #[test]
    fn json_nel_testo() {
        assert!(json_da("```json\n{\"a\": 1}\n```").is_some());
        assert!(json_da("ecco: {\"a\": 1} fine").is_some());
        assert!(json_da("niente").is_none());
        assert!(json_da("[1]").is_none());
    }

    #[test]
    fn foto() {
        let jpeg = STANDARD.encode([b"\xff\xd8\xff\xe0".as_slice(), &[b'0'; 3000]].concat());
        assert!(immagine_buona(&json!(jpeg)).is_ok());
        assert_eq!(
            immagine_buona(&json!("questo non e' base64!"))
                .unwrap_err()
                .codice,
            400
        );
        assert!(
            immagine_buona(&json!(STANDARD.encode(b"ciao".repeat(500))))
                .unwrap_err()
                .testo
                .starts_with("Serve")
        );
    }
}
