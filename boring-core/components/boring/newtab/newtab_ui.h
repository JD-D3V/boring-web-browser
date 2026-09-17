// Copyright 2026 boring. BSD style license.

#ifndef COMPONENTS_BORING_NEWTAB_NEWTAB_UI_H_
#define COMPONENTS_BORING_NEWTAB_NEWTAB_UI_H_

#include "content/public/browser/web_ui_controller.h"
#include "content/public/browser/webui_config.h"

namespace user_prefs {
class PrefRegistrySyncable;
}

namespace boring {

// The host name of the page: chrome://boring-newtab
inline constexpr char kBoringNewTabHost[] = "boring-newtab";
inline constexpr char kBoringNewTabUrl[] = "chrome://boring-newtab";

// The shortcuts a person pinned to the new tab page, as a list of
// {title, url} dictionaries. Kept on this device.
inline constexpr char kNewTabShortcutsPref[] = "boring.newtab.shortcuts";

void RegisterNewTabPrefs(user_prefs::PrefRegistrySyncable* registry);

// A quiet new tab page: the shortcuts the person chose and one line
// saying whether protection is working. Nothing on it is fetched from
// the internet, so opening a tab never tells anyone anything.
class BoringNewTabUI : public content::WebUIController {
 public:
  explicit BoringNewTabUI(content::WebUI* web_ui);
  ~BoringNewTabUI() override;

  BoringNewTabUI(const BoringNewTabUI&) = delete;
  BoringNewTabUI& operator=(const BoringNewTabUI&) = delete;
};

class BoringNewTabUIConfig
    : public content::DefaultWebUIConfig<BoringNewTabUI> {
 public:
  BoringNewTabUIConfig();
};

}  // namespace boring

#endif  // COMPONENTS_BORING_NEWTAB_NEWTAB_UI_H_
