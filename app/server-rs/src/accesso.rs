//! Who gets in: accounts, passwords and cookies (accesso.py).

use crate::conf::conf;
use base64::Engine;
use hmac::{Hmac, KeyInit, Mac};
use rand::Rng;
use regex::Regex;
use sha2::{Digest, Sha256};
use std::collections::VecDeque;
use std::sync::{LazyLock, Mutex};
use std::time::Duration;

pub const CAPO: i64 = 1;
pub const ITERAZIONI: u32 = 240_000;
pub const DURATA: i64 = 400 * 86400;
const MAX_SBAGLI: usize = 30;
const FINESTRA: f64 = 3600.0;

const SCHERMI: [(u32, u32, u32); 13] = [
    (320, 568, 2),
    (375, 667, 2),
    (414, 736, 3),
    (375, 812, 3),
    (414, 896, 2),
    (414, 896, 3),
    (390, 844, 3),
    (428, 926, 3),
    (393, 852, 3),
    (430, 932, 3),
    (402, 874, 3),
    (440, 956, 3),
    (420, 912, 3),
];

static RE_UTENTE: LazyLock<Regex> = LazyLock::new(|| crate::py::re(r"^[a-z0-9][a-z0-9._-]{2,23}$"));
static SBAGLI: Mutex<VecDeque<f64>> = Mutex::new(VecDeque::new());

/// Bytes from the operating system's CSPRNG (through the thread-local generator of `rand`), as `secrets` does.
pub fn casuali<const N: usize>() -> [u8; N] {
    let mut b = [0u8; N];
    rand::rng().fill_bytes(&mut b);
    b
}

pub fn impronta(valore: &str) -> String {
    hex::encode(Sha256::digest(valore.as_bytes()))
}

pub fn firma(segreto: &str, testo: &str) -> String {
    // HMAC takes keys of any length: the error branch cannot happen
    match <Hmac<Sha256> as KeyInit>::new_from_slice(segreto.as_bytes()) {
        Ok(mut m) => {
            m.update(testo.as_bytes());
            hex::encode(m.finalize().into_bytes())
        }
        Err(_) => String::new(),
    }
}

pub fn uguali(a: &str, b: &str) -> bool {
    use subtle::ConstantTimeEq;
    a.len() == b.len() && bool::from(a.as_bytes().ct_eq(b.as_bytes()))
}

pub fn pulisci_codice(codice: &str) -> String {
    codice
        .chars()
        .filter(|c| crate::py::alnum(*c))
        .take(40)
        .collect()
}

/// The username in lowercase, or None if it is not made of letters, digits, dots and dashes (3-24 characters).
pub fn nome_utente(testo: &str) -> Option<String> {
    let u = testo.trim().to_lowercase();
    if RE_UTENTE.is_match(&u) {
        Some(u)
    } else {
        None
    }
}

fn pbkdf2_hex(password: &str, sale: &[u8], giri: u32) -> String {
    let mut out = [0u8; 32];
    pbkdf2::pbkdf2_hmac::<Sha256>(password.as_bytes(), sale, giri, &mut out);
    hex::encode(out)
}

pub fn impasta(password: &str) -> String {
    let sale = casuali::<16>();
    format!(
        "pbkdf2${}${}${}",
        ITERAZIONI,
        hex::encode(sale),
        pbkdf2_hex(password, &sale, ITERAZIONI)
    )
}

/// Same format and same check as Python: `pbkdf2$<iterations>$<salt hex>$<hash hex>`.
pub fn combacia(password: &str, impasto: &str) -> bool {
    let parti: Vec<&str> = impasto.split('$').collect();
    if parti.len() != 4 {
        return false;
    }
    let (giri, sale, atteso) = (parti[1], parti[2], parti[3]);
    let giri: u32 = match giri.trim().parse() {
        Ok(g) if g > 0 => g,
        _ => return false,
    };
    let sale: String = sale.chars().filter(|c| !c.is_whitespace()).collect();
    let sale = match hex::decode(&sale) {
        Ok(s) => s,
        Err(_) => return false,
    };
    uguali(&pbkdf2_hex(password, &sale, giri), atteso)
}

/// any hash: when the username does not exist the work is done anyway, so the answer takes the same time
pub static FINTO: LazyLock<String> = LazyLock::new(|| impasta(&hex::encode(casuali::<8>())));

/// `secrets.token_urlsafe(32)`
pub fn nuovo_gettone() -> String {
    base64::engine::general_purpose::URL_SAFE_NO_PAD.encode(casuali::<32>())
}

pub fn troppi_sbagli() -> bool {
    let ora = crate::py::ora();
    let mut s = SBAGLI.lock().unwrap_or_else(|e| e.into_inner());
    while s.front().is_some_and(|t| ora - t > FINESTRA) {
        s.pop_front();
    }
    s.len() >= MAX_SBAGLI
}

