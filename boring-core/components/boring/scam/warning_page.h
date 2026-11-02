// Copyright 2026 boring. BSD style license.

#ifndef COMPONENTS_BORING_SCAM_WARNING_PAGE_H_
#define COMPONENTS_BORING_SCAM_WARNING_PAGE_H_

#include <string>

namespace content {
class WebContents;
}

namespace boring {

// The words on one warning page. Plain text: the page escapes it. Keep it
// short and calm: what happened, what to do, and one main button.
struct WarningText {
  std::string title;        // the tab title
  std::string eyebrow;      // the small label over the heading
  std::string heading;      // what this is, in one line
  std::string what;         // what happened
  std::string address;      // the address, shown in a box
  std::string main_button;  // the safe way out
  std::string why;          // the details: why this was blocked
  std::string no_bypass;    // shown instead of "Continue anyway" when it is off
};

// The full page for any kind of warning, so every warning looks and reads
// the same. The colours come from the browser's own theme for this tab
// (light or dark, and the colour choice, Green included) and are written
// into the page, because a page from a web address cannot read them from
// the browser. "Continue anyway" is left out when `may_continue` is false.
//
// The buttons call the interstitial controller: the main button is
// CMD_DONT_PROCEED and "Continue anyway" is CMD_PROCEED.
std::string BuildWarningPage(content::WebContents* web_contents,
                             const WarningText& text,
                             bool may_continue);

}  // namespace boring

#endif  // COMPONENTS_BORING_SCAM_WARNING_PAGE_H_
