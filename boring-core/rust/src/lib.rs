// C interface around the adblock engine, built as a small DLL that the
// browser loads. Keeping it a DLL means its Rust runtime stays separate
// from the Rust that Chromium itself links.
//
// Strings handed back to C are allocated here and must be given back to
// `boring_adblock_string_free`, never to the C runtime's free().

use std::collections::HashSet;
use std::ffi::{CStr, CString};
use std::os::raw::{c_char, c_int};
use std::panic::{catch_unwind, AssertUnwindSafe};
use std::sync::{Arc, RwLock};

use adblock::lists::{FilterSet, ParseOptions};
use adblock::request::Request;
use adblock::resources::{
    InMemoryResourceStorage, PermissionMask, Resource, ResourceImpl, ResourceStorageBackend,
};
use adblock::Engine;

pub struct EngineHandle(RwLock<Engine>);

// The engine is read from several browser threads at once. This fails to
// build if the adblock crate is ever built with its "single-thread"
// feature again, which would make those reads a data race.
const _: () = {
    const fn assert_send_sync<T: Send + Sync>() {}
    assert_send_sync::<Engine>();
};

fn cstr<'a>(p: *const c_char) -> Option<&'a str> {
    if p.is_null() {
        return None;
    }
    unsafe { CStr::from_ptr(p) }.to_str().ok()
}

// Hands a string to C. Null when it holds a NUL, which JSON never does.
fn to_c_string(s: String) -> *mut c_char {
    match CString::new(s) {
        Ok(c) => c.into_raw(),
        Err(_) => std::ptr::null_mut(),
    }
}

// Reads `count` C strings. Null entries and invalid UTF-8 are skipped.
//
// # Safety
// `items` must be null, or point to `count` pointers that are each null
// or a valid NUL-terminated C string.
unsafe fn str_array<'a>(items: *const *const c_char, count: usize) -> Vec<&'a str> {
    if items.is_null() || count == 0 {
        return Vec::new();
    }
    let items = unsafe { std::slice::from_raw_parts(items, count) };
    items.iter().filter_map(|p| cstr(*p)).collect()
}

fn engine_ref<'a>(handle: *const EngineHandle) -> Option<&'a EngineHandle> {
    if handle.is_null() {
        None
    } else {
        Some(unsafe { &*handle })
    }
}

