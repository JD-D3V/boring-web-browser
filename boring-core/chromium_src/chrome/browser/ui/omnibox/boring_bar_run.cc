// Copyright 2026 boring. BSD style license.

#include "chrome/browser/ui/omnibox/boring_bar_run.h"

#include <string>
#include <string_view>

#include "chrome/app/chrome_command_ids.h"
#include "chrome/browser/autocomplete/boring_bar_provider.h"
#include "chrome/browser/themes/theme_service.h"
#include "chrome/browser/themes/theme_service_factory.h"
#include "chrome/browser/ui/browser_commands.h"
#include "chrome/browser/ui/browser_window/public/browser_window_interface.h"
#include "chrome/browser/ui/omnibox/chrome_omnibox_client.h"
#include "components/omnibox/browser/autocomplete_match.h"
#include "components/omnibox/browser/autocomplete_provider.h"
#include "components/omnibox/browser/omnibox_client.h"

namespace {

// The Do table's ids and the menu commands they run. Kept in step with
// kDoRows in boring_bar_provider.cc by tools/tests/test_bar_tables.py.
struct DoCommand {
  std::string_view id;
  int command;
};

constexpr DoCommand kDoCommands[] = {
    {"newtab", IDC_NEW_TAB},
    {"newwindow", IDC_NEW_WINDOW},
    {"incognito", IDC_NEW_INCOGNITO_WINDOW},
    {"history", IDC_SHOW_HISTORY},
    {"downloads", IDC_SHOW_DOWNLOADS},
    {"print", IDC_PRINT},
    {"find", IDC_FIND},
    {"zoomin", IDC_ZOOM_PLUS},
    {"zoomout", IDC_ZOOM_MINUS},
    {"zoomreset", IDC_ZOOM_NORMAL},
    // Both open something that asks before anything is deleted.
    {"delete", IDC_CLEAR_BROWSING_DATA},
    {"forget", IDC_BORING_FORGET_SESSION},
};

std::string DoId(const AutocompleteMatch& match) {
  return match.GetAdditionalInfoForDebugging(BoringBarProvider::kDoKey);
}

}  // namespace

bool BoringBarIsDoRow(const AutocompleteMatch& match) {
  return match.provider &&
         match.provider->type() == AutocompleteProvider::Type::kBoringBar &&
         !DoId(match).empty();
}

void BoringBarRunRow(OmniboxClient* client, const AutocompleteMatch& match) {
  if (!client || !client->IsChromeOmniboxClient() || !BoringBarIsDoRow(match)) {
    return;
  }
  BrowserWindowInterface* browser =
      static_cast<ChromeOmniboxClient*>(client)->browser();
  if (!browser) {
    return;
  }
  const std::string id = DoId(match);
  if (id == "dark" || id == "light") {
    ThemeServiceFactory::GetForProfile(browser->GetProfile())
        ->SetBrowserColorScheme(id == "dark"
                                    ? ThemeService::BrowserColorScheme::kDark
                                    : ThemeService::BrowserColorScheme::kLight);
    return;
  }
  for (const DoCommand& row : kDoCommands) {
    if (row.id == id) {
      // The same path as the menu: a command that is off in this window
      // (Incognito in a guest window, say) does nothing.
      chrome::ExecuteCommand(browser, row.command);
      return;
    }
  }
}
