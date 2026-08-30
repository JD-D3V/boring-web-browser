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
