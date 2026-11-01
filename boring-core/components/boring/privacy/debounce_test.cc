// Copyright 2026 boring. BSD style license.
//
// Debounce() against sample addresses: the ones it has to skip, and the
// ones it must leave alone however they are dressed up. A plain program
// rather than a gtest, so it builds with the browser and nothing else:
//
//   ninja -C out\Default debounce_test
//   out\Default\debounce_test.exe
//
// Prints one line per failure and exits with how many there were.

#include <iostream>
#include <memory>
#include <optional>
#include <string>
#include <vector>

#include "base/at_exit.h"
#include "base/feature_list.h"
#include "base/strings/escape.h"
#include "components/boring/privacy/debounce.h"
#include "url/gurl.h"

namespace {

int g_failures = 0;
int g_checks = 0;

// `text` as the value of a query parameter.
std::string Enc(const std::string& text) {
  return base::EscapeQueryParamValue(text, /*use_plus=*/false);
}

std::string Got(const std::string& input) {
  std::optional<GURL> out = boring::Debounce(GURL(input));
  return out ? out->spec() : "(nothing)";
}

// `input` has to come out as `want`.
void Follows(const std::string& input, const std::string& want) {
  ++g_checks;
  const std::string got = Got(input);
  if (got != want) {
    ++g_failures;
    std::cout << "FAIL follows\n  input: " << input.substr(0, 200)
              << "\n  want:  " << want << "\n  got:   " << got.substr(0, 200)
              << "\n";
  }
}

// `input` has to be left as it is.
void Leaves(const std::string& input) {
  Follows(input, "(nothing)");
}

}  // namespace

