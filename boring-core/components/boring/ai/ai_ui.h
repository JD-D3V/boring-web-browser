// Copyright 2026 boring. BSD style license.

#ifndef COMPONENTS_BORING_AI_AI_UI_H_
#define COMPONENTS_BORING_AI_AI_UI_H_

#include "content/public/browser/web_ui_controller.h"
#include "content/public/browser/webui_config.h"

namespace boring {
namespace ai {

// The host name of the settings page: chrome://boring-ai
inline constexpr char kBoringAiHost[] = "boring-ai";

// The page where a person picks which AI service to use, if any, and
// types their own key. Nothing here runs on its own.
class BoringAiUI : public content::WebUIController {
 public:
  explicit BoringAiUI(content::WebUI* web_ui);
  ~BoringAiUI() override;

  BoringAiUI(const BoringAiUI&) = delete;
  BoringAiUI& operator=(const BoringAiUI&) = delete;
};

class BoringAiUIConfig : public content::DefaultWebUIConfig<BoringAiUI> {
 public:
  BoringAiUIConfig();
};

}  // namespace ai
}  // namespace boring

#endif  // COMPONENTS_BORING_AI_AI_UI_H_
