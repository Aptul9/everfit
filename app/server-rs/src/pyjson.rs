//! JSON written the way Python's `json.dumps` writes it: same separators, same float digits, same escaping.
//! Responses and stored rows must be byte-identical to the Python server so the two can share a database.

use serde_json::Value;
use std::fmt::Write;

/// `json.dumps(v, ensure_ascii=False, separators=(",", ":"))`
pub fn compatto(v: &Value) -> String {
    dumps(v, false, true)
}

/// `json.dumps(v, ensure_ascii=False)`
pub fn largo(v: &Value) -> String {
    dumps(v, false, false)
}

/// `json.dumps(v)`
pub fn ascii(v: &Value) -> String {
    dumps(v, true, false)
}

/// `json.dumps(v, ensure_ascii=True, separators=(",", ":"))`
pub fn ascii_compatto(v: &Value) -> String {
    dumps(v, true, true)
}

pub fn dumps(v: &Value, ensure_ascii: bool, compact: bool) -> String {
    let mut s = String::new();
    scrivi(&mut s, v, ensure_ascii, compact);
    s
}

fn scrivi(s: &mut String, v: &Value, ea: bool, compact: bool) {
    match v {
        Value::Null => s.push_str("null"),
        Value::Bool(b) => s.push_str(if *b { "true" } else { "false" }),
        Value::Number(n) => {
            if let Some(i) = n.as_i64() {
                let _ = write!(s, "{i}");
            } else if let Some(u) = n.as_u64() {
                let _ = write!(s, "{u}");
            } else {
                s.push_str(&float_repr(n.as_f64().unwrap_or(0.0)));
            }
        }
        Value::String(t) => stringa(s, t, ea),
        Value::Array(a) => {
            s.push('[');
            for (i, x) in a.iter().enumerate() {
                if i > 0 {
                    s.push_str(if compact { "," } else { ", " });
                }
                scrivi(s, x, ea, compact);
            }
            s.push(']');
        }
        Value::Object(m) => {
            s.push('{');
            for (i, (k, x)) in m.iter().enumerate() {
                if i > 0 {
                    s.push_str(if compact { "," } else { ", " });
                }
                stringa(s, k, ea);
                s.push_str(if compact { ":" } else { ": " });
                scrivi(s, x, ea, compact);
            }
            s.push('}');
        }
    }
}

fn stringa(s: &mut String, t: &str, ea: bool) {
    s.push('"');
    for c in t.chars() {
        match c {
            '"' => s.push_str("\\\""),
            '\\' => s.push_str("\\\\"),
            '\n' => s.push_str("\\n"),
            '\r' => s.push_str("\\r"),
            '\t' => s.push_str("\\t"),
            '\u{8}' => s.push_str("\\b"),
            '\u{c}' => s.push_str("\\f"),
            c if (c as u32) < 0x20 => {
                let _ = write!(s, "\\u{:04x}", c as u32);
            }
            c if ea && (c as u32) > 0x7f => {
                let mut buf = [0u16; 2];
                for u in c.encode_utf16(&mut buf) {
                    let _ = write!(s, "\\u{:04x}", u);
                }
            }
            c => s.push(c),
        }
    }
    s.push('"');
}

/// `repr(float)` in Python: shortest round-trip digits, fixed notation for 1e-4 <= |x| < 1e16, otherwise `1.5e+16`.
pub fn float_repr(f: f64) -> String {
    if f.is_nan() {
        return "NaN".into();
    }
    if f.is_infinite() {
        return if f > 0.0 {
            "Infinity".into()
        } else {
            "-Infinity".into()
        };
    }
    if f == 0.0 {
        return if f.is_sign_negative() {
            "-0.0".into()
        } else {
            "0.0".into()
        };
    }
    let e = format!("{:e}", f);
    let (mant, exp) = e.split_once('e').unwrap_or((e.as_str(), "0"));
    let exp: i32 = exp.parse().unwrap_or(0);
    let (neg, mant) = match mant.strip_prefix('-') {
        Some(m) => (true, m),
        None => (false, mant),
    };
    let digits: String = mant.chars().filter(|c| *c != '.').collect();
    let mut out = String::new();
    if neg {
        out.push('-');
    }
    if (-4..16).contains(&exp) {
        if exp < 0 {
            out.push_str("0.");
            for _ in 0..(-exp - 1) {
                out.push('0');
            }
            out.push_str(&digits);
        } else {
            let intera = (exp + 1) as usize;
            if digits.len() <= intera {
                out.push_str(&digits);
                for _ in 0..(intera - digits.len()) {
                    out.push('0');
                }
                out.push_str(".0");
            } else {
                out.push_str(&digits[..intera]);
                out.push('.');
                out.push_str(&digits[intera..]);
            }
        }
    } else {
        out.push_str(&digits[..1]);
        if digits.len() > 1 {
            out.push('.');
            out.push_str(&digits[1..]);
        }
        let _ = write!(out, "e{}{:02}", if exp < 0 { '-' } else { '+' }, exp.abs());
    }
    out
}

/// A float that Python would print as an int when it has no fractional part is still a float: keep it one.
pub fn num_f(f: f64) -> Value {
    serde_json::Number::from_f64(f)
        .map(Value::Number)
        .unwrap_or(Value::Null)
}

#[cfg(test)]
mod test {
    use super::*;
    use serde_json::json;

    #[test]
    fn float_come_python() {
        for (f, atteso) in [
            (70.0, "70.0"),
            (55.5, "55.5"),
            (0.1, "0.1"),
            (1e16, "1e+16"),
            (1.5e16, "1.5e+16"),
            (1e-5, "1e-05"),
            (0.0001, "0.0001"),
            (123456789.125, "123456789.125"),
            (1731000000000.0, "1731000000000.0"),
            (-2.5, "-2.5"),
            (1e22, "1e+22"),
            (9999999999999998.0, "9999999999999998.0"),
        ] {
            assert_eq!(float_repr(f), atteso, "{f}");
        }
    }

    #[test]
    fn separatori_ed_escape() {
        let v = json!({"a": [1, 2.0, "è\n"], "b": null});
        assert_eq!(compatto(&v), "{\"a\":[1,2.0,\"è\\n\"],\"b\":null}");
        assert_eq!(largo(&v), "{\"a\": [1, 2.0, \"è\\n\"], \"b\": null}");
        assert_eq!(
            ascii(&json!(["è", "😀"])),
            "[\"\\u00e8\", \"\\ud83d\\ude00\"]"
        );
    }
}
