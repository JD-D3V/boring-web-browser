// Copyright 2026 boring. BSD style license.

#ifndef CHROME_BROWSER_AUTOCOMPLETE_BORING_BAR_PROVIDER_H_
#define CHROME_BROWSER_AUTOCOMPLETE_BORING_BAR_PROVIDER_H_

#include <string>
#include <vector>

#include "base/memory/raw_ptr.h"
#include "components/omnibox/browser/autocomplete_provider.h"

class AutocompleteInput;
class AutocompleteProviderClient;
class Profile;

// The Bar's own rows (design/v12-compiled, screen C06): things to do under
// "Do", the profile's other open tabs under "Open tabs" and Settings pages
// under "Settings". Worked out on the machine from two fixed tables and the
// open tabs; it makes no network request and is done when Start returns.
class BoringBarProvider : public AutocompleteProvider {
 public:
  // The additional info keys a row carries: the Do row's id (read by
  // chrome/browser/ui/omnibox/boring_bar_run.cc) and the row's glyph (read
  // by the results page's handler). Both are values from our own tables,
  // never page text.
  static constexpr char kDoKey[] = "boring.do";
  static constexpr char kIconKey[] = "boring.icon";

  BoringBarProvider(AutocompleteProviderClient* client, Profile* profile);
  BoringBarProvider(const BoringBarProvider&) = delete;
  BoringBarProvider& operator=(const BoringBarProvider&) = delete;

  void Start(const AutocompleteInput& input, bool minimal_changes) override;

 private:
  ~BoringBarProvider() override;

  void AddDoRows(const std::vector<std::u16string>& words);
  void AddSettingsRows(const std::vector<std::u16string>& words);
  void AddOpenTabRows(const AutocompleteInput& input,
                      const std::vector<std::u16string>& words);

  raw_ptr<AutocompleteProviderClient> client_;
  raw_ptr<Profile> profile_;
};

#endif  // CHROME_BROWSER_AUTOCOMPLETE_BORING_BAR_PROVIDER_H_
