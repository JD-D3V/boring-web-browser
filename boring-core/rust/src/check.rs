//! Line by line reports on filter rules, made with the parser the engine
//! itself uses, so a rule reported as fine here is one the engine keeps.
//!
//! Two users: the browser, which tells a person which of their own rules
//! did nothing, and tools/publish_lists.py (through the check_lists
//! binary), which refuses to publish a list the engine cannot read.

use adblock::lists::{parse_filter, FilterParseError, ParseOptions, ParsedLine};
use adblock::resources::PermissionMask;

/// Never report more than this many bad lines. A pasted list of
/// thousands of broken lines needs the first ones fixed, not all of them
/// listed.
pub const MAX_REPORTED: usize = 1000;

/// One line the engine did not accept.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct RuleError {
    /// 1-based, as an editor shows it.
    pub line: usize,
    pub rule: String,
    pub error: String,
}

/// What the engine made of a list.
#[derive(Debug, Default, Clone)]
pub struct ListReport {
    /// Lines that are rules, not comments or blank.
    pub rules: usize,
    pub network: usize,
    pub cosmetic: usize,
    /// How many lines the engine did not accept, reported or not.
    pub error_count: usize,
    /// The first MAX_REPORTED of them.
    pub errors: Vec<RuleError>,
}

// Lines the engine skips on purpose. These mirror adblock-rust's own
// test (detect_filter_type in lists.rs), so a comment is never reported
// as a broken rule.
fn is_comment(line: &str) -> bool {
    line.len() == 1
        || line.starts_with('!')
        || line.starts_with("[Adblock")
        || (line.starts_with('#') && line[1..].starts_with(char::is_whitespace))
}

// uBO marks its powerful scriptlets by name: every one that needs a
// trusted list is called trusted-something. Checked by name because a
// rule parses the same whether or not its scriptlet may run.
fn uses_trusted_scriptlet(line: &str) -> bool {
    let Some(start) = line.find("+js(") else {
        return false;
    };
    line[start + 4..].trim_start().starts_with("trusted-")
}

fn describe(error: &FilterParseError) -> String {
    match error {
        FilterParseError::Unsupported => "not a rule this blocker understands".to_owned(),
        other => other.to_string(),
    }
}

/// Parses every line of `text`. With `trusted` false, a rule that names
/// a trusted-only scriptlet counts as an error too, because it would
/// silently do nothing.
pub fn check_list(text: &str, trusted: bool) -> ListReport {
    let options = ParseOptions {
        permissions: if trusted {
            PermissionMask::from_bits(0xff)
        } else {
            PermissionMask::default()
        },
        ..ParseOptions::default()
    };
    let mut report = ListReport::default();
    for (index, raw) in text.lines().enumerate() {
        let line = raw.trim();
        if line.is_empty() || is_comment(line) {
            continue;
        }
        report.rules += 1;
        let error = match parse_filter(line, false, options) {
            Ok(ParsedLine::Network(_)) => {
                report.network += 1;
                None
            }
            Ok(ParsedLine::Cosmetic(_)) if !trusted && uses_trusted_scriptlet(line) => {
                Some("trusted scriptlets only run from the built-in lists".to_owned())
            }
            Ok(ParsedLine::Cosmetic(_)) => {
                report.cosmetic += 1;
                None
            }
            Err(e) => Some(describe(&e)),
        };
        if let Some(error) = error {
            report.error_count += 1;
            if report.errors.len() < MAX_REPORTED {
                report.errors.push(RuleError {
                    line: index + 1,
                    rule: line.to_owned(),
                    error,
                });
            }
        }
    }
    report
}

/// The errors as a JSON array of {"line", "rule", "error"}.
pub fn errors_json(errors: &[RuleError]) -> String {
    let items: Vec<serde_json::Value> = errors
        .iter()
        .map(|e| serde_json::json!({ "line": e.line, "rule": e.rule, "error": e.error }))
        .collect();
    serde_json::Value::Array(items).to_string()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn comments_and_blank_lines_are_not_rules() {
        let report = check_list("! a comment\n\n[Adblock Plus 2.0]\n# note\n", false);
        assert_eq!(report.rules, 0);
        assert!(report.errors.is_empty());
    }

    #[test]
    fn good_rules_are_counted() {
        let report = check_list(
            "||ads.test^\nexample.com##.ad\n@@||ok.test^\nexample.com#@#.ad\n",
            false,
        );
        assert_eq!(report.rules, 4);
        assert_eq!(report.network, 2);
        assert_eq!(report.cosmetic, 2);
        assert_eq!(report.error_count, 0);
    }

    #[test]
    fn a_bad_rule_is_reported_with_its_line() {
        let report = check_list("||ads.test^\n||bad.test^$unknownoption\n", false);
        assert_eq!(report.error_count, 1);
        assert_eq!(report.errors[0].line, 2);
        assert_eq!(report.errors[0].rule, "||bad.test^$unknownoption");
        assert!(!report.errors[0].error.is_empty());
    }

    #[test]
    fn trusted_scriptlets_are_refused_from_untrusted_rules_only() {
        let rule = "example.com##+js(trusted-set-cookie, a, b)\n";
        assert_eq!(check_list(rule, false).error_count, 1);
        assert_eq!(check_list(rule, true).error_count, 0);
        let plain = "example.com##+js(set-constant, a, 1)\n";
        assert_eq!(check_list(plain, false).error_count, 0);
    }

    #[test]
    fn errors_are_capped() {
        let text = "||x.test^$nosuchoption\n".repeat(MAX_REPORTED + 5);
        let report = check_list(&text, false);
        assert_eq!(report.error_count, MAX_REPORTED + 5);
        assert_eq!(report.errors.len(), MAX_REPORTED);
    }

    #[test]
    fn errors_serialize_as_json() {
        let report = check_list("||bad.test^$nosuchoption\n", false);
        let parsed: serde_json::Value = serde_json::from_str(&errors_json(&report.errors)).unwrap();
        assert_eq!(parsed[0]["line"], 1);
        assert_eq!(parsed[0]["rule"], "||bad.test^$nosuchoption");
    }
}