/// Build an engine from filter list text (one or more lists joined with
/// newlines). Returns null on failure. The caller owns the handle and
/// must give it back to `boring_adblock_free`.
///
/// # Safety
/// `rules` must point to `len` readable bytes.
#[no_mangle]
pub unsafe extern "C" fn boring_adblock_new(rules: *const u8, len: usize) -> *mut EngineHandle {
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

/// One filter list for `boring_adblock_new_lists`.
#[repr(C)]
pub struct BoringAdblockList {
    /// The list text, not NUL-terminated.
    pub text: *const u8,
    pub len: usize,
    /// Non-zero for a list we trust with every scriptlet permission
    /// (uBO's own lists). Zero for everything else, which then cannot
    /// use trusted scriptlets such as trusted-set-cookie.
    pub trusted: c_int,
}

// Every permission bit. uBO marks its powerful scriptlets
// "requiresTrust" and only runs them from its own lists; the resources
// file carries that as a permission bit, and a trusted list may use any.
const FULL_TRUST: PermissionMask = PermissionMask::from_bits(0xff);

/// Builds one engine from several filter lists, each with its own trust
/// level, so a rule in one list can be cancelled by an exception in
/// another. Returns null on failure. The caller owns the handle and must
/// give it back to `boring_adblock_free`.
///
/// # Safety
/// `lists` must be null or point to `count` entries, and each entry's
/// `text` must point to `len` readable bytes (or be null with `len` 0).
#[no_mangle]
pub unsafe extern "C" fn boring_adblock_new_lists(
    lists: *const BoringAdblockList,
    count: usize,
) -> *mut EngineHandle {
    let result = catch_unwind(|| {
        let lists = if lists.is_null() || count == 0 {
            &[][..]
        } else {
            unsafe { std::slice::from_raw_parts(lists, count) }
        };
        let mut set = FilterSet::new(false);
        for list in lists {
            if list.text.is_null() || list.len == 0 {
                continue;
            }
            let bytes = unsafe { std::slice::from_raw_parts(list.text, list.len) };
            let permissions = if list.trusted != 0 {
                FULL_TRUST
            } else {
                PermissionMask::default()
            };
            set.add_filter_list(
                String::from_utf8_lossy(bytes).into_owned(),
                ParseOptions {
                    permissions,
                    ..ParseOptions::default()
                },
            );
        }
        Engine::new_with_filter_set(set)
    });
    match result {
        Ok(engine) => Box::into_raw(Box::new(EngineHandle(RwLock::new(engine)))),
        Err(_) => std::ptr::null_mut(),
    }
}

// ---- Scriptlet and $redirect resources ----

/// Parsed resources.json, shared by every engine that uses it so the
/// scriptlets and stub files are held in memory once.
pub struct ResourcesHandle {
    storage: Arc<InMemoryResourceStorage>,
    count: usize,
}

struct SharedResources(Arc<InMemoryResourceStorage>);

impl ResourceStorageBackend for SharedResources {
    fn get_resource(&self, resource_ident: &str) -> Option<ResourceImpl> {
        self.0.get_resource(resource_ident)
    }
}

// Parses an adblock-rust `Resource` array. An entry that does not parse
// or does not decode is skipped rather than failing the whole file, so
// one bad scriptlet cannot take the rest with it.
fn parse_resources(text: &str) -> Option<(InMemoryResourceStorage, usize)> {
    let entries: Vec<serde_json::Value> = serde_json::from_str(text).ok()?;
    let mut storage = InMemoryResourceStorage::default();
    let mut count = 0;
    for entry in entries {
        let Ok(resource) = serde_json::from_value::<Resource>(entry) else {
            continue;
        };
        if storage.add_resource(resource).is_ok() {
            count += 1;
        }
    }
    Some((storage, count))
}

/// Parses resources.json (a JSON array of adblock-rust `Resource`
/// objects). Returns null when the text is not a JSON array; entries
/// that are broken on their own are skipped. The caller owns the handle
/// and must give it back to `boring_resources_free`.
///
/// # Safety
/// `json` must point to `len` readable bytes.
#[no_mangle]
pub unsafe extern "C" fn boring_resources_new(json: *const u8, len: usize) -> *mut ResourcesHandle {
    if json.is_null() {
        return std::ptr::null_mut();
    }
    let result = catch_unwind(|| {
        let bytes = unsafe { std::slice::from_raw_parts(json, len) };
        let text = std::str::from_utf8(bytes).ok()?;
        parse_resources(text)
    });
    match result {
        Ok(Some((storage, count))) => Box::into_raw(Box::new(ResourcesHandle {
            storage: Arc::new(storage),
            count,
        })),
        _ => std::ptr::null_mut(),
    }
}

/// How many resources were loaded. Used for logging.
///
/// # Safety
/// `handle` must be null, or resources from `boring_resources_new` that
/// have not been freed.
#[no_mangle]
pub unsafe extern "C" fn boring_resources_count(handle: *const ResourcesHandle) -> usize {
    if handle.is_null() {
        return 0;
    }
    unsafe { &*handle }.count
}

/// Frees resources. Engines already given them keep their own reference.
///
/// # Safety
/// `handle` must be null, or resources from `boring_resources_new` that
/// have not already been freed. It must not be used afterwards.
#[no_mangle]
pub unsafe extern "C" fn boring_resources_free(handle: *mut ResourcesHandle) {
    if !handle.is_null() {
        drop(unsafe { Box::from_raw(handle) });
    }
}

/// Gives an engine the scriptlets and $redirect stubs to use. Replaces
/// any it had. Returns 1 on success, 0 otherwise. Network blocking works
/// with or without resources; without them, ##+js rules inject nothing
/// and $redirect rules block instead of redirecting.
///
/// Safe while other threads are checking requests: this takes the
/// engine's write lock, so it waits for checks in progress and holds
/// new ones back for the moment it takes to swap.
///
/// # Safety
/// `handle` must be null, or an engine from `boring_adblock_new*` that
/// has not been freed. `resources` must be null, or resources from
/// `boring_resources_new` that have not been freed.
#[no_mangle]
pub unsafe extern "C" fn boring_adblock_use_resources(
    handle: *mut EngineHandle,
    resources: *const ResourcesHandle,
) -> c_int {
    if handle.is_null() || resources.is_null() {
        return 0;
    }
    let result = catch_unwind(AssertUnwindSafe(|| {
        let engine = unsafe { &*handle };
        let storage = Arc::clone(&unsafe { &*resources }.storage);
        match engine.0.write() {
            Ok(mut guard) => {
                guard.use_resource_storage(SharedResources(storage));
                1
            }
            Err(_) => 0,
        }
    }));
    result.unwrap_or(0)
}

// ---- Network requests ----

/// Returns 1 when the request should be blocked, 0 otherwise.
///
/// # Safety
/// `handle` must be null, or an engine from `boring_adblock_new` that has
/// not been freed. The three string arguments must be null or valid
/// NUL-terminated C strings.
///
/// request_type uses the adblock list names: script, image, stylesheet,
/// document, subdocument, xmlhttprequest, font, media, websocket, ping,
/// other.
#[no_mangle]
pub unsafe extern "C" fn boring_adblock_check(
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
        if guard.check_network_request(&request).should_block() {
            1
        } else {
            0
        }
    });
    result.unwrap_or(0)
}

