// Copyright 2026 boring. BSD style license.

#ifndef COMPONENTS_BORING_GUARDS_GUARDS_POLICY_H_
#define COMPONENTS_BORING_GUARDS_GUARDS_POLICY_H_

namespace content {
class BrowserContext;
}

namespace boring {
namespace guards {

// True when "Warn about scam tricks" is on for the profile
// (boring.protection.warn_scam_tricks, on by default). True with no
// context or no prefs: the safe answer is the protected one.
bool IsEnabled(content::BrowserContext* context);

}  // namespace guards
}  // namespace boring

#endif  // COMPONENTS_BORING_GUARDS_GUARDS_POLICY_H_
