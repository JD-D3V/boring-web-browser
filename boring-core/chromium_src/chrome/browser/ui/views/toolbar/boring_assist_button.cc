// Copyright 2026 boring. BSD style license.

#include "chrome/browser/ui/views/toolbar/boring_assist_button.h"

#include "base/functional/bind.h"
#include "chrome/browser/ui/browser_window/public/browser_window_interface.h"
#include "chrome/browser/ui/views/boring/boring_assistance_panel.h"
#include "components/tabs/public/tab_interface.h"
#include "components/vector_icons/vector_icons.h"
#include "content/public/browser/web_contents.h"
#include "ui/base/metadata/metadata_impl_macros.h"
#include "ui/views/accessibility/view_accessibility.h"

BoringAssistButton::BoringAssistButton(BrowserWindowInterface* browser)
    : ToolbarButton(base::BindRepeating(&BoringAssistButton::OnPressed,
                                        base::Unretained(this))),
      browser_(browser) {
  // A chat bubble with a sparkle reads as asking for help, and it is one of
  // Chromium's own generic icons, not a Google mark.
  SetVectorIcon(vector_icons::kChatSparkIcon);
  SetTooltipText(u"Ask Gemini");
  GetViewAccessibility().SetName(u"Ask Gemini");
  // Nothing is worth asking until a page is showing.
  SetVisible(false);

  // ToolbarView::Update never reaches us with a tab, so follow the
  // window's own active tab signal instead.
  tab_changed_ = browser_->RegisterActiveTabDidChange(base::BindRepeating(
      [](BoringAssistButton* self, BrowserWindowInterface*) {
        self->FollowActiveTab();
      },
      base::Unretained(this)));
  FollowActiveTab();
}

BoringAssistButton::~BoringAssistButton() = default;

void BoringAssistButton::FollowActiveTab() {
  tabs::TabInterface* active = browser_->GetActiveTabInterface();
  content::WebContents* tab = active ? active->GetContents() : nullptr;
  if (web_contents() != tab) {
    Observe(tab);
  }
  ShowIfAssistable();
}

void BoringAssistButton::PrimaryPageChanged(content::Page& page) {
  ShowIfAssistable();
}

void BoringAssistButton::ShowIfAssistable() {
  tabs::TabInterface* active = browser_->GetActiveTabInterface();
  const bool assistable = active != nullptr && boring::CanAssist(active);
  if (GetVisible() != assistable) {
    SetVisible(assistable);
    PreferredSizeChanged();
  }
}

void BoringAssistButton::OnPressed() {
  // The panel reads the page only once the person asks it to. This button
  // never reads or sends page content itself.
  boring::ToggleAssistancePanel(browser_);
}

BEGIN_METADATA(BoringAssistButton)
END_METADATA
