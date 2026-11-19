//! Small helpers that reproduce Python semantics the server relies on: truthiness, `str()`, `float()`, the clock.

use regex::Regex;
use serde_json::Value;
use std::time::{SystemTime, UNIX_EPOCH};

pub static NULLA: Value = Value::Null;

/// A regex from a constant pattern. Every pattern passed here is compiled by the test suite, so this cannot fail at
/// run time; it is the one place allowed to `expect`.
#[allow(clippy::expect_used)]
pub fn re(pattern: &str) -> Regex {
    Regex::new(pattern).expect("constant regex")
}

/// Header bytes as Python's http.server decodes them (ISO-8859-1).
pub fn latin1(b: &[u8]) -> String {
    b.iter().map(|&c| c as char).collect()
}

/// `urllib.parse.unquote(s)` (UTF-8, errors="replace")
pub fn unquote(s: &str) -> String {
    String::from_utf8_lossy(&percent_decode(s.as_bytes(), false)).into_owned()
}

fn percent_decode(b: &[u8], piu: bool) -> Vec<u8> {
    let mut out = Vec::with_capacity(b.len());
    let mut i = 0;
    while i < b.len() {
        match b[i] {
            b'%' if i + 2 < b.len()
                && b[i + 1].is_ascii_hexdigit()
                && b[i + 2].is_ascii_hexdigit() =>
            {
                let alto = (b[i + 1] as char).to_digit(16).unwrap_or(0);
                let basso = (b[i + 2] as char).to_digit(16).unwrap_or(0);
                out.push((alto * 16 + basso) as u8);
                i += 3;
                continue;
            }
            b'+' if piu => out.push(b' '),
            c => out.push(c),
        }
        i += 1;
    }
    out
}

/// `parse_qs(query)` keeping only the first value of each name, as every caller does with `[0]`. Blank values are
/// dropped like Python does (keep_blank_values=False).
pub fn parse_qs(query: &str) -> std::collections::HashMap<String, String> {
    let mut m = std::collections::HashMap::new();
    for pezzo in query.split('&') {
        let Some((k, v)) = pezzo.split_once('=') else {
            continue;
        };
        if v.is_empty() {
            continue;
        }
        let k = String::from_utf8_lossy(&percent_decode(k.as_bytes(), true)).into_owned();
        let v = String::from_utf8_lossy(&percent_decode(v.as_bytes(), true)).into_owned();
        m.entry(k).or_insert(v);
    }
    m
}

/// `urllib.parse.quote_plus(s)`, the encoding `urlencode` uses.
pub fn quote_plus(s: &str) -> String {
    let mut out = String::new();
    for b in s.bytes() {
        match b {
            b' ' => out.push('+'),
            b if b.is_ascii_alphanumeric() || matches!(b, b'_' | b'.' | b'-' | b'~') => {
                out.push(b as char)
            }
            b => out.push_str(&format!("%{b:02X}")),
        }
    }
    out
}

/// `time.time()`
pub fn ora() -> f64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|d| d.as_secs_f64())
        .unwrap_or(0.0)
}

/// `d.get(k)` on something that may not be a dict: None (Null) when missing.
pub fn get<'a>(v: &'a Value, k: &str) -> &'a Value {
    v.get(k).unwrap_or(&NULLA)
}

/// `bool(x)`
pub fn vero(v: &Value) -> bool {
    match v {
        Value::Null => false,
        Value::Bool(b) => *b,
        Value::Number(n) => n.as_f64().map(|f| f != 0.0).unwrap_or(true),
        Value::String(s) => !s.is_empty(),
        Value::Array(a) => !a.is_empty(),
        Value::Object(o) => !o.is_empty(),
    }
}

/// `x or alternativa`
pub fn o<'a>(v: &'a Value, alt: &'a Value) -> &'a Value {
    if vero(v) { v } else { alt }
}

/// `str(x)`
pub fn testo(v: &Value) -> String {
    match v {
        Value::String(s) => s.clone(),
        other => repr(other),
    }
}

/// `str(x or "")`
pub fn testo_o(v: &Value) -> String {
    if vero(v) { testo(v) } else { String::new() }
}

/// `repr(x)` for JSON-shaped values.
pub fn repr(v: &Value) -> String {
    match v {
        Value::Null => "None".into(),
        Value::Bool(true) => "True".into(),
        Value::Bool(false) => "False".into(),
        Value::Number(n) => {
            if n.is_f64() {
                crate::pyjson::float_repr(n.as_f64().unwrap_or(0.0))
            } else {
                n.to_string()
            }
        }
        Value::String(s) => {
            let quote = if s.contains('\'') && !s.contains('"') {
                '"'
            } else {
                '\''
            };
            let mut out = String::from(quote);
            for c in s.chars() {
                match c {
                    '\\' => out.push_str("\\\\"),
                    '\n' => out.push_str("\\n"),
                    '\r' => out.push_str("\\r"),
                    '\t' => out.push_str("\\t"),
                    c if c == quote => {
                        out.push('\\');
                        out.push(c);
                    }
                    c if (c as u32) < 0x20 || c as u32 == 0x7f => {
                        out.push_str(&format!("\\x{:02x}", c as u32))
                    }
                    c => out.push(c),
                }
            }
            out.push(quote);
            out
        }
        Value::Array(a) => format!("[{}]", a.iter().map(repr).collect::<Vec<_>>().join(", ")),
        Value::Object(m) => format!(
            "{{{}}}",
            m.iter()
                .map(|(k, x)| format!("{}: {}", repr(&Value::String(k.clone())), repr(x)))
                .collect::<Vec<_>>()
                .join(", ")
        ),
    }
}

