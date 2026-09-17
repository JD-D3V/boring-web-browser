// Copyright 2026 boring. BSD style license.

#ifndef CHROME_BROWSER_UI_VIEWS_TOOLBAR_BORING_PROTECTION_BUTTON_H_
#define CHROME_BROWSER_UI_VIEWS_TOOLBAR_BORING_PROTECTION_BUTTON_H_

#include "base/memory/raw_ptr.h"
#include "base/timer/timer.h"
#include "chrome/browser/ui/views/toolbar/toolbar_button.h"
#include "ui/base/metadata/metadata_header_macros.h"

class BrowserWindowInterface;

// The shield in the toolbar. It says whether scam and ad blocking are
// really running, without being asked, and grows a "Needs attention"
// label when a list did not load. Pressing it opens the Protection page,
// which explains the same state in full.
class BoringProtectionButton : public ToolbarButton {
  METADATA_HEADER(BoringProtectionButton, ToolbarButton)

 public:
  explicit BoringProtectionButton(BrowserWindowInterface* browser);

  BoringProtectionButton(const BoringProtectionButton&) = delete;
  BoringProtectionButton& operator=(const BoringProtectionButton&) = delete;

  ~BoringProtectionButton() override;

  // ToolbarButton:
  void OnThemeChanged() override;

 private:
  // What the shield is currently saying.
  enum class State {
    kWorking,  // both lists loaded, everything is being blocked
    kLoading,  // at least one list has not finished, nothing to report yet
    kFailed,   // a list is missing, so something is not being blocked
  };

  // Reads the two services and paints what it finds. While a list is
  // still loading it asks again shortly and stops once there is an
  // answer, because neither service has anything to subscribe to.
  void UpdateState();

  State ReadState() const;
  void OnPressed();

  const raw_ptr<BrowserWindowInterface> browser_;
  State state_ = State::kLoading;
  base::OneShotTimer while_loading_;
};

#endif  // CHROME_BROWSER_UI_VIEWS_TOOLBAR_BORING_PROTECTION_BUTTON_H_
