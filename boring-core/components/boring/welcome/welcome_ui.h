// Copyright 2026 boring. BSD style license.

#ifndef COMPONENTS_BORING_WELCOME_WELCOME_UI_H_
#define COMPONENTS_BORING_WELCOME_WELCOME_UI_H_

#include "content/public/browser/web_ui_controller.h"
#include "content/public/browser/webui_config.h"

namespace boring {

// The host name of the page: chrome://boring-welcome
inline constexpr char kBoringWelcomeHost[] = "boring-welcome";
inline constexpr char kBoringWelcomeUrl[] = "chrome://boring-welcome";

// Shown the first time the browser opens: import, default browser, and
// Senior Safe Mode for someone setting it up for another person.
class BoringWelcomeUI : public content::WebUIController {
 public:
  explicit BoringWelcomeUI(content::WebUI* web_ui);
  ~BoringWelcomeUI() override;

  BoringWelcomeUI(const BoringWelcomeUI&) = delete;
  BoringWelcomeUI& operator=(const BoringWelcomeUI&) = delete;
};

class BoringWelcomeUIConfig
    : public content::DefaultWebUIConfig<BoringWelcomeUI> {
 public:
  BoringWelcomeUIConfig();
};

}  // namespace boring

#endif  // COMPONENTS_BORING_WELCOME_WELCOME_UI_H_
