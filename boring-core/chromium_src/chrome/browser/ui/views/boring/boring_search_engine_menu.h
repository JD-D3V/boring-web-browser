// Copyright 2026 boring. BSD style license.

#ifndef CHROME_BROWSER_UI_VIEWS_BORING_BORING_SEARCH_ENGINE_MENU_H_
#define CHROME_BROWSER_UI_VIEWS_BORING_BORING_SEARCH_ENGINE_MENU_H_

#include <memory>
#include <string>
#include <vector>

#include "base/functional/callback.h"
#include "base/memory/raw_ptr.h"
#include "base/memory/weak_ptr.h"
#include "base/scoped_observation.h"
#include "base/values.h"
#include "chrome/browser/ui/views/boring/boring_popup.h"
#include "ui/gfx/geometry/rect.h"
#include "ui/views/widget/widget.h"
#include "ui/views/widget/widget_observer.h"

class LocationBarView;
class LocationIconView;
class Profile;

namespace gfx {
class Image;
}

namespace views {
class BubbleDialogDelegate;
class ImageView;
class LabelButton;
class View;
}  // namespace views

// The search engine menu: every engine the browser has, with its icon
// and name. Choosing one searches with it this once; "Make default" on a
// row makes it the browser's default. It unrolls downward like a paper
// scroll, and rolls back up on Done, Escape or a click elsewhere. With
// Windows "Animation effects" off it only fades.
//
// Opened from the engine icon at the left of the address bar, only
// where Chromium shows that icon (an empty address bar, as on the new
// tab page, or while a search is being typed), and from the engine
// button on our new tab page. Everywhere else the icon keeps Chromium's
// page info bubble; see the hooks below and search-engine-menu.patch.
class BoringSearchEngineMenu : public views::WidgetObserver {
 public:
  // An engine was chosen, by keyword: search with it this once.
  using PickCallback = base::RepeatingCallback<void(const std::u16string&)>;

  // Location icon hooks, called from location_icon_view.cc.

  // True when `icon` is showing the search engine rather than the page's
  // security state, so pressing it should open this menu.
  static bool IsAvailableFor(LocationIconView* icon);
  // Opens the menu under `icon`. False when it is not available there.
  static bool ShowForLocationIcon(LocationIconView* icon);
  // True while a menu opened from `icon` is on screen.
  static bool IsShowingFor(const LocationIconView* icon);
  // Makes `icon` a real button while the menu is available there
  // (focusable, named, "has popup"), and gives it back to Chromium's own
  // settings when it is not. Called at the end of Update().
  static void UpdateLocationIcon(LocationIconView* icon);

  // Opens the menu for the window whose address bar is `bar`, anchored
  // under `anchor_view`, or under `anchor_rect` (screen DIP) when there
  // is no view. Closes any menu already open. False when there is no
  // engine to list.
  static bool Show(LocationBarView* bar,
                   views::View* anchor_view,
                   const gfx::Rect& anchor_rect,
                   PickCallback on_pick,
                   base::RepeatingClosure on_default_changed,
                   base::OnceClosure on_closed);

  // The menu on screen, or null. There is at most one: opening one
  // takes activation from any other.
  static BoringSearchEngineMenu* GetShowing();

  BoringSearchEngineMenu(const BoringSearchEngineMenu&) = delete;
  BoringSearchEngineMenu& operator=(const BoringSearchEngineMenu&) = delete;

  ~BoringSearchEngineMenu() override;

  // Rolls the menu back up and closes it.
  void RollUp();

  // Test only (smoke_search_menu.py, through the new tab page when the
  // browser runs with --boring-search-menu-test).
  base::DictValue StateForTesting() const;
  void PickForTesting(size_t index);
  void MakeDefaultForTesting(size_t index);
  void PressEscapeForTesting();

  // views::WidgetObserver:
  void OnWidgetDestroying(views::Widget* widget) override;

 private:
  // One engine in the list.
  struct Row {
    Row();
    Row(Row&&);
    Row& operator=(Row&&);
    ~Row();

    std::string id;
    std::u16string keyword;
    std::u16string name;
    bool is_default = false;
    bool can_be_default = false;
    raw_ptr<views::LabelButton> pick = nullptr;
    raw_ptr<views::LabelButton> make_default = nullptr;
  };

  BoringSearchEngineMenu(LocationBarView* bar,
                         PickCallback on_pick,
                         base::RepeatingClosure on_default_changed,
                         base::OnceClosure on_closed);

  // Reads the engines. False when there are none yet.
  bool LoadRows();
  // Builds the list, keeping focus on `focus_keyword` when given.
  void BuildContents(views::View* list,
                     const std::u16string& focus_keyword = std::u16string());
  void Open(views::View* anchor_view, const gfx::Rect& anchor_rect);

  void OnPick(size_t index);
  void OnMakeDefault(size_t index);
  void OnDefaultChanged(const std::u16string& keyword,
                        const std::u16string& name);
  void OnFaviconFetched(const std::u16string& keyword, const gfx::Image& icon);

  // Every close, from Escape, Done, a click elsewhere or a choice, comes
  // here first, so the menu can roll up before it goes.
  void OnCloseRequested(views::Widget::ClosedReason reason);
  void OnRolledUp();
  // Draws the curl at the edge being unrolled.
  void OnMotionProgress(double progress, bool rich);

  // The curl painted at the bottom edge while the menu unrolls. Its own
  // layer on top of the popup's root layer.
  class Curl;

  Profile* profile() const;

  const raw_ptr<LocationBarView> bar_;
  PickCallback on_pick_;
  base::RepeatingClosure on_default_changed_;
  base::OnceClosure on_closed_;
  std::vector<Row> rows_;
  raw_ptr<views::View> list_ = nullptr;
  raw_ptr<views::View> contents_ = nullptr;
  // Rect the menu was anchored to, in screen DIP, for tests.
  gfx::Rect anchor_bounds_;
  raw_ptr<const views::View> anchor_view_ = nullptr;

  // The delegate must outlive the widget, so it is declared first and
  // destroyed last.
  std::unique_ptr<views::BubbleDialogDelegate> delegate_;
  std::unique_ptr<views::Widget> widget_;
  std::unique_ptr<Curl> curl_;
  boring_ui::PopupMotion motion_{boring_ui::PopupMotion::Style::kUnroll};
  base::ScopedObservation<views::Widget, views::WidgetObserver>
      widget_observation_{this};
  base::WeakPtrFactory<BoringSearchEngineMenu> weak_factory_{this};
};

#endif  // CHROME_BROWSER_UI_VIEWS_BORING_BORING_SEARCH_ENGINE_MENU_H_
