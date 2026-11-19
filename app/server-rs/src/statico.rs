//! The app's files (server.py `_statico`, `guscio`): same paths, ETags, cache headers and the service worker with
//! the app version and file list written in at delivery.

use crate::py;
use sha1::{Digest, Sha1};
use std::path::{Path, PathBuf};
use std::sync::{LazyLock, Mutex};
use std::time::UNIX_EPOCH;

type Voce = (String, i64, u64);

struct Guscio {
    chiave: Option<Vec<Voce>>,
    versione: String,
    file: Vec<String>,
}

static GUSCIO: LazyLock<Mutex<Guscio>> = LazyLock::new(|| {
    Mutex::new(Guscio {
        chiave: None,
        versione: String::new(),
        file: vec![],
    })
});

fn mtime(m: &std::fs::Metadata) -> i64 {
    m.modified()
        .ok()
        .and_then(|t| t.duration_since(UNIX_EPOCH).ok())
        .map(|d| d.as_secs() as i64)
        .unwrap_or(0)
}

fn cammina(base: &Path, dir: &Path, voci: &mut Vec<Voce>) {
    let Ok(lista) = std::fs::read_dir(dir) else {
        return;
    };
    for e in lista.flatten() {
        let Ok(tipo) = e.file_type() else { continue };
        let pieno = e.path();
        if tipo.is_dir() {
            cammina(base, &pieno, voci); // os.walk does not follow symlinked directories, neither does this
            continue;
        }
        let Ok(rel) = pieno.strip_prefix(base) else {
            continue;
        };
        let rel = rel.to_string_lossy().replace('\\', "/");
        if rel.starts_with("img/")
            || rel.starts_with("icons/splash-")
            || rel == "sw.js"
            || rel == "manifest.webmanifest"
        {
            continue;
        }
        if let Ok(m) = std::fs::metadata(&pieno) {
            voci.push((rel, mtime(&m), m.len()));
        }
    }
}

/// Version and files of the app, photos excluded: the service worker stores them and the app opens from there.
/// The version is the fingerprint of the content: change a file, it changes, and devices update by themselves.
pub fn guscio(root: &Path) -> (String, Vec<String>) {
    let mut voci = Vec::new();
    cammina(root, root, &mut voci);
    voci.sort();
    let mut g = GUSCIO.lock().unwrap_or_else(|e| e.into_inner());
    if g.chiave.as_ref() != Some(&voci) {
        let mut h = Sha1::new();
        for rel in voci.iter().map(|v| v.0.as_str()).chain(["sw.js"]) {
            h.update(rel.as_bytes());
            h.update(std::fs::read(root.join(rel)).unwrap_or_default());
        }
        g.versione = py::taglia(&hex::encode(h.finalize()), 12);
        g.file = voci
            .iter()
            .map(|v| {
                if v.0 == "index.html" {
                    "./".to_string()
                } else {
                    v.0.clone()
                }
            })
            .collect();
        g.chiave = Some(voci);
    }
    (g.versione.clone(), g.file.clone())
}

/// `posixpath.normpath(p)`
pub fn normpath(p: &str) -> String {
    if p.is_empty() {
        return ".".into();
    }
    let iniziali = if p.starts_with("//") && !p.starts_with("///") {
        2
    } else if p.starts_with('/') {
        1
    } else {
        0
    };
    let mut parti: Vec<&str> = Vec::new();
    for c in p.split('/') {
        match c {
            "" | "." => {}
            ".." if iniziali == 0 && parti.last().is_none_or(|x| *x == "..") => parti.push(".."),
            ".." => {
                parti.pop();
            }
            c => parti.push(c),
        }
    }
    let s = "/".repeat(iniziali) + &parti.join("/");
    if s.is_empty() { ".".into() } else { s }
}

/// `mimetypes.guess_type` for the files the app ships, with the types server.py adds.
pub fn tipo(percorso: &Path) -> &'static str {
    let est = percorso
        .extension()
        .and_then(|e| e.to_str())
        .unwrap_or("")
        .to_ascii_lowercase();
    match est.as_str() {
        "html" | "htm" => "text/html",
        "css" => "text/css",
        "js" | "mjs" => "text/javascript",
        "json" => "application/json",
        "webmanifest" => "application/manifest+json",
        "png" => "image/png",
        "jpg" | "jpeg" => "image/jpeg",
        "gif" => "image/gif",
        "svg" => "image/svg+xml",
        "ico" => "image/vnd.microsoft.icon",
        "webp" => "image/webp",
        "txt" => "text/plain",
        "xml" => "text/xml",
        "pdf" => "application/pdf",
        "wasm" => "application/wasm",
        _ => "application/octet-stream",
    }
}

/// The file under `root` that the request path names, or None when it is outside root or not a regular file.
pub fn trova(root: &Path, path: &str) -> Option<(String, PathBuf)> {
    let rel = normpath(&py::unquote(path))
        .trim_start_matches('/')
        .to_string();
    let rel = if rel.is_empty() || rel == "." {
        "index.html".to_string()
    } else {
        rel
    };
    let base = std::fs::canonicalize(root).ok()?;
    let pieno = std::fs::canonicalize(base.join(&rel)).ok()?;
    (pieno.starts_with(&base) && pieno.is_file()).then_some((rel, pieno))
}

pub fn etag(m: &std::fs::Metadata) -> String {
    format!("\"{:x}-{:x}\"", mtime(m), m.len())
}

#[cfg(test)]
mod test {
    use super::*;

    #[test]
    fn normpath_come_python() {
        for (p, atteso) in [
            ("/", "/"),
            ("/a/../../etc", "/etc"),
            ("/a//b/./c/", "/a/b/c"),
            ("", "."),
            ("a/../..", ".."),
            ("//x", "//x"),
            ("///x", "/x"),
            ("/..", "/"),
        ] {
            assert_eq!(normpath(p), atteso, "{p}");
        }
    }

    #[test]
    fn fuori_dalla_radice() {
        let d = tempfile::tempdir().unwrap();
        std::fs::write(d.path().join("index.html"), "x").unwrap();
        assert_eq!(trova(d.path(), "/").unwrap().0, "index.html");
        assert!(trova(d.path(), "/../../etc/passwd").is_none());
        assert!(trova(d.path(), "/%2e%2e/%2e%2e/etc/passwd").is_none());
        assert!(trova(d.path(), "/nessuno").is_none());
    }
}
