// Copyright 2026 boring. BSD style license.

#include "components/boring/adblock/blocking_off_sites.h"

#include <memory>
#include <utility>
#include <vector>

#include "base/supports_user_data.h"
#include "base/values.h"
#include "components/boring/core/boring_prefs.h"
#include "components/prefs/pref_service.h"
#include "components/user_prefs/user_prefs.h"
#include "content/public/browser/browser_context.h"
#include "url/gurl.h"

namespace boring {

namespace {

const char kUserDataKey[] = "boring_blocking_off_sites";

// Keeps one copy per profile, so every check for that profile sees the
// same one. Holds nothing but the copy: no pointer to the prefs, and no
// pref observer, because user data can outlive a profile's PrefService
// at shutdown.
struct Holder : public base::SupportsUserData::Data {
  scoped_refptr<BlockingOffSites> sites =
      base::MakeRefCounted<BlockingOffSites>();
};

}  // namespace

// static
scoped_refptr<BlockingOffSites> BlockingOffSites::ForContext(
    content::BrowserContext* context) {
  auto* holder = static_cast<Holder*>(context->GetUserData(kUserDataKey));
  if (!holder) {
    auto owned = std::make_unique<Holder>();
    holder = owned.get();
    context->SetUserData(kUserDataKey, std::move(owned));
  }
  // Read the pref fresh every time. This runs for every navigation, a
  // reload included, so the copy is current before the page's own
  // requests are checked, and a change from the shield or the
  // Protection page is picked up by the reload that follows it.
  std::vector<std::string> sites;
  if (const PrefService* prefs = user_prefs::UserPrefs::Get(context)) {
    for (const base::Value& site : prefs->GetList(prefs::kBlockingOffSites)) {
      if (site.is_string()) {
        sites.push_back(site.GetString());
      }
    }
  }
  holder->sites->Set(base::flat_set<std::string>(std::move(sites)));
  return holder->sites;
}

BlockingOffSites::BlockingOffSites() = default;
BlockingOffSites::~BlockingOffSites() = default;

bool BlockingOffSites::IsOff(const GURL& top_frame_url) const {
  const std::string site = GetBlockingSite(top_frame_url);
  if (site.empty()) {
    return false;
  }
  base::AutoLock lock(lock_);
  return sites_.contains(site);
}

void BlockingOffSites::Set(base::flat_set<std::string> sites) {
  base::AutoLock lock(lock_);
  sites_ = std::move(sites);
}

}  // namespace boring