pub fn segna_sbaglio() {
    SBAGLI
        .lock()
        .unwrap_or_else(|e| e.into_inner())
        .push_back(crate::py::ora());
    std::thread::sleep(Duration::from_secs(1));
}

// ---------- cookie ----------
pub fn leggi_cookie(intestazione: Option<&str>, nome: &str) -> String {
    for pezzo in intestazione.unwrap_or("").split(';') {
        let pezzo = pezzo.trim();
        let (k, v) = pezzo.split_once('=').unwrap_or((pezzo, ""));
        if k == nome {
            return v.to_string();
        }
    }
    String::new()
}

/// `urllib.parse.quote(s, safe="")`
pub fn quote(s: &str) -> String {
    let mut out = String::new();
    for b in s.bytes() {
        if b.is_ascii_alphanumeric() || matches!(b, b'_' | b'.' | b'-' | b'~') {
            out.push(b as char);
        } else {
            out.push_str(&format!("%{:02X}", b));
        }
    }
    out
}

pub fn biscotti(gettone: &str, nome: &str) -> Vec<String> {
    vec![
        format!(
            "fitk={}; Path=/; Max-Age={}; Secure; HttpOnly; SameSite=Lax",
            gettone, DURATA
        ),
        format!(
            "fitn={}; Path=/; Max-Age={}; Secure; SameSite=Lax",
            quote(nome),
            DURATA
        ),
    ]
}

pub fn biscotti_spenti() -> Vec<String> {
    vec![
        "fitk=; Path=/; Max-Age=0; Secure; HttpOnly; SameSite=Lax".into(),
        "fitn=; Path=/; Max-Age=0; Secure; SameSite=Lax".into(),
    ]
}

// ---------- login page ----------
const PAGINA: &str = include_str!("../testi/pagina.html");

fn avvio_iphone(prefisso: &str) -> String {
    SCHERMI
        .iter()
        .map(|(w, h, k)| {
            format!(
                "<link rel=\"apple-touch-startup-image\" href=\"{}icons/splash-{}x{}.png\" media=\"(device-width: {}px) and (device-height: {}px) and (-webkit-device-pixel-ratio: {}) and (orientation: portrait)\">",
                prefisso, w * k, h * k, w, h, k
            )
        })
        .collect::<Vec<_>>()
        .join("\n")
}

/// `html.escape(s)`
pub fn escape(s: &str) -> String {
    let mut out = String::with_capacity(s.len());
    for c in s.chars() {
        match c {
            '&' => out.push_str("&amp;"),
            '<' => out.push_str("&lt;"),
            '>' => out.push_str("&gt;"),
            '"' => out.push_str("&quot;"),
            '\'' => out.push_str("&#x27;"),
            c => out.push(c),
        }
    }
    out
}

const ALTRE: &str = "\n  <a href=\"/oidc/login__APKQ__\" style=\"color:#a6abb8;font-size:14px;text-decoration:underline\">altre opzioni di accesso</a>";

/// The login page. Without the central account service it is byte for byte the Python one; with it, a small link to
/// the normal authorization page. `apk` is the Android shell's `?apk=<versionCode>`, kept through the login.
pub fn pagina_con(messaggio: &str, apk: Option<&str>) -> Vec<u8> {
    let altre = if crate::oidc::attivo() {
        ALTRE.replace(
            "__APKQ__",
            &apk.map(|a| format!("?apk={a}")).unwrap_or_default(),
        )
    } else {
        String::new()
    };
    PAGINA
        .replace("__ALTRE__", &altre)
        .replace(
            "__APK__",
            &apk.map(|a| format!("?apk={a}")).unwrap_or_default(),
        )
        .replace("__AVVIO__", &avvio_iphone("/"))
        .replace("__MESSAGGIO__", &escape(messaggio))
        .replace("__FUOCO__", "autofocus")
        .into_bytes()
}

pub fn acceso() -> bool {
    conf().acceso
}

#[cfg(test)]
mod test {
    use super::*;

    #[test]
    fn impasto_compatibile() {
        // made by Python: accesso.impasta("prova-anna.2026", "00112233445566778899aabbccddeeff")
        let h = impasta("segreta123");
        assert!(combacia("segreta123", &h));
        assert!(!combacia("altra", &h));
        assert!(!combacia("x", "rotto"));
        assert_eq!(quote("Anna b/è"), "Anna%20b%2F%C3%A8");
        assert_eq!(nome_utente(" Anna "), Some("anna".into()));
        assert_eq!(nome_utente("an na!"), None);
        assert_eq!(nuovo_gettone().len(), 43);
    }
}
