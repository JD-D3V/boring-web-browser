// C interface around the adblock engine, built as a small DLL that the
// browser loads. Keeping it a DLL means its Rust runtime stays separate
// from the Rust that Chromium itself links.

use std::ffi::CStr;
use std::os::raw::{c_char, c_int};
use std::panic::catch_unwind;
use std::sync::RwLock;

use adblock::request::Request;
use adblock::Engine;

pub struct EngineHandle(RwLock<Engine>);

fn cstr<'a>(p: *const c_char) -> Option<&'a str> {
    if p.is_null() {
        return None;
    }
    unsafe { CStr::from_ptr(p) }.to_str().ok()
}

/// Build an engine from filter list text (one or more lists joined with
/// newlines). Returns null on failure. The caller owns the handle.
#[no_mangle]
pub extern "C" fn boring_adblock_new(rules: *const u8, len: usize) -> *mut EngineHandle {
    let result = catch_unwind(|| {
        let bytes = unsafe { std::slice::from_raw_parts(rules, len) };
        let text = String::from_utf8_lossy(bytes);
        Engine::new_with_list_text(text.as_ref())
    });
    match result {
        Ok(engine) => Box::into_raw(Box::new(EngineHandle(RwLock::new(engine)))),
        Err(_) => std::ptr::null_mut(),
    }
}

/// Returns 1 when the request should be blocked, 0 otherwise.
/// request_type uses the adblock list names: script, image, stylesheet,
/// document, subdocument, xmlhttprequest, font, media, websocket, ping,
/// other.
#[no_mangle]
pub extern "C" fn boring_adblock_check(
    handle: *const EngineHandle,
    url: *const c_char,
    source_url: *const c_char,
    request_type: *const c_char,
) -> c_int {
    if handle.is_null() {
        return 0;
    }
    let result = catch_unwind(|| {
        let url = match cstr(url) {
            Some(u) => u,
            None => return 0,
        };
        let source = cstr(source_url).unwrap_or("");
        let rtype = cstr(request_type).unwrap_or("other");
        let request = match Request::new(url, source, rtype, "GET") {
            Ok(r) => r,
            Err(_) => return 0,
        };
        let engine = unsafe { &*handle };
        let guard = match engine.0.read() {
            Ok(g) => g,
            Err(_) => return 0,
        };
        let result = guard.check_network_request(&request);
        if result.filter.is_some() && result.exception.is_none() {
            1
        } else {
            0
        }
    });
    result.unwrap_or(0)
}

#[no_mangle]
pub extern "C" fn boring_adblock_free(handle: *mut EngineHandle) {
    if !handle.is_null() {
        drop(unsafe { Box::from_raw(handle) });
    }
}

// ---- Scam and phishing blocklist ----

pub struct ScamList(std::collections::HashSet<String>);

/// Builds a blocklist from text with one host per line. Lines starting
/// with # are comments. A "127.0.0.1 host" hosts file layout also works.
#[no_mangle]
pub extern "C" fn boring_scamlist_new(text: *const u8, len: usize) -> *mut ScamList {
    let result = catch_unwind(|| {
        let bytes = unsafe { std::slice::from_raw_parts(text, len) };
        let text = String::from_utf8_lossy(bytes);
        let mut set = std::collections::HashSet::new();
        for line in text.lines() {
            let line = line.trim();
            if line.is_empty() || line.starts_with('#') || line.starts_with('!') {
                continue;
            }
            // Take the last field so hosts file lines work too.
            let host = line.split_whitespace().last().unwrap_or("");
            let host = host.trim_start_matches("*.").trim_end_matches('.');
            if host.contains('.') && !host.contains('/') {
                set.insert(host.to_ascii_lowercase());
            }
        }
        set
    });
    match result {
        Ok(set) => Box::into_raw(Box::new(ScamList(set))),
        Err(_) => std::ptr::null_mut(),
    }
}

/// Returns 1 when the host, or any parent domain of it, is on the list.
#[no_mangle]
pub extern "C" fn boring_scamlist_contains(
    handle: *const ScamList,
    host: *const c_char,
) -> c_int {
    if handle.is_null() {
        return 0;
    }
    let result = catch_unwind(|| {
        let host = match cstr(host) {
            Some(h) => h.to_ascii_lowercase(),
            None => return 0,
        };
        let set = &unsafe { &*handle }.0;
        let mut part: &str = host.trim_end_matches('.');
        loop {
            if set.contains(part) {
                return 1;
            }
            match part.split_once('.') {
                Some((_, rest)) if rest.contains('.') => part = rest,
                _ => return 0,
            }
        }
    });
    result.unwrap_or(0)
}

#[no_mangle]
pub extern "C" fn boring_scamlist_free(handle: *mut ScamList) {
    if !handle.is_null() {
        drop(unsafe { Box::from_raw(handle) });
    }
}

/// Returns the number of hosts on the list. Used for logging.
#[no_mangle]
pub extern "C" fn boring_scamlist_size(handle: *const ScamList) -> usize {
    if handle.is_null() {
        return 0;
    }
    unsafe { &*handle }.0.len()
}