/// A blocking rule matched (it may still be cancelled by an exception).
pub const BORING_ADBLOCK_MATCHED: c_int = 1;
/// An exception rule matched.
pub const BORING_ADBLOCK_EXCEPTION: c_int = 2;
/// An $important rule matched: block, whatever any exception says, and
/// stop asking further engines.
pub const BORING_ADBLOCK_IMPORTANT: c_int = 4;

/// Checks a request and says what matched, as a mask of the
/// BORING_ADBLOCK_* bits above. 0 means nothing matched or the check
/// failed. The request is blocked when IMPORTANT is set, or when MATCHED
/// is set and EXCEPTION is not.
///
/// To check several engines as one, like uBO checks several lists, pass
/// what earlier engines found: `previously_matched` skips looking for
/// blocking rules and looks only for exceptions to that earlier match;
/// `force_check_exceptions` looks for exceptions even when nothing here
/// matched. Stop at the first IMPORTANT.
///
/// When `redirect_out` is not null it receives a `data:` URL to serve in
/// place of the request when a $redirect or $redirect-rule applies, else
/// null. A redirect alone does not mean the request is blocked: serve it
/// only when the request is blocked. Free it with
/// `boring_adblock_string_free`.
///
/// # Safety
/// `handle` must be null, or an engine from `boring_adblock_new*` that
/// has not been freed. The three string arguments must be null or valid
/// NUL-terminated C strings. `redirect_out` must be null or writable.
#[no_mangle]
pub unsafe extern "C" fn boring_adblock_check_request(
    handle: *const EngineHandle,
    url: *const c_char,
    source_url: *const c_char,
    request_type: *const c_char,
    previously_matched: c_int,
    force_check_exceptions: c_int,
    redirect_out: *mut *mut c_char,
) -> c_int {
    if !redirect_out.is_null() {
        unsafe { *redirect_out = std::ptr::null_mut() };
    }
    let Some(engine) = engine_ref(handle) else {
        return 0;
    };
    let result = catch_unwind(AssertUnwindSafe(|| {
        let url = cstr(url)?;
        let source = cstr(source_url).unwrap_or("");
        let rtype = cstr(request_type).unwrap_or("other");
        let request = Request::new(url, source, rtype, "GET").ok()?;
        let guard = engine.0.read().ok()?;
        Some(guard.check_network_request_subset(
            &request,
            previously_matched != 0,
            force_check_exceptions != 0,
        ))
    }));
    let Ok(Some(checked)) = result else {
        return 0;
    };
    let mut flags = 0;
    if checked.filter.is_some() {
        flags |= BORING_ADBLOCK_MATCHED;
    }
    if checked.exception.is_some() {
        flags |= BORING_ADBLOCK_EXCEPTION;
    }
    if checked.important {
        flags |= BORING_ADBLOCK_IMPORTANT;
    }
    if !redirect_out.is_null() {
        if let Some(redirect) = checked.redirect {
            unsafe { *redirect_out = to_c_string(redirect) };
        }
    }
    flags
}

