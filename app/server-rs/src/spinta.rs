//! Phone notifications (Web Push, spinta.py). The POST to the push service carries no payload, so nothing needs
//! encrypting: the phone then fetches the text from /api/notifiche/prossime with its cookie. The VAPID signature
//! (RFC 8292, ES256) comes from the p256 crate instead of the hand-written curve arithmetic of the Python server.

use crate::conf::conf;
use crate::log;
use base64::Engine;
use base64::engine::general_purpose::URL_SAFE_NO_PAD;
use p256::ecdsa::signature::Signer;
use p256::ecdsa::{Signature, SigningKey};
use p256::elliptic_curve::Generate;
use serde_json::json;
use std::collections::HashMap;
use std::io::Write;
use std::path::{Path, PathBuf};
use std::sync::{LazyLock, Mutex};
use std::time::Duration;

/// The only services the server sends to: the address comes from the phone and must not become a request anywhere.
const SERVIZI: [&str; 4] = [
    ".push.apple.com",
    "fcm.googleapis.com",
    ".push.services.mozilla.com",
    ".notify.windows.com",
];

static CHIAVI: LazyLock<Mutex<HashMap<PathBuf, (SigningKey, String)>>> =
    LazyLock::new(|| Mutex::new(HashMap::new()));

fn b64(b: &[u8]) -> String {
    URL_SAFE_NO_PAD.encode(b)
}

/// The public key (65 bytes: 0x04, x, y) of a private key.
pub fn pubblica(k: &SigningKey) -> Vec<u8> {
    k.verifying_key().to_sec1_point(false).as_bytes().to_vec()
}

fn da_hex(testo: &str) -> Option<SigningKey> {
    let t = testo.trim();
    if t.is_empty() || t.len() > 64 || !t.chars().all(|c| c.is_ascii_hexdigit()) {
        return None;
    }
    let b = hex::decode(format!("{t:0>64}")).ok()?;
    SigningKey::from_slice(&b).ok()
}

/// (private, public in base64 for the phone). The private one lives in <data>/vapid.key, made the first time.
pub fn chiave(cartella: &Path) -> (SigningKey, String) {
    let mut c = CHIAVI.lock().unwrap_or_else(|e| e.into_inner());
    if let Some(k) = c.get(cartella) {
        return k.clone();
    }
    let percorso = cartella.join("vapid.key");
    let d = match std::fs::read_to_string(&percorso)
        .ok()
        .and_then(|t| da_hex(&t))
    {
        Some(d) => d,
        None => {
            let d = SigningKey::generate();
            let mut o = std::fs::OpenOptions::new();
            o.write(true).create(true).truncate(true);
            #[cfg(unix)]
            {
                use std::os::unix::fs::OpenOptionsExt;
                o.mode(0o600);
            }
            if let Ok(mut f) = o.open(&percorso) {
                let _ = writeln!(f, "{}", hex::encode(d.to_bytes()));
            }
            d
        }
    };
    let pub_b64 = b64(&pubblica(&d));
    c.insert(cartella.to_path_buf(), (d.clone(), pub_b64.clone()));
    (d, pub_b64)
}

/// The ES256 signature of `messaggio` (64 bytes: r and s); None only if the signer itself fails.
pub fn firma(d: &SigningKey, messaggio: &[u8]) -> Option<Vec<u8>> {
    let s: Signature = d.try_sign(messaggio).ok()?;
    Some(s.to_bytes().to_vec())
}

pub fn indirizzo_buono(indirizzo: &str) -> bool {
    let prova = &conf().spinta_prova;
    if !prova.is_empty() && indirizzo.starts_with(prova.as_str()) {
        return true;
    }
    let Ok(u) = url::Url::parse(indirizzo) else {
        return false;
    };
    let host = u.host_str().unwrap_or("").to_lowercase();
    u.scheme() == "https"
        && !host.is_empty()
        && SERVIZI.iter().any(|s| host == *s || host.ends_with(s))
        && indirizzo.len() < 1000
}

/// Wakes a phone. Returns the service's status (201 = taken; 404 and 410 = subscription gone; 0 = not reached).
pub fn spingi(cartella: &Path, indirizzo: &str) -> i64 {
    spingi_con(cartella, indirizzo, true, 3600)
}

