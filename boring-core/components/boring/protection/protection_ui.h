// Copyright 2026 boring. BSD style license.

#ifndef COMPONENTS_BORING_PROTECTION_PROTECTION_UI_H_
#define COMPONENTS_BORING_PROTECTION_PROTECTION_UI_H_

#include "content/public/browser/web_ui_controller.h"
#include "content/public/browser/webui_config.h"

namespace boring {

// The host name of the page: chrome://boring-protection
inline constexpr char kBoringProtectionHost[] = "boring-protection";

// Shows whether scam and ad blocking are really working right now, and
// holds the switches for Senior Safe Mode and sponsored search results.
// A failure is shown as a failure. The page never claims protection that
// is not there.
class BoringProtectionUI : public content::WebUIController {
 public:
  explicit BoringProtectionUI(content::WebUI* web_ui);
  ~BoringProtectionUI() override;

  BoringProtectionUI(const BoringProtectionUI&) = delete;
  BoringProtectionUI& operator=(const BoringProtectionUI&) = delete;
};

class BoringProtectionUIConfig
    : public content::DefaultWebUIConfig<BoringProtectionUI> {
 public:
  BoringProtectionUIConfig();
};

}  // namespace boring

#endif  // COMPONENTS_BORING_PROTECTION_PROTECTION_UI_H_
