// Copyright 2026 boring. BSD style license.

#ifndef COMPONENTS_BORING_WEBSTORE_BUNDLED_WEB_STORE_H_
#define COMPONENTS_BORING_WEBSTORE_BUNDLED_WEB_STORE_H_

#include <string>

namespace base {
class Version;
}

namespace content {
class BrowserContext;
}

namespace user_prefs {
class PrefRegistrySyncable;
}

// Chromium Web Store (NeverDecaf, MIT) ships beside chrome.dll in
// boring\chromium-web-store, without its update_url, so only a browser
// release changes it. It is installed into each profile once, as an
// ordinary extension the person can turn off or remove from
// chrome://extensions, and it stays removed once removed.
namespace boring::webstore {

namespace prefs {

// The bundled version this profile was last given, or "own" when the
// person already had a copy of their own. Empty until then. Set and the
// extension missing means the person removed it.
inline constexpr char kBundledVersion[] = "boring.webstore.bundled_version";

}  // namespace prefs

inline constexpr char kOwnCopy[] = "own";

void RegisterProfilePrefs(user_prefs::PrefRegistrySyncable* registry);

// Called once per profile when its extensions have loaded. Installs or
// updates the bundled copy when that is what the profile needs, off the
// UI thread, and otherwise does nothing.
void MaybeInstallBundledWebStore(content::BrowserContext* context);

enum class Action {
  kNothing,
  kInstall,
  kRecordOwnCopy,
  kRecordBundled,
};

// The decision, kept apart from the browser so it can be read and
// tested on its own. `installed` is null when the extension is not
// installed; `installed_by_us` says whether that copy is ours.
Action Decide(const std::string& recorded,
              const base::Version* installed,
              bool installed_by_us,
              const base::Version& bundled);

}  // namespace boring::webstore

#endif  // COMPONENTS_BORING_WEBSTORE_BUNDLED_WEB_STORE_H_
