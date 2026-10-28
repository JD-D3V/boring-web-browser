// Copyright 2026 boring. BSD style license.

#ifndef COMPONENTS_BORING_SCAM_TAKEOVER_TAKEOVER_UI_H_
#define COMPONENTS_BORING_SCAM_TAKEOVER_TAKEOVER_UI_H_

#include "content/public/browser/web_ui_controller.h"
#include "content/public/browser/webui_config.h"

namespace boring {

// The Get me out page, chrome://boring-takeover. Shown in place of a page
// that was locking the browser. It says the computer is fine, and has one
// big button that closes the tab. Only the browser can show it, so the
// page it replaced cannot draw over it or hold the tab open.
class BoringTakeoverUI : public content::WebUIController {
 public:
  explicit BoringTakeoverUI(content::WebUI* web_ui);
  ~BoringTakeoverUI() override;

  BoringTakeoverUI(const BoringTakeoverUI&) = delete;
  BoringTakeoverUI& operator=(const BoringTakeoverUI&) = delete;
};

class BoringTakeoverUIConfig
    : public content::DefaultWebUIConfig<BoringTakeoverUI> {
 public:
  BoringTakeoverUIConfig();
};

}  // namespace boring

#endif  // COMPONENTS_BORING_SCAM_TAKEOVER_TAKEOVER_UI_H_
