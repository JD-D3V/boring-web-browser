// Copyright 2026 boring. BSD style license.

#ifndef COMPONENTS_BORING_PROTECTION_SITE_RULES_HANDLER_H_
#define COMPONENTS_BORING_PROTECTION_SITE_RULES_HANDLER_H_

#include "base/values.h"
#include "content/public/browser/web_ui_message_handler.h"

namespace boring {

// Answers the three rows we add to Chromium's own site details page
// (chrome://settings/content/siteDetails?site=...): blocking and never
// sleep, which are our prefs. Clear on close is Chromium's own cookie
// setting and goes through Chromium's own site settings handler, so it
// is not here. The page asks with an origin; the handler works out the
// key each pref uses (see GetBlockingSite() and GetNeverSleepKey()), so
// the page never has to know it.
//
//   boringGetSiteRules(origin) -> {site, blockingOff, neverSleep}
//       `site` is empty when the origin is not a web page, and then the
//       page hides the rows.
//   boringSetSiteRule(origin, "blocking" | "neverSleep", on)
class SiteRulesHandler : public content::WebUIMessageHandler {
 public:
  SiteRulesHandler();
  ~SiteRulesHandler() override;

  SiteRulesHandler(const SiteRulesHandler&) = delete;
  SiteRulesHandler& operator=(const SiteRulesHandler&) = delete;

  // content::WebUIMessageHandler:
  void RegisterMessages() override;

 private:
  void HandleGet(const base::ListValue& args);
  void HandleSet(const base::ListValue& args);
};

}  // namespace boring

#endif  // COMPONENTS_BORING_PROTECTION_SITE_RULES_HANDLER_H_