pub fn spingi_con(cartella: &Path, indirizzo: &str, urgente: bool, vita: i64) -> i64 {
    if !indirizzo_buono(indirizzo) {
        return 0;
    }
    let (d, pub_b64) = chiave(cartella);
    let Ok(u) = url::Url::parse(indirizzo) else {
        return 0;
    };
    let host = u.host_str().unwrap_or("").to_string();
    let netloc = match u.port() {
        Some(p) => format!("{host}:{p}"),
        None => host.clone(),
    };
    let testa = b64(br#"{"typ":"JWT","alg":"ES256"}"#);
    let exp = crate::py::int(crate::py::ora()) + 12 * 3600;
    let corpo = b64(crate::pyjson::ascii_compatto(&json!({"aud": format!("{}://{}", u.scheme(), netloc), "exp": exp, "sub": conf().chi_siamo})).as_bytes());
    let firmato = format!("{testa}.{corpo}");
    let Some(f) = firma(&d, firmato.as_bytes()) else {
        return 0;
    };
    let gettone = format!("{firmato}.{}", b64(&f));
    let r = crate::ai_http::client()
        .post(indirizzo)
        .timeout(Duration::from_secs(15))
        .header("TTL", vita.to_string())
        .header("Urgency", if urgente { "high" } else { "normal" })
        .header("Content-Length", "0")
        .header("Authorization", format!("vapid t={gettone}, k={pub_b64}"))
        .body(Vec::<u8>::new())
        .send();
    match r {
        Ok(r)
            if r.status().is_success()
                || r.status().is_redirection()
                || r.status().is_informational() =>
        {
            r.status().as_u16() as i64
        }
        Ok(r) => {
            let codice = r.status().as_u16();
            let perche: String = r.text().unwrap_or_default().chars().take(200).collect();
            log!("notifiche: {} ha risposto {} {}", host, codice, perche);
            codice as i64
        }
        Err(e) => {
            log!(
                "notifiche: {} non raggiunto ({})",
                host,
                crate::ai_http::tipo_errore(&e)
            );
            0
        }
    }
}

#[cfg(test)]
mod test {
    //! prova_spinta.py: a key made here, a signature made here, OpenSSL verifying it.
    use super::*;

    #[test]
    fn punti_noti_della_curva() {
        let uno = da_hex("1").unwrap();
        assert_eq!(
            hex::encode(&pubblica(&uno)[1..33]),
            "6b17d1f2e12c4247f8bce6e563a440f277037d812deb33a0f4a13945d898c296"
        );
        let due = da_hex("2").unwrap();
        assert_eq!(
            hex::encode(&pubblica(&due)[1..33]),
            "7cf27b188d034f7e8a52380304b51ac3c08969e277f21b35a60b48fc47669978"
        );
    }

    #[test]
    fn openssl_verifica_la_firma() {
        let d = da_hex("1F2E3D4C5B6A79880123456789ABCDEFFEDCBA98765432100F1E2D3C4B5A6978").unwrap();
        let pubb = pubblica(&d);
        let messaggio = b"eyJ0eXAiOiJKV1QiLCJhbGciOiJFUzI1NiJ9.eyJhdWQiOiJodHRwczovL3dlYi5wdXNoLmFwcGxlLmNvbSJ9";
        let f = firma(&d, messaggio).unwrap();
        assert_eq!(f.len(), 64);
        let sig = Signature::from_slice(&f).unwrap();
        let der = sig.to_der();
        let mut spki = hex::decode("3059301306072a8648ce3d020106082a8648ce3d030107034200").unwrap();
        spki.extend_from_slice(&pubb);
        let dir = tempfile::tempdir().unwrap();
        std::fs::write(dir.path().join("pub.der"), &spki).unwrap();
        std::fs::write(dir.path().join("firma.der"), der.as_bytes()).unwrap();
        std::fs::write(dir.path().join("messaggio"), messaggio).unwrap();
        let p = |n: &str| dir.path().join(n).to_string_lossy().into_owned();
        let out = std::process::Command::new("openssl")
            .args([
                "dgst",
                "-sha256",
                "-verify",
                &p("pub.der"),
                "-keyform",
                "DER",
                "-signature",
                &p("firma.der"),
                &p("messaggio"),
            ])
            .output();
        match out {
            Ok(o) => assert!(
                String::from_utf8_lossy(&o.stdout).contains("Verified OK"),
                "{:?}",
                o
            ),
            Err(_) => eprintln!("openssl assente: verifica saltata"),
        }
    }

    #[test]
    fn chiave_su_file_compatibile() {
        let dir = tempfile::tempdir().unwrap();
        // the format Python writes: "%064x\n"
        std::fs::write(
            dir.path().join("vapid.key"),
            "1f2e3d4c5b6a79880123456789abcdeffedcba98765432100f1e2d3c4b5a6978\n",
        )
        .unwrap();
        let (_, p) = chiave(dir.path());
        assert_eq!(p.len(), 87);
        let altra = tempfile::tempdir().unwrap();
        let (d, _) = chiave(altra.path());
        let scritto = std::fs::read_to_string(altra.path().join("vapid.key")).unwrap();
        assert_eq!(scritto, format!("{}\n", hex::encode(d.to_bytes())));
    }
}
