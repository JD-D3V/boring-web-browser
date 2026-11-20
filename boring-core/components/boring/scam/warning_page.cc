// Copyright 2026 boring. BSD style license.

#include "components/boring/scam/warning_page.h"

#include "base/strings/escape.h"
#include "base/strings/strcat.h"
#include "base/strings/stringprintf.h"
#include "chrome/browser/ui/color/chrome_color_id.h"
#include "content/public/browser/web_contents.h"
#include "third_party/skia/include/core/SkColor.h"
#include "ui/color/color_id.h"
#include "ui/color/color_provider.h"
#include "ui/gfx/color_utils.h"

namespace boring {

namespace {

// The page is written directly here, in plain language. It stays calm on
// purpose: it says the computer is fine and nobody needs to be called.
// Its colours are the TOKENS rows of the compiled design (see
// ColourVariables).
constexpr char kPageTop[] = R"HTML(<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>%TITLE%</title>
<style>
  %COLOURS%
  * { box-sizing: border-box; }
  [hidden] { display: none !important; }
  body { background: var(--page); color: var(--ink);
         font: 14px/1.5 system-ui, "Segoe UI", sans-serif;
         margin: 0; display: flex; min-height: 100vh; align-items: center;
         justify-content: center; }
  .warning-page { width: 520px; max-width: calc(100% - 32px); margin: 40px 0;
                  display: flex; flex-direction: column; gap: 20px;
                  padding: 32px; border-radius: 12px;
                  background: var(--surface);
                  box-shadow: 0 0 0 1px var(--line), 0 1px 2px var(--shadow); }
  .warning-symbol { width: 44px; height: 44px; display: grid;
                    place-items: center; border-radius: 10px;
                    color: var(--bad); background: var(--bad-tint); }
  .words { display: flex; flex-direction: column; gap: 8px; }
  h1 { margin: 0; font-size: 24px; font-weight: 600;
       letter-spacing: -0.015em; line-height: 1.25; }
  p { margin: 0; }
  .host { font-weight: 600; overflow-wrap: anywhere; }
  .host-box { padding: 10px 14px; border-radius: 8px; background: var(--field);
              box-shadow: inset 0 0 0 1px var(--line); }
  .calm, .why, .panel-note { color: var(--ink2); }
  .why { display: flex; flex-direction: column; align-items: flex-start;
         gap: 12px; }
  .why .link { font-size: 13px; }
  .actions { display: flex; flex-wrap: wrap; align-items: center; gap: 12px; }
  button { font: inherit; color: inherit; border: 0; background: none;
           padding: 0; cursor: pointer; }
  .primary, .secondary { height: 40px; display: flex; align-items: center;
                         border-radius: 8px;
                         transition: transform 150ms ease-out; }
  .primary { padding: 0 20px; font-weight: 600; color: var(--solid-ink);
             background: var(--solid); }
  .secondary { padding: 0 16px; font-weight: 500;
               box-shadow: inset 0 0 0 1px var(--edge); }
  .primary:active, .secondary:active { transform: scale(0.98); }
  .footer { padding-top: 16px; display: flex; justify-content: space-between;
            gap: 16px; font-size: 13px; color: var(--ink2);
            box-shadow: inset 0 1px 0 var(--line); }
  .link { text-decoration: underline; text-underline-offset: 3px; }
  @media (hover: hover) { .link:hover { color: var(--ink); } }
  :focus-visible { outline: 2px solid var(--ink); outline-offset: 2px; }
  @media (prefers-reduced-motion: reduce) {
    .primary, .secondary { transition: none; }
    .primary:active, .secondary:active { transform: none; }
  }
  @media (max-width: 480px) { .warning-page { padding: 24px; } }
  @media (forced-colors: active) {
    button { border: 1px solid ButtonText; }
    .primary { background: Highlight; color: HighlightText; }
  }
</style>
</head>
<body>
<div class="warning-page">
<div class="warning-symbol" aria-hidden="true"><svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 3l7.5 2.8v5.7c0 4.3-3 7.7-7.5 9-4.5-1.3-7.5-4.7-7.5-9V5.8zM12 8v4.5M12 15.6v.01"></path></svg></div>
<div class="words">
<h1>%HEADING%</h1>
)HTML";

constexpr char kPageBottom[] = R"HTML(
<p class="calm">%CALM%</p>
</div>
<div class="actions">
<button class="primary" onclick="goBack()">%MAIN%</button>
%WHY_BUTTON%
</div>
%CONTINUE%
</div>
<script>
function goBack() {
  if (window.certificateErrorPageController) {
    certificateErrorPageController.dontProceed();
  } else {
    history.back();
  }
}
function proceedAnyway() {
  if (window.certificateErrorPageController) {
    certificateErrorPageController.proceed();
  }
  return false;
}
function reportMistake() {
  if (window.certificateErrorPageController) {
    certificateErrorPageController.openHelpCenter();
  }
}
function toggleWhy(button) {
  var why = document.getElementById('why');
  why.hidden = !why.hidden;
  button.setAttribute('aria-expanded', why.hidden ? 'false' : 'true');
}
</script>
</body>
</html>
)HTML";

