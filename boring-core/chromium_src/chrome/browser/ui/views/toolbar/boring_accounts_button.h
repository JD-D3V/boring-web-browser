// Copyright 2026 boring. BSD style license.

#ifndef CHROME_BROWSER_UI_VIEWS_TOOLBAR_BORING_ACCOUNTS_BUTTON_H_
#define CHROME_BROWSER_UI_VIEWS_TOOLBAR_BORING_ACCOUNTS_BUTTON_H_

#include <memory>
#include <string>

#include "base/memory/raw_ptr.h"
#include "base/memory/weak_ptr.h"
#include "chrome/browser/ui/views/boring/boring_popup.h"
#include "chrome/browser/ui/views/toolbar/toolbar_button.h"
#include "components/boring/accounts/accounts_rules.h"
#include "components/prefs/pref_change_registrar.h"
#include "ui/base/metadata/metadata_header_macros.h"
#include "ui/views/widget/widget.h"

class BrowserWindowInterface;
class GURL;

namespace ui {
class Event;
}

namespace views {
class BubbleDialogDelegate;
}  // namespace views

// The Accounts button on the toolbar (ledger item 11, screen 13). Accounts
// are shortcuts: the profile keeps a short list (components/boring/
// accounts) and this opens each company's own pages from it. Nothing is
// signed in to here and nothing is read from any site.
//
// The button shows the first account's initial in its colour, or a person
// glyph when there are none. Pressing it opens "Your accounts": one row
// per account with Mail, Calendar and Files, the six Add buttons, and a
// footer saying where you sign in. Links open in a new tab.
//
// Not added in Incognito or guest windows (toolbar_view.cc).
class BoringAccountsButton : public ToolbarButton {
  METADATA_HEADER(BoringAccountsButton, ToolbarButton)

 public:
  explicit BoringAccountsButton(BrowserWindowInterface* browser);

  BoringAccountsButton(const BoringAccountsButton&) = delete;
  BoringAccountsButton& operator=(const BoringAccountsButton&) = delete;

  ~BoringAccountsButton() override;

  // Also used by the test hook.
  void ShowPanel();
  bool IsPanelShowing() const;

  // ToolbarButton:
  void OnThemeChanged() override;
  bool HandleAccessibleAction(const ui::AXActionData& action_data) override;

 private:
  enum class Link { kMail, kCalendar, kFiles };

  // Paints the first account's initial, or the glyph, after the list or the
  // theme changes. A change to the list also closes an open panel, so it
  // never shows a list that is no longer there.
  void PaintInitial();
  void OnPressed(const ui::Event& event);
  void ClosePanel();
  void OnPanelCloseRequested(views::Widget::ClosedReason reason);
  void OnPanelClosed();

  // The panel's buttons. Accounts are named by id, and every address comes
  // from the store, never from the panel.
  void OnOpenLink(const std::string& id, Link link);
  void OnAddKnown(boring::accounts::Provider provider);
  void OnAddOther();
  // A new foreground tab, no referrer, as if typed.
  void OpenInNewTab(const GURL& url);

  // boring: test hook, see the .cc.
  void RunTestSteps(std::string steps);
  void WriteTestReport();

  const raw_ptr<BrowserWindowInterface> browser_;
  PrefChangeRegistrar pref_change_registrar_;

  // The delegate must outlive the widget: declared first, destroyed last.
  std::unique_ptr<views::BubbleDialogDelegate> panel_delegate_;
  std::unique_ptr<views::Widget> panel_;
  boring_ui::PopupMotion panel_motion_{boring_ui::PopupMotion::Style::kDrop};
  base::WeakPtrFactory<BoringAccountsButton> weak_factory_{this};
};

#endif  // CHROME_BROWSER_UI_VIEWS_TOOLBAR_BORING_ACCOUNTS_BUTTON_H_
