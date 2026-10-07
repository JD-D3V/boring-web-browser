// Copyright 2026 boring. BSD style license.

#ifndef CHROME_BROWSER_UI_VIEWS_TOOLBAR_BORING_ASSIST_BUTTON_H_
#define CHROME_BROWSER_UI_VIEWS_TOOLBAR_BORING_ASSIST_BUTTON_H_

#include "base/callback_list.h"
#include "base/memory/raw_ptr.h"
#include "chrome/browser/ui/views/toolbar/toolbar_button.h"
#include "content/public/browser/web_contents_observer.h"
#include "ui/base/metadata/metadata_header_macros.h"

class BrowserWindowInterface;

// Opens the Ask Gemini panel for the current page. The button shows itself
// only where the panel can work, so it is not a dead control on incognito,
// guest or settings pages.
class BoringAssistButton : public ToolbarButton,
                           public content::WebContentsObserver {
  METADATA_HEADER(BoringAssistButton, ToolbarButton)

 public:
  explicit BoringAssistButton(BrowserWindowInterface* browser);

  BoringAssistButton(const BoringAssistButton&) = delete;
  BoringAssistButton& operator=(const BoringAssistButton&) = delete;

  ~BoringAssistButton() override;

  // content::WebContentsObserver:
  // A new page can change the answer (a web page becoming a settings page),
  // so the button is checked again on every page change.
  void PrimaryPageChanged(content::Page& page) override;

 private:
  // Points us at whichever tab the window is showing now.
  void FollowActiveTab();

  // Shows the button only while the active tab qualifies for the panel.
  void ShowIfAssistable();

  void OnPressed();

  const raw_ptr<BrowserWindowInterface> browser_;
  base::CallbackListSubscription tab_changed_;
};

#endif  // CHROME_BROWSER_UI_VIEWS_TOOLBAR_BORING_ASSIST_BUTTON_H_