constexpr char kWhyButton[] =
    "<button type=\"button\" class=\"secondary\" aria-expanded=\"false\" "
    "aria-controls=\"why\" onclick=\"toggleWhy(this)\">Why was this "
    "blocked</button>";

// "Continue anyway" sits inside the closed "Why was this blocked" part, so
// getting past a warning takes two presses. While the part is closed it is
// display: none, so it can be neither seen nor reached with Tab.
constexpr char kContinueTop[] = "<div class=\"why\" id=\"why\" hidden><p>";

constexpr char kContinueBottom[] =
    "</p><button type=\"button\" class=\"link\" id=\"continue\" "
    "onclick=\"return proceedAnyway()\">Continue anyway, not advised</button>"
    "</div>";

// On every warning, whether or not there is a way past.
constexpr char kReportButton[] =
    "<button type=\"button\" class=\"link\" id=\"report\" "
    "onclick=\"reportMistake()\">Report a mistake</button>";

// Where a text names the site: the address goes there, in bold.
constexpr char kHostMarker[] = "%HOST%";

std::string Hex(SkColor colour) {
  return base::StringPrintf("#%02x%02x%02x", SkColorGetR(colour),
                            SkColorGetG(colour), SkColorGetB(colour));
}

// The page is not a chrome:// page, so it cannot load the theme's
// colors.css. Its surfaces, lines and text are read from the tab's own
// colour provider, the same ids the new tab page reads, so they follow
// the Look; they are numbers written as #rrggbb, never page text. Light
// or dark is told from the dialog background, so it cannot disagree with
// the window; the warning colours and the solid button are the design's
// TOKENS rows.
std::string ColourVariables(content::WebContents* contents) {
  const ui::ColorProvider& provider = contents->GetColorProvider();
  const bool dark =
      color_utils::IsDark(provider.GetColor(ui::kColorDialogBackground));
  const std::string looks = base::StrCat(
      {"    --page: ", Hex(provider.GetColor(kColorNewTabPageBackground)),
       "; --surface: ", Hex(provider.GetColor(kColorToolbar)),
       "; --field: ", Hex(provider.GetColor(kColorLocationBarBackground)),
       ";\n    --line: ", Hex(provider.GetColor(kColorToolbarSeparator)),
       "; --edge: ", Hex(provider.GetColor(kColorBoringEdge)),
       "; --ink: ", Hex(provider.GetColor(kColorToolbarText)),
       ";\n    --ink2: ",
       Hex(provider.GetColor(kColorToolbarButtonIconInactive)), ";\n"});
  return dark ? base::StrCat({":root { color-scheme: dark;\n", looks,
                              "    --bad: #ff9a8f; --bad-tint: #3b1c1a;\n"
                              "    --solid: #e8e9ed; --solid-ink: #14151a;\n"
                              "    --shadow: rgba(0,0,0,0.55); }"})
              : base::StrCat({":root { color-scheme: light;\n", looks,
                              "    --bad: #a3271c; --bad-tint: #fbe6e3;\n"
                              "    --solid: #1a1c22; --solid-ink: #ffffff;\n"
                              "    --shadow: rgba(16,24,40,0.16); }"});
}

void ReplaceFirst(std::string& text,
                  const std::string& marker,
                  const std::string& with) {
  const size_t pos = text.find(marker);
  if (pos != std::string::npos) {
    text.replace(pos, marker.size(), with);
  }
}

}  // namespace

std::string BuildWarningPage(content::WebContents* web_contents,
                             const WarningText& text,
                             bool may_continue) {
  std::string top(kPageTop);
  ReplaceFirst(top, "%COLOURS%", ColourVariables(web_contents));
  ReplaceFirst(top, "%TITLE%", base::EscapeForHTML(text.title));
  ReplaceFirst(top, "%HEADING%", base::EscapeForHTML(text.heading));

  // Everything is escaped first; the marker survives escaping, so the
  // address (escaped too) can only ever land where the text put it.
  const std::string address = base::EscapeForHTML(text.address);
  std::string what = base::EscapeForHTML(text.what);
  std::string body;
  if (what.find(kHostMarker) != std::string::npos) {
    ReplaceFirst(what, kHostMarker,
                 base::StrCat({"<span class=\"host\">", address, "</span>"}));
    body = base::StrCat({"<p>", what, "</p>"});
  } else {
    body = base::StrCat({"<p>", what, "</p><p class=\"host host-box\">",
                         address, "</p>"});
  }

  std::string bottom(kPageBottom);
  ReplaceFirst(bottom, "%CALM%", base::EscapeForHTML(text.calm));
  ReplaceFirst(bottom, "%MAIN%", base::EscapeForHTML(text.main_button));
  ReplaceFirst(bottom, "%WHY_BUTTON%", may_continue ? kWhyButton : "");
  ReplaceFirst(
      bottom, "%CONTINUE%",
      may_continue
          ? base::StrCat({kContinueTop, base::EscapeForHTML(text.why),
                          kContinueBottom, "<div class=\"footer\">",
                          kReportButton, "</div>"})
          : base::StrCat({"<div class=\"footer\"><p class=\"panel-note\">",
                          base::EscapeForHTML(text.no_bypass), "</p>",
                          kReportButton, "</div>"}));
  return base::StrCat({top, body, bottom});
}

}  // namespace boring
