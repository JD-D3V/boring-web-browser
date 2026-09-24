// Copyright 2026 boring. BSD style license.

#ifndef CHROME_BROWSER_UI_VIEWS_TOOLBAR_BORING_PROTECTION_BUTTON_H_
#define CHROME_BROWSER_UI_VIEWS_TOOLBAR_BORING_PROTECTION_BUTTON_H_

#include <string>

#include "base/callback_list.h"
#include "base/memory/raw_ptr.h"
#include "base/timer/timer.h"
#include "chrome/browser/ui/views/toolbar/toolbar_button.h"
#include "components/prefs/pref_change_registrar.h"
#include "content/public/browser/web_contents_observer.h"
#include "ui/base/metadata/metadata_header_macros.h"
#include "ui/menus/simple_menu_model.h"

class BrowserWindowInterface;

namespace ui {
class Event;
}

// The shield in the toolbar. It says whether scam and ad blocking are
// really running, without being asked, and grows a "Needs attention"
// label when a list did not load, or "Blocking off" on a site where the
// person turned it off. Pressing it on a web page opens a short menu to
// turn blocking off or back on for that site, or open the Protection
// page; anywhere else it opens the Protection page.
class BoringProtectionButton : public ToolbarButton,
                               public content::WebContentsObserver,
                               public ui::SimpleMenuModel::Delegate {
  METADATA_HEADER(BoringProtectionButton, ToolbarButton)

 public:
  explicit BoringProtectionButton(BrowserWindowInterface* browser);

  BoringProtectionButton(const BoringProtectionButton&) = delete;
  BoringProtectionButton& operator=(const BoringProtectionButton&) = delete;

  ~BoringProtectionButton() override;

  // ToolbarButton:
  void OnThemeChanged() override;

  // content::WebContentsObserver:
  void PrimaryPageChanged(content::Page& page) override;

  // ui::SimpleMenuModel::Delegate:
  void ExecuteCommand(int command_id, int event_flags) override;

 protected:
  // ToolbarButton, also reached by a right click:
  void ShowDropDownMenu(ui::mojom::MenuSourceType source_type) override;

 private:
  // What the shield is currently saying.
  enum class State {
    kWorking,  // both lists loaded, everything is being blocked
    kLoading,  // at least one list has not finished, nothing to report yet
    kFailed,   // a list is missing, so something is not being blocked
    kOffHere,  // the person turned blocking off for this tab's site
  };

  // Reads the two services and paints what it finds. While a list is
  // still loading it asks again shortly and stops once there is an
  // answer, because neither service has anything to subscribe to.
  void UpdateState();

  State ReadState() const;
  void OnPressed(const ui::Event& event);

  // Points us at whichever tab the window is showing now.
  void FollowActiveTab();

  // The site of the page in the tab, see boring::GetBlockingSite().
  // Empty on pages that are not http or https.
  std::string CurrentSite() const;
  bool IsOffHere() const;

  // The menu, owned by ToolbarButton so it outlives an open menu.
  ui::SimpleMenuModel* site_menu();

  const raw_ptr<BrowserWindowInterface> browser_;
  State state_ = State::kLoading;
  base::OneShotTimer while_loading_;
  base::CallbackListSubscription tab_changed_;
  // Repaints when a site is added or removed anywhere, the Protection
  // page or another window included.
  PrefChangeRegistrar pref_change_registrar_;
  // The site the open menu is about, so a choice acts on the site that
  // was shown even if the tab moves on while the menu is open.
  std::string menu_site_;
};

#endif  // CHROME_BROWSER_UI_VIEWS_TOOLBAR_BORING_PROTECTION_BUTTON_H_
