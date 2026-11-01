// Copyright 2026 boring. BSD style license.

#include "components/boring/protection/site_rules_handler.h"

#include <string>

#include "base/functional/bind.h"
#include "base/values.h"
#include "components/boring/adblock/blocking_off_sites.h"
#include "components/boring/core/boring_prefs.h"
#include "components/boring/performance/never_sleep_sites.h"
#include "components/prefs/pref_service.h"
#include "components/user_prefs/user_prefs.h"
#include "content/public/browser/browser_context.h"
#include "content/public/browser/web_contents.h"
#include "content/public/browser/web_ui.h"
#include "url/gurl.h"

namespace boring {

namespace {

constexpr char kGetMessage[] = "boringGetSiteRules";
constexpr char kSetMessage[] = "boringSetSiteRule";

}  // namespace

SiteRulesHandler::SiteRulesHandler() = default;
SiteRulesHandler::~SiteRulesHandler() = default;

void SiteRulesHandler::RegisterMessages() {
  web_ui()->RegisterMessageCallback(
      kGetMessage, base::BindRepeating(&SiteRulesHandler::HandleGet,
                                       base::Unretained(this)));
  web_ui()->RegisterMessageCallback(
      kSetMessage, base::BindRepeating(&SiteRulesHandler::HandleSet,
                                       base::Unretained(this)));
}

// [callback id, origin]
void SiteRulesHandler::HandleGet(const base::ListValue& args) {
  if (args.size() != 2 || !args[1].is_string()) {
    return;
  }
  AllowJavascript();
  content::BrowserContext* context =
      web_ui()->GetWebContents()->GetBrowserContext();
  const GURL url(args[1].GetString());
  base::DictValue out;
  out.Set("site", GetBlockingSite(url));
  out.Set("blockingOff",
          IsBlockingOffForSite(user_prefs::UserPrefs::Get(context), url));
  out.Set("neverSleep", performance::IsNeverSleep(context, url));
  ResolveJavascriptCallback(args[0], out);
}

// [origin, "blocking" | "neverSleep", on]
void SiteRulesHandler::HandleSet(const base::ListValue& args) {
  if (args.size() != 3 || !args[0].is_string() || !args[1].is_string() ||
      !args[2].is_bool()) {
    return;
  }
  content::BrowserContext* context =
      web_ui()->GetWebContents()->GetBrowserContext();
  const GURL url(args[0].GetString());
  const std::string& rule = args[1].GetString();
  const bool on = args[2].GetBool();
  if (rule == "blocking") {
    SetBlockingOffForSite(user_prefs::UserPrefs::Get(context),
                          GetBlockingSite(url), !on);
    // Bring the copy the renderer checks read up to date now, the way the
    // shield's panel does, rather than at the next page's first request.
    BlockingOffSites::ForContext(context);
  } else if (rule == "neverSleep") {
    performance::SetNeverSleep(context, url, on);
  }
}

}  // namespace boring
