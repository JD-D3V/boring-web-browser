// Copyright 2026 boring. BSD style license.

#include "components/boring/scam/takeover/takeover_policy.h"

#include "components/boring/core/boring_prefs.h"
#include "components/prefs/pref_service.h"
#include "components/user_prefs/user_prefs.h"
#include "content/public/browser/browser_context.h"
#include "content/public/browser/web_contents.h"

namespace boring {

bool IsStopTakeoversEnabled(content::WebContents* web_contents) {
  if (!web_contents) {
    return true;
  }
  PrefService* prefs =
      user_prefs::UserPrefs::Get(web_contents->GetBrowserContext());
  return !prefs || prefs->GetBoolean(prefs::kStopTakeovers);
}

bool ShouldEscAlwaysExit(content::WebContents* web_contents) {
  return IsStopTakeoversEnabled(web_contents);
}

}  // namespace boring
