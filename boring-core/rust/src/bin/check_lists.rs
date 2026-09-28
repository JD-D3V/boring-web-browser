//! Parses filter lists with the engine's own parser and reports, as
//! JSON on stdout, what it made of each: rules, network and cosmetic
//! filters, and the lines it did not accept. Then builds one engine from
//! all of them, serializes it and loads it back, the way the browser's
//! engine cache does.
//!
//! tools/publish_lists.py runs this on every list before it publishes a
//! bundle, and applies its own limits to the numbers. This tool only
//! reports; it exits non-zero only when it could not do its job.
//!
//! Usage: check_lists [--trusted] FILE [[--trusted] FILE ...]
//!   --trusted  the next file is used with every scriptlet permission,
//!              as ubo.txt and the uBO annoyances list are.

use std::process::ExitCode;
use std::time::Instant;

use boring_adblock::check::{check_list, errors_json, ListReport};

/// Bad lines listed per file in the output. The count is always exact.
const EXAMPLES: usize = 10;

struct Input {
    path: String,
    trusted: bool,
    text: String,
}

fn parse_args() -> Result<Vec<Input>, String> {
    let mut inputs = Vec::new();
    let mut trusted = false;
    for arg in std::env::args().skip(1) {
        if arg == "--trusted" {
            trusted = true;
            continue;
        }
        let bytes = std::fs::read(&arg).map_err(|e| format!("{arg}: {e}"))?;
        // Strict: the lists are UTF-8, and one that is not has been
        // damaged on the way, which the browser would paper over.
        let text = String::from_utf8(bytes).map_err(|_| format!("{arg}: not valid UTF-8"))?;
        inputs.push(Input {
            path: arg,
            trusted,
            text,
        });
        trusted = false;
    }
    if inputs.is_empty() {
        return Err("usage: check_lists [--trusted] FILE [[--trusted] FILE ...]".to_owned());
    }
    Ok(inputs)
}

fn file_json(input: &Input, report: &ListReport) -> serde_json::Value {
    let examples: serde_json::Value = serde_json::from_str(&errors_json(
        &report.errors[..report.errors.len().min(EXAMPLES)],
    ))
    .unwrap_or_default();
    serde_json::json!({
        "path": input.path,
        "trusted": input.trusted,
        "rules": report.rules,
        "network": report.network,
        "cosmetic": report.cosmetic,
        "errors": report.error_count,
        "examples": examples,
    })
}

// Builds, serializes and reloads one engine from every list. Anything
// going wrong here, a panic included, is reported rather than fatal.
fn engine_json(inputs: &[Input]) -> serde_json::Value {
    let result = std::panic::catch_unwind(|| {
        let start = Instant::now();
        let engine = boring_adblock::build_engine(
            inputs
                .iter()
                .map(|input| (input.text.as_str(), input.trusted)),
        );
        let build_ms = start.elapsed().as_millis();
        let bytes = engine.serialize();
        let mut loaded = adblock::Engine::default();
        let reloaded = loaded.deserialize(&bytes).is_ok();
        (build_ms, bytes.len(), reloaded)
    });
    match result {
        Ok((build_ms, size, reloaded)) => serde_json::json!({
            "built": true,
            "build_ms": build_ms,
            "serialized_bytes": size,
            "reloaded": reloaded,
        }),
        Err(_) => serde_json::json!({ "built": false }),
    }
}

fn main() -> ExitCode {
    let inputs = match parse_args() {
        Ok(inputs) => inputs,
        Err(message) => {
            eprintln!("{message}");
            return ExitCode::from(2);
        }
    };
    let files: Vec<serde_json::Value> = inputs
        .iter()
        .map(|input| file_json(input, &check_list(&input.text, input.trusted)))
        .collect();
    let report = serde_json::json!({
        "adblock": boring_adblock::ADBLOCK_CRATE_VERSION.to_str().unwrap_or_default(),
        "files": files,
        "engine": engine_json(&inputs),
    });
    println!("{report:#}");
    ExitCode::SUCCESS
}
