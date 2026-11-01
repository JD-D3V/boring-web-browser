// Copyright 2026 boring. BSD style license.

#include "components/boring/guards/guards_policy.h"

#include "components/boring/core/boring_prefs.h"
#include "components/prefs/pref_service.h"
#include "components/user_prefs/user_prefs.h"
#include "content/public/browser/browser_context.h"

namespace boring {
namespace guards {

bool IsEnabled(content::BrowserContext* context) {
  if (!context) {
    return true;
  }
  PrefService* prefs = user_prefs::UserPrefs::Get(context);
  return !prefs || prefs->GetBoolean(prefs::kWarnScamTricks);
}

}  // namespace guards
}  // namespace boring