int main() {
  base::AtExitManager at_exit;
  // Some of base reads feature flags; give it a list with the defaults.
  auto features = std::make_unique<base::FeatureList>();
  features->InitFromCommandLine(std::string(), std::string());
  base::FeatureList::SetInstance(std::move(features));

  const std::string fb = "https://l.facebook.com/l.php?u=";
  const std::string goog = "https://www.google.com/url?q=";
  const std::string example = "https://example.com/";

  // ---- Redirectors that are skipped. ----
  Follows(fb + "https%3A%2F%2Fexample.com%2Fpage%3Fa%3D1%26b%3D2&h=AT0abc",
          "https://example.com/page?a=1&b=2");
  Follows("https://lm.facebook.com/l.php?u=http%3A%2F%2Fexample.org%2F&h=x",
          "http://example.org/");
  Follows("https://l.messenger.com/l.php?u=https%3A%2F%2Fexample.com%2F",
          example);
  Follows("https://l.facebook.com:8443/l.php?u=https%3A%2F%2Fexample.com%2F",
          example);
  Follows("HTTPS://L.FACEBOOK.COM/l.php?u=HTTPS%3A%2F%2Fexample.com%2F",
          example);
  Follows("https://l.instagram.com/?u=https%3A%2F%2Fexample.com%2Fa&e=AT1",
          "https://example.com/a");
  Follows(goog + "https://example.com/a?b=c&sa=U&ved=2ah",
          "https://example.com/a?b=c");
  Follows(
      "https://www.google.com/url?sa=t&rct=j&q=&esrc=s&url="
      "https%3A%2F%2Fexample.com%2Fa&ved=2ah",
      "https://example.com/a");
  Follows("https://www.google.co.uk/url?q=https%3A%2F%2Fexample.com%2F",
          example);
  Follows(
      "https://www.youtube.com/redirect?event=video_description&q="
      "https%3A%2F%2Fexample.com%2F&v=abc",
      example);
  Follows("https://out.reddit.com/t3_abc?url=https%3A%2F%2Fexample.com%2F&x=1",
          example);
  Follows("https://duckduckgo.com/l/?uddg=https%3A%2F%2Fexample.com%2Fx&rut=a",
          "https://example.com/x");
  // Brave's own kinds: base64 in a parameter, and a part of the path.
  Follows("https://a.ouo.today/r?cr=" + Enc("aHR0cHM6Ly9leGFtcGxlLmNvbS8="),
          example);
  Follows("https://y2u.be/dQw4w9WgXcQ",
          "https://www.youtube.com/watch?v=dQw4w9WgXcQ");

  // ---- AMP copies. ----
  Follows("https://www.google.com/amp/s/example.com/article/1?x=1",
          "https://example.com/article/1?x=1");
  Follows("https://example-com.cdn.ampproject.org/c/s/example.com/a",
          "https://example.com/a");
  Follows(
      "https://example-com.cdn.ampproject.org/v/s/example.com/a?amp_js_v=0.1",
      "https://example.com/a?amp_js_v=0.1");

  // ---- The address is kept exactly as it was written in the parameter:
  // decoded once, never twice. ----
  Follows(fb + "https%3A%2F%2Fexample.com%2F%3Fa%3Dhttps%253A%252F%252Fb.com",
          "https://example.com/?a=https%3A%2F%2Fb.com");

  // ---- A redirector that leads to another is followed to the end. ----
  Follows(fb + Enc(goog + Enc("https://example.com/final")),
          "https://example.com/final");
  Follows(fb + "http%3A%2F%2F192.168.1.1%2F", "http://192.168.1.1/");

  // ---- Not a redirector: left alone. ----
  Leaves(example);
  Leaves("https://example.com/?u=https%3A%2F%2Fevil.com%2F");
  Leaves("https://www.google.com/search?q=cats");
  Leaves("https://www.google.com/url?q=cats");
  Leaves("https://l.facebook.com/l.php");
  Leaves("https://l.facebook.com/l.php?u=");
  Leaves("not an address");
  Leaves("");

  // ---- Not web addresses at all. ----
  Leaves("javascript:alert(1)");
  Leaves("file:///C:/Windows/win.ini");
  Leaves("data:text/html,x");
  Leaves("chrome://settings");
  Leaves("ftp://l.facebook.com/l.php?u=https%3A%2F%2Fexample.com%2F");

  // ---- Targets that must never be followed. ----
  Leaves(fb + "javascript%3Aalert(1)");
  Leaves(fb + "JaVaScRiPt%3Aalert(1)");
  Leaves(fb + "java%09script%3Aalert(1)");
  Leaves(fb + "data%3Atext%2Fhtml%2C%3Cscript%3Ealert(1)%3C%2Fscript%3E");
  Leaves(fb + "file%3A%2F%2F%2FC%3A%2FWindows%2Fwin.ini");
  Leaves(fb + "chrome%3A%2F%2Fsettings");
  Leaves(fb + "about%3Ablank");
  Leaves(fb + "blob%3Ahttps%3A%2F%2Fexample.com%2Fx");
  Leaves(fb + "ftp%3A%2F%2Fexample.com%2F");
  Leaves(fb + "view-source%3Ahttps%3A%2F%2Fexample.com%2F");
  Leaves(fb + "%2F%2Fevil.example%2F");
  Leaves(fb + "https%3A%2Fexample.com%2F");
  Leaves(fb + "http%3Aexample.com");
  Leaves(fb + "%2Fpath%2Fonly");
  // A target with something in it that the URL parser would drop or
  // read differently.
  Leaves(fb + "https%3A%2F%2Fexample.com%2F%0D%0Ax");
  Leaves(fb + "https%3A%2F%2Fexample.com%2F%09");
  Leaves(fb + "https%3A%2F%2Fexample.com%2F%00");
  Leaves(fb + "https%3A%2F%2Fexample.com%2F%20x");
  Leaves(fb + "https%3A%2F%2Fexample.com%5C%40evil.example%2F");
  Leaves(fb + "https%3A%2F%2Fuser%3Apass%40example.com%2F");
  Leaves(fb + "https%3A%2F%2Flocalhost%2F");
  Leaves(fb + "https%3A%2F%2F%2F");
  // A parameter given twice is read differently by different servers.
  Leaves(fb + "https%3A%2F%2Fexample.com%2F&u=javascript%3Aalert(1)");
  // base64 that decodes to something bad, or to nothing.
  Leaves("https://a.ouo.today/r?cr=" + Enc("amF2YXNjcmlwdDphbGVydCgxKQ=="));
  Leaves("https://a.ouo.today/r?cr=%21%21%21");
  // Too long.
  Leaves(fb + Enc(example + std::string(9000, 'a')));
  Leaves(fb + Enc(example) + "&x=" + std::string(40000, 'a'));

  // ---- Nested: the bad address at the end of a chain is not followed.
  // What comes out is the redirector just before it, a plain web address
  // that goes through every check as the navigation it is. ----
  {
    const std::string inner_file = fb + Enc("file:///C:/");
    Follows(goog + Enc(inner_file), GURL(inner_file).spec());
    const std::string inner_js = fb + Enc("javascript:alert(1)");
    Follows(goog + Enc(inner_js), GURL(inner_js).spec());
    const std::string inner_data = fb + Enc("data:text/html,x");
    Follows(goog + Enc(inner_data), GURL(inner_data).spec());
  }

  // ---- A chain that runs on and on is not an honest link. ----
  {
    std::string deep = "https://example.com/end";
    for (int i = 0; i < 8; ++i) {
      deep = (i % 2 ? goog : fb) + Enc(deep);
    }
    Leaves(deep);
    std::string shallow = "https://example.com/end";
    for (int i = 0; i < 3; ++i) {
      shallow = (i % 2 ? goog : fb) + Enc(shallow);
    }
    Follows(shallow, "https://example.com/end");
  }

  // ---- Look-alike hosts and paths are not the redirector. ----
  Leaves("https://l.facebook.com.evil.example/l.php?u=https%3A%2F%2Fexample.com%2F");
  Leaves("https://notl.facebook.com/l.php?u=https%3A%2F%2Fexample.com%2F");
  Leaves("https://evil.example/l.facebook.com/l.php?u=https%3A%2F%2Fexample.com%2F");
  Leaves("https://evil.example/?x=https://l.facebook.com/l.php?u=https%3A%2F%2Fexample.com%2F");
  Leaves("https://www.google.com.evil.example/url?q=https%3A%2F%2Fexample.com%2F");
  Leaves("https://cdn.ampproject.org.evil.example/c/s/example.com/a");
  Leaves("https://evil.example/cdn.ampproject.org/c/s/example.com/a");
  Leaves("https://evil.example/amp/s/example.com/a");

  std::cout << (g_checks - g_failures) << " of " << g_checks << " passed\n";
  return g_failures;
}