/// `float(x)` for JSON values: numbers, numeric strings (Python syntax), booleans. None when Python would raise.
pub fn float(v: &Value) -> Option<f64> {
    match v {
        Value::Number(n) => n.as_f64(),
        Value::Bool(b) => Some(if *b { 1.0 } else { 0.0 }),
        Value::String(s) => float_str(s),
        _ => None,
    }
}

/// `float(s)` for a Python string.
pub fn float_str(s: &str) -> Option<f64> {
    let t = s.trim();
    if t.is_empty() {
        return None;
    }
    let pulito: String = if t.contains('_') {
        // Python accepts single underscores between digits
        let b: Vec<char> = t.chars().collect();
        for (i, c) in b.iter().enumerate() {
            if *c == '_'
                && !(i > 0
                    && i + 1 < b.len()
                    && b[i - 1].is_ascii_digit()
                    && b[i + 1].is_ascii_digit())
            {
                return None;
            }
        }
        t.replace('_', "")
    } else {
        t.to_string()
    };
    let l = pulito.to_ascii_lowercase();
    let senza_segno = l.trim_start_matches(['+', '-']);
    match senza_segno {
        "inf" | "infinity" => {
            return Some(if l.starts_with('-') {
                f64::NEG_INFINITY
            } else {
                f64::INFINITY
            });
        }
        "nan" => return Some(f64::NAN),
        _ => {}
    }
    if !pulito
        .chars()
        .all(|c| c.is_ascii_digit() || matches!(c, '+' | '-' | '.' | 'e' | 'E'))
    {
        return None;
    }
    pulito.parse::<f64>().ok()
}

/// `str.isprintable()` for one character (approximation of Python's Unicode table: no control, format,
/// separator or unassigned-looking characters except the plain space).
pub fn stampabile(c: char) -> bool {
    if c == ' ' {
        return true;
    }
    if c.is_control() || c.is_whitespace() {
        return false;
    }
    let u = c as u32;
    // Cf (format) characters commonly met, private use and surrogates are not printable in Python
    !matches!(u, 0xAD | 0x600..=0x605 | 0x61C | 0x6DD | 0x70F | 0x180E | 0x200B..=0x200F | 0x202A..=0x202E
        | 0x2060..=0x2064 | 0x2066..=0x206F | 0xFEFF | 0xFFF9..=0xFFFB | 0xE000..=0xF8FF
        | 0xF0000..=0x10FFFF | 0xE0001 | 0xE0020..=0xE007F)
}

/// Python's `str.isalnum()` for one character (close enough: letters and numbers).
pub fn alnum(c: char) -> bool {
    c.is_alphanumeric()
}

/// `str.title()`: a cased character after a cased one goes lowercase, otherwise uppercase.
pub fn title(s: &str) -> String {
    let mut out = String::with_capacity(s.len());
    let mut prima_cased = false;
    for c in s.chars() {
        if prima_cased {
            out.extend(c.to_lowercase());
        } else {
            out.extend(c.to_uppercase());
        }
        prima_cased = c.is_lowercase() || c.is_uppercase();
    }
    out
}

/// `s[:n]` counting characters, as Python does.
pub fn taglia(s: &str, n: usize) -> String {
    match s.char_indices().nth(n) {
        Some((i, _)) => s[..i].to_string(),
        None => s.to_string(),
    }
}

/// `" ".join(s.split())`
pub fn spazi(s: &str) -> String {
    s.split_whitespace().collect::<Vec<_>>().join(" ")
}

/// Python's `round(x, n)` (round half to even on the binary value, like CPython).
pub fn round(x: f64, n: i32) -> f64 {
    if !x.is_finite() {
        return x;
    }
    // CPython formats with enough digits and rounds correctly; formatting with {:.n$} does round-half-even on the
    // exact binary value, which is what CPython's round() also does.
    let s = format!("{:.*}", n.max(0) as usize, x);
    s.parse().unwrap_or(x)
}

/// `round(x)` with no digits: an int, half to even.
pub fn round_int(x: f64) -> i64 {
    let r = x.round();
    if (x - x.trunc()).abs() == 0.5 {
        let t = x.trunc();
        if (t as i64) % 2 == 0 {
            t as i64
        } else {
            r as i64
        }
    } else {
        r as i64
    }
}

/// `int(float)` truncation
pub fn int(x: f64) -> i64 {
    x.trunc() as i64
}

pub fn n_f(f: f64) -> Value {
    crate::pyjson::num_f(f)
}

#[cfg(test)]
mod test {
    use super::*;

    #[test]
    fn arrotonda_come_python() {
        assert_eq!(round(2.675, 2), 2.67);
        assert_eq!(round(0.125, 2), 0.12);
        assert_eq!(round(78.5, 1), 78.5);
        assert_eq!(round_int(2.5), 2);
        assert_eq!(round_int(3.5), 4);
        assert_eq!(round_int(-2.5), -2);
        assert_eq!(round_int(4.4), 4);
    }

    #[test]
    fn float_come_python() {
        assert_eq!(float_str(" 8.5 "), Some(8.5));
        assert_eq!(float_str("1_000"), Some(1000.0));
        assert_eq!(float_str("abc"), None);
        assert_eq!(float_str(""), None);
        assert!(float_str("nan").unwrap().is_nan());
    }
}
