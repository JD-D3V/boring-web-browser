// Copyright 2026 boring. BSD style license.

#include "components/boring/scam/warning_page.h"

#include "base/strings/escape.h"
#include "base/strings/strcat.h"
#include "content/public/browser/web_contents.h"
#include "third_party/skia/include/core/SkColor.h"
#include "ui/color/color_id.h"
#include "ui/color/color_provider.h"
#include "ui/gfx/color_utils.h"

namespace boring {

namespace {

// The page is written directly here, in plain language, with big text.
// It stays calm on purpose, and takes its colours from the window's own
// palette (see ColourVariables).
constexpr char kPageTop[] = R"HTML(<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>%TITLE%</title>
<style>
  %COLOURS%
  * { box-sizing: border-box; }
  body { background: var(--paper); color: var(--ink);
         font: 14px/1.6 "Segoe UI", system-ui, sans-serif;
         margin: 0; display: flex; min-height: 100vh; align-items: center;
         justify-content: center; }
  .warning-page { max-width: 640px; width: 100%; margin: 65px auto;
                  padding: 0 30px 35px; }
  .warning-symbol { display: grid; place-items: center; font-size: 24px;
                    color: var(--warning); background: var(--warning-soft);
                    width: 52px; height: 52px; border-radius: 15px;
                    margin-bottom: 26px; }
  .eyebrow { text-transform: uppercase; letter-spacing: 0.16em;
             font-size: 10px; font-weight: 650; color: var(--warning);
             margin-bottom: 10px; }
  h1 { font-size: 38px; letter-spacing: -0.045em; font-weight: 550;
       line-height: 1.1; margin: 0 0 0.4em; }
  p { color: var(--muted); font-size: 14px; line-height: 1.65;
      margin: 0 0 1em; }
  .host { font-size: 14px; padding: 14px 18px; border: 1px solid var(--line);
          border-radius: 8px; background: var(--chip); color: var(--ink);
          font-weight: 600; overflow-wrap: anywhere; margin: 0 0 1.2em; }
  .actions { display: flex; flex-wrap: wrap; gap: 12px; margin-top: 24px; }
  .primary { min-height: 40px; padding: 10px 18px; border-radius: 7px;
             font-weight: 600; font-size: 13px; border: none;
             cursor: pointer; font-family: inherit;
             background: var(--accent); color: var(--on-accent); }
  .text-button { background: none; border: none; color: var(--accent);
                 font-weight: 600; padding: 8px 0; text-align: left;
                 font-size: 13px; cursor: pointer; font-family: inherit; }
  /* Press and hover: colour and a small scale only, so input never waits. */
  .primary, .text-button {
    transition: background-color 150ms ease-out, color 150ms ease-out,
                border-color 150ms ease-out, transform 150ms ease-out; }
  .primary:active { transform: scale(0.98); }
  .text-button:active { transform: scale(0.98); }
  @media (hover: hover) {
    .primary:hover { background: color-mix(in srgb, var(--accent) 86%, var(--ink)); }
    .text-button:hover { text-decoration: underline; text-underline-offset: 3px; }
  }
  :focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }
  details { margin-top: 28px; font-size: 12px; color: var(--muted); }
  summary { cursor: pointer; }
  .panel-note { font-size: 12px; color: var(--muted); margin-top: 28px; }
  @media (prefers-reduced-motion: reduce) {
    .primary, .text-button { transition: none; }
    .primary:active, .text-button:active { transform: none; }
  }
  @media (max-width: 480px) { .warning-page { padding: 0 22px 22px; } }
  @media (forced-colors: active) {
    button { border: 1px solid ButtonText; }
    .primary { background: Highlight; color: HighlightText; }
  }
</style>
</head>
<body>
<div class="warning-page">
<div class="warning-symbol" aria-hidden="true">!</div>
<div class="eyebrow">%EYEBROW%</div>
<h1>%HEADING%</h1>
)HTML";

constexpr char kPageBottom[] = R"HTML(
<div class="actions">
<button class="primary" onclick="goBack()">%MAIN%</button>
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
</script>
</body>
</html>
)HTML";

constexpr char kContinueTop[] =
    "<details><summary>Why was this blocked?</summary><p>";

constexpr char kContinueBottom[] =
    "</p>"
    "<button type=\"button\" class=\"text-button\" "
    "onclick=\"return proceedAnyway()\">Continue anyway</button></details>";

// The page is not a chrome:// page, so it cannot load the theme's
// colors.css the way the Protection page does. The colours are read from
// the tab's own colour provider when the page is built instead, which is
// the same palette the window is using: Cool, Beige or Green, light or
// dark. Dark is told from the page colour itself, not from a setting, so
// it cannot disagree with what the provider handed back.
std::string ColourVariables(content::WebContents* contents) {
  const ui::ColorProvider& colours = contents->GetColorProvider();
  const SkColor paper = colours.GetColor(ui::kColorDialogBackground);
  const bool dark = color_utils::IsDark(paper);
  const auto rgb = [&colours](ui::ColorId id) {
    return color_utils::SkColorToRgbString(colours.GetColor(id));
  };
  return base::StrCat(
      {":root { color-scheme: ",
       dark ? "dark" : "light",
       ";\n",
       "    --paper: rgb(",
       color_utils::SkColorToRgbString(paper),
       ");\n",
       "    --ink: rgb(",
       rgb(ui::kColorDialogForeground),
       ");\n",
       "    --muted: rgb(",
       rgb(ui::kColorLabelForegroundSecondary),
       ");\n",
       "    --line: rgb(",
       rgb(ui::kColorBubbleBorder),
       ");\n",
       "    --accent: rgb(",
       rgb(ui::kColorSysPrimary),
       ");\n",
       "    --on-accent: rgb(",
       rgb(ui::kColorSysOnPrimary),
       ");\n",
       "    --chip: color-mix(in srgb, var(--ink) 6%, var(--paper));\n",
       "    --warning: ",
       dark ? "#ffb69c" : "#9e3e24",
       ";\n",
       "    --warning-soft: ",
       dark ? "#412f28" : "#fbebe4",
       ";\n",
       "  }"});
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
  ReplaceFirst(top, "%EYEBROW%", base::EscapeForHTML(text.eyebrow));
  ReplaceFirst(top, "%HEADING%", base::EscapeForHTML(text.heading));

  const std::string body = base::StrCat(
      {"<p>", base::EscapeForHTML(text.what), "</p><div class=\"host\">",
       base::EscapeForHTML(text.address), "</div>"});

  std::string bottom(kPageBottom);
  ReplaceFirst(bottom, "%MAIN%", base::EscapeForHTML(text.main_button));
  ReplaceFirst(
      bottom, "%CONTINUE%",
      may_continue
          ? base::StrCat(
                {kContinueTop, base::EscapeForHTML(text.why), kContinueBottom})
          : base::StrCat({"<p class=\"panel-note\">",
                          base::EscapeForHTML(text.no_bypass), "</p>"}));
  return base::StrCat({top, body, bottom});
}

}  // namespace boring