// ---- Cosmetic filters ----

/// The cosmetic filters for a page, as JSON:
/// `{"hide_selectors": [..], "procedural_actions": [..], "exceptions":
/// [..], "injected_script": "..", "generichide": false}`.
/// procedural_actions entries are themselves JSON strings in adblock-rust's
/// format. Returns null on failure. Free the result with
/// `boring_adblock_string_free`.
///
/// # Safety
/// `handle` must be null, or an engine from `boring_adblock_new*` that
/// has not been freed. `url` must be null or a valid NUL-terminated C
/// string.
#[no_mangle]
pub unsafe extern "C" fn boring_adblock_url_cosmetic_resources(
    handle: *const EngineHandle,
    url: *const c_char,
) -> *mut c_char {
    let Some(engine) = engine_ref(handle) else {
        return std::ptr::null_mut();
    };
    let result = catch_unwind(AssertUnwindSafe(|| {
        let url = cstr(url)?;
        let guard = engine.0.read().ok()?;
        serde_json::to_string(&guard.url_cosmetic_resources(url)).ok()
    }));
    match result {
        Ok(Some(json)) => to_c_string(json),
        _ => std::ptr::null_mut(),
    }
}

/// Generic hide selectors for the given class names and ids found on a
/// page, as a JSON array of strings. `exceptions` is the exceptions list
/// from `boring_adblock_url_cosmetic_resources`. Class names and ids are
/// passed bare, without the leading `.` or `#`. Returns null on failure.
/// Free the result with `boring_adblock_string_free`.
///
/// # Safety
/// `handle` must be null, or an engine from `boring_adblock_new*` that
/// has not been freed. Each array must be null or point to its count of
/// pointers, each null or a valid NUL-terminated C string.
#[no_mangle]
pub unsafe extern "C" fn boring_adblock_hidden_class_id_selectors(
    handle: *const EngineHandle,
    classes: *const *const c_char,
    class_count: usize,
    ids: *const *const c_char,
    id_count: usize,
    exceptions: *const *const c_char,
    exception_count: usize,
) -> *mut c_char {
    let Some(engine) = engine_ref(handle) else {
        return std::ptr::null_mut();
    };
    let result = catch_unwind(AssertUnwindSafe(|| {
        let classes = unsafe { str_array(classes, class_count) };
        let ids = unsafe { str_array(ids, id_count) };
        let exceptions: HashSet<String> = unsafe { str_array(exceptions, exception_count) }
            .into_iter()
            .map(str::to_owned)
            .collect();
        let guard = engine.0.read().ok()?;
        let selectors = guard.hidden_class_id_selectors(classes, ids, &exceptions);
        serde_json::to_string(&selectors).ok()
    }));
    match result {
        Ok(Some(json)) => to_c_string(json),
        _ => std::ptr::null_mut(),
    }
}

/// Frees a string returned by this library.
///
/// # Safety
/// `s` must be null, or a string returned by this library that has not
/// already been freed. It must not be used afterwards.
#[no_mangle]
pub unsafe extern "C" fn boring_adblock_string_free(s: *mut c_char) {
    if !s.is_null() {
        drop(unsafe { CString::from_raw(s) });
    }
}

/// Frees an engine.
///
/// # Safety
/// `handle` must be null, or an engine from `boring_adblock_new*` that
/// has not already been freed. It must not be used afterwards.
#[no_mangle]
pub unsafe extern "C" fn boring_adblock_free(handle: *mut EngineHandle) {
    if !handle.is_null() {
        drop(unsafe { Box::from_raw(handle) });
    }
}

// ---- Scam and phishing blocklist ----

pub struct ScamList(std::collections::HashSet<String>);

/// Builds a blocklist from text with one host per line. Lines starting
/// with # are comments. A "127.0.0.1 host" hosts file layout also works.
/// The caller owns the list and must give it back to
/// `boring_scamlist_free`.
///
/// # Safety
/// `text` must point to `len` readable bytes.
#[no_mangle]
pub unsafe extern "C" fn boring_scamlist_new(text: *const u8, len: usize) -> *mut ScamList {
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
///
/// # Safety
/// `handle` must be null, or a list from `boring_scamlist_new` that has
/// not been freed. `host` must be null or a valid NUL-terminated C string.
#[no_mangle]
pub unsafe extern "C" fn boring_scamlist_contains(
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

/// Frees a blocklist.
///
/// # Safety
/// `handle` must be null, or a list from `boring_scamlist_new` that has
/// not already been freed. It must not be used afterwards.
#[no_mangle]
pub unsafe extern "C" fn boring_scamlist_free(handle: *mut ScamList) {
    if !handle.is_null() {
        drop(unsafe { Box::from_raw(handle) });
    }
}

/// Returns the number of hosts on the list. Used for logging.
///
/// # Safety
/// `handle` must be null, or a list from `boring_scamlist_new` that has
/// not been freed.
#[no_mangle]
pub unsafe extern "C" fn boring_scamlist_size(handle: *const ScamList) -> usize {
    if handle.is_null() {
        return 0;
    }
    unsafe { &*handle }.0.len()
}

#[cfg(test)]
mod tests {
    use super::*;
    use base64::{engine::general_purpose::STANDARD, Engine as _};

    struct Owned(*mut EngineHandle);

    impl Drop for Owned {
        fn drop(&mut self) {
            unsafe { boring_adblock_free(self.0) };
        }
    }

    fn engine(lists: &[(&str, bool)]) -> Owned {
        let entries: Vec<BoringAdblockList> = lists
            .iter()
            .map(|(text, trusted)| BoringAdblockList {
                text: text.as_ptr(),
                len: text.len(),
                trusted: c_int::from(*trusted),
            })
            .collect();
        let handle = unsafe { boring_adblock_new_lists(entries.as_ptr(), entries.len()) };
        assert!(!handle.is_null());
        Owned(handle)
    }

    fn resource(name: &str, kind: serde_json::Value, body: &str, permission: u8) -> String {
        serde_json::json!({
            "name": name,
            "aliases": [],
            "kind": kind,
            "content": STANDARD.encode(body),
            "permission": permission,
        })
        .to_string()
    }

    fn give_resources(engine: &Owned, json: &str) {
        unsafe {
            let resources = boring_resources_new(json.as_ptr(), json.len());
            assert!(!resources.is_null());
            assert_eq!(boring_adblock_use_resources(engine.0, resources), 1);
            // The engine keeps its own reference.
            boring_resources_free(resources);
        }
    }

    fn take_string(p: *mut c_char) -> String {
        assert!(!p.is_null());
        let s = unsafe { CStr::from_ptr(p) }.to_str().unwrap().to_owned();
        unsafe { boring_adblock_string_free(p) };
        s
    }

    fn cosmetic(engine: &Owned, url: &str) -> serde_json::Value {
        let url = CString::new(url).unwrap();
        let json =
            take_string(unsafe { boring_adblock_url_cosmetic_resources(engine.0, url.as_ptr()) });
        serde_json::from_str(&json).unwrap()
    }

    fn check(engine: &Owned, url: &str, rtype: &str) -> (c_int, Option<String>) {
        let url = CString::new(url).unwrap();
        let source = CString::new("https://page.test/").unwrap();
        let rtype = CString::new(rtype).unwrap();
        let mut redirect: *mut c_char = std::ptr::null_mut();
        let flags = unsafe {
            boring_adblock_check_request(
                engine.0,
                url.as_ptr(),
                source.as_ptr(),
                rtype.as_ptr(),
                0,
                0,
                &mut redirect,
            )
        };
        let redirect = (!redirect.is_null()).then(|| take_string(redirect));
        (flags, redirect)
    }

    // A template scriptlet that needs trust bit 1, like uBO's trusted-*.
    fn trusted_scriptlet() -> String {
        format!(
            "[{}]",
            resource(
                "trusted-test.js",
                serde_json::json!("template"),
                "window.trustedRan = '{{1}}';",
                1,
            )
        )
    }

    #[test]
    fn hide_rule_reaches_hide_selectors() {
        let e = engine(&[("example.com##.ad-banner\n", false)]);
        let res = cosmetic(&e, "https://example.com/page");
        let selectors = res["hide_selectors"].as_array().unwrap();
        assert!(selectors.iter().any(|s| s == ".ad-banner"));
        assert_eq!(res["generichide"], false);

        let other = cosmetic(&e, "https://other.test/");
        assert!(other["hide_selectors"].as_array().unwrap().is_empty());
    }

    // Needs the crate's css-validation feature. Without it the rule comes
    // back as a plain selector, which the page's CSS parser rejects, and
    // the element stays visible.
    #[test]
    fn procedural_rule_reaches_procedural_actions() {
        let e = engine(&[("example.com##div:has-text(Sponsored)\n", false)]);
        let res = cosmetic(&e, "https://example.com/page");
        assert!(res["hide_selectors"].as_array().unwrap().is_empty());
        let actions = res["procedural_actions"].as_array().unwrap();
        assert_eq!(actions.len(), 1);
        assert!(actions[0].as_str().unwrap().contains("has-text"));
    }

    #[test]
    fn generic_hide_rule_found_by_class() {
        let e = engine(&[("##.sponsored-card\n", false)]);
        let class = CString::new("sponsored-card").unwrap();
        let classes = [class.as_ptr()];
        let json = take_string(unsafe {
            boring_adblock_hidden_class_id_selectors(
                e.0,
                classes.as_ptr(),
                1,
                std::ptr::null(),
                0,
                std::ptr::null(),
                0,
            )
        });
        let selectors: Vec<String> = serde_json::from_str(&json).unwrap();
        assert_eq!(selectors, vec![".sponsored-card".to_string()]);
    }

    #[test]
    fn scriptlet_rule_injects_script() {
        let e = engine(&[("example.com##+js(boring-test, 42)\n", false)]);
        let resources = format!(
            "[{}]",
            resource(
                "boring-test.js",
                serde_json::json!("template"),
                "window.boringTest = '{{1}}';",
                0,
            )
        );
        give_resources(&e, &resources);
        let res = cosmetic(&e, "https://example.com/");
        let script = res["injected_script"].as_str().unwrap();
        assert!(script.contains("window.boringTest = '42';"), "{script}");
    }

    #[test]
    fn redirect_rule_returns_data_url() {
        let e = engine(&[("||ads.test/player.js$script,redirect=noop.js\n", false)]);
        let resources = format!(
            "[{}]",
            resource(
                "noop.js",
                serde_json::json!({ "mime": "application/javascript" }),
                "(function() {})();",
                0,
            )
        );
        give_resources(&e, &resources);
        let (flags, redirect) = check(&e, "https://ads.test/player.js", "script");
        assert_ne!(flags & BORING_ADBLOCK_MATCHED, 0);
        let redirect = redirect.expect("a redirect");
        assert!(
            redirect.starts_with("data:application/javascript;base64,"),
            "{redirect}"
        );
    }

    // uBO answers fetch and XHR calls to Google's ad server with a stub.
    // A <script> from the same server must not get that stub from an
    // $xhr rule; another rule blocks it.
    #[test]
    fn xhr_redirect_does_not_reach_scripts() {
        let e = engine(&[(
            "||pagead2.googlesyndication.com^\n\
             ||pagead2.googlesyndication.com^$xhr,redirect=noop.js\n",
            false,
        )]);
        let resources = format!(
            "[{}]",
            resource(
                "noop.js",
                serde_json::json!({ "mime": "application/javascript" }),
                "(function() {})();",
                0,
            )
        );
        give_resources(&e, &resources);
        let url = "https://pagead2.googlesyndication.com/pagead/js/adsbygoogle.js";
        let (xhr_flags, xhr_redirect) = check(&e, url, "xmlhttprequest");
        assert_ne!(xhr_flags & BORING_ADBLOCK_MATCHED, 0);
        assert!(xhr_redirect.is_some());
        let (script_flags, script_redirect) = check(&e, url, "script");
        assert_ne!(script_flags & BORING_ADBLOCK_MATCHED, 0);
        assert!(script_redirect.is_none(), "{script_redirect:?}");
    }

    #[test]
    fn redirect_without_resources_still_blocks() {
        let e = engine(&[("||ads.test/player.js$script,redirect=noop.js\n", false)]);
        let (flags, redirect) = check(&e, "https://ads.test/player.js", "script");
        assert_ne!(flags & BORING_ADBLOCK_MATCHED, 0);
        assert!(redirect.is_none());
    }

    #[test]
    fn trusted_scriptlet_needs_trusted_list() {
        let rule = "example.com##+js(trusted-test, yes)\n";

        let standard = engine(&[(rule, false)]);
        give_resources(&standard, &trusted_scriptlet());
        let res = cosmetic(&standard, "https://example.com/");
        assert!(!res["injected_script"]
            .as_str()
            .unwrap()
            .contains("trustedRan"));

        let trusted = engine(&[("", false), (rule, true)]);
        give_resources(&trusted, &trusted_scriptlet());
        let res = cosmetic(&trusted, "https://example.com/");
        assert!(res["injected_script"]
            .as_str()
            .unwrap()
            .contains("window.trustedRan = 'yes';"));
    }

    #[test]
    fn exception_in_one_list_cancels_block_in_another() {
        let e = engine(&[
            ("||tracker.test^\n", false),
            ("@@||tracker.test/ok.js\n", true),
        ]);
        let (flags, _) = check(&e, "https://tracker.test/ok.js", "script");
        assert_ne!(flags & BORING_ADBLOCK_MATCHED, 0);
        assert_ne!(flags & BORING_ADBLOCK_EXCEPTION, 0);
        let (flags, _) = check(&e, "https://tracker.test/bad.js", "script");
        assert_eq!(flags, BORING_ADBLOCK_MATCHED);
    }

    #[test]
    fn earlier_match_is_excepted_by_later_engine() {
        let later = engine(&[("@@||tracker.test/ok.js\n", false)]);
        let url = CString::new("https://tracker.test/ok.js").unwrap();
        let rtype = CString::new("script").unwrap();
        let flags = unsafe {
            boring_adblock_check_request(
                later.0,
                url.as_ptr(),
                std::ptr::null(),
                rtype.as_ptr(),
                1,
                0,
                std::ptr::null_mut(),
            )
        };
        assert_ne!(flags & BORING_ADBLOCK_EXCEPTION, 0);
    }

    #[test]
    fn bad_resources_do_not_break_blocking() {
        let bad = "not json";
        assert!(unsafe { boring_resources_new(bad.as_ptr(), bad.len()) }.is_null());

        // One broken entry is skipped, the good one still loads.
        let mixed = format!(
            "[{{\"name\": 5}}, {}]",
            resource(
                "noop.js",
                serde_json::json!({ "mime": "application/javascript" }),
                "",
                0
            )
        );
        let resources = unsafe { boring_resources_new(mixed.as_ptr(), mixed.len()) };
        assert_eq!(unsafe { boring_resources_count(resources) }, 1);
        unsafe { boring_resources_free(resources) };

        let e = engine(&[("||ads.test^\n", false)]);
        let (flags, _) = check(&e, "https://ads.test/x.js", "script");
        assert_eq!(flags, BORING_ADBLOCK_MATCHED);
    }

    #[test]
    fn null_arguments_are_safe() {
        unsafe {
            let mut out: *mut c_char = std::ptr::null_mut();
            assert_eq!(
                boring_adblock_check_request(
                    std::ptr::null(),
                    std::ptr::null(),
                    std::ptr::null(),
                    std::ptr::null(),
                    0,
                    0,
                    &mut out,
                ),
                0
            );
            assert!(out.is_null());
            assert!(
                boring_adblock_url_cosmetic_resources(std::ptr::null(), std::ptr::null()).is_null()
            );
            assert_eq!(
                boring_adblock_use_resources(std::ptr::null_mut(), std::ptr::null()),
                0
            );
            boring_adblock_string_free(std::ptr::null_mut());
            boring_resources_free(std::ptr::null_mut());
            let e = boring_adblock_new_lists(std::ptr::null(), 0);
            assert!(!e.is_null());
            boring_adblock_free(e);
        }
    }

    #[test]
    fn old_single_list_functions_still_work() {
        let rules = "||ads.test^\n";
        let e = Owned(unsafe { boring_adblock_new(rules.as_ptr(), rules.len()) });
        let url = CString::new("https://ads.test/a.js").unwrap();
        let rtype = CString::new("script").unwrap();
        let blocked =
            unsafe { boring_adblock_check(e.0, url.as_ptr(), std::ptr::null(), rtype.as_ptr()) };
        assert_eq!(blocked, 1);
    }
}
