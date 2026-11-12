// Copyright 2026 boring. BSD style license.

#include "chrome/browser/ui/views/boring/boring_save_tabs.h"

#include <utility>
#include <vector>

#include "base/functional/bind.h"
#include "base/functional/callback_helpers.h"
#include "base/i18n/time_formatting.h"
#include "base/memory/weak_ptr.h"
#include "base/strings/string_number_conversions.h"
#include "chrome/browser/bookmarks/bookmark_model_factory.h"
#include "chrome/browser/profiles/profile.h"
#include "chrome/browser/ui/bookmarks/bookmark_utils.h"
#include "chrome/browser/ui/browser_window/public/browser_window_interface.h"
#include "chrome/browser/ui/browser_window/public/global_browser_collection.h"
#include "chrome/browser/ui/chrome_pages.h"
#include "chrome/browser/ui/tabs/tab_strip_model.h"
#include "chrome/common/webui_url_constants.h"
#include "components/bookmarks/browser/bookmark_model.h"
#include "components/bookmarks/browser/bookmark_node.h"
#include "components/constrained_window/constrained_window_views.h"
#include "ui/base/base_window.h"
#include "ui/base/models/dialog_model.h"
#include "ui/base/mojom/dialog_button.mojom.h"
#include "url/gurl.h"

namespace boring {

namespace {

struct Page {
  GURL url;
  std::u16string title;
};

// The tabs of one window that hold a page. A new tab page or a blank tab
// is not worth a bookmark.
std::vector<Page> PagesOf(BrowserWindowInterface* window) {
  std::vector<Page> pages;
  TabStripModel* tabs = window->GetTabStripModel();
  const GURL new_tab(chrome::kChromeUINewTabURL);
  for (int i = 0; i < tabs->count(); ++i) {
    Page page;
    if (!chrome::GetURLAndTitleToBookmark(tabs->GetWebContentsAt(i), &page.url,
                                          &page.title) ||
        page.url.IsAboutBlank() || page.url == new_tab) {
      continue;
    }
    pages.push_back(std::move(page));
  }
  return pages;
}

void ShowSaved(BrowserWindowInterface* browser,
               int64_t folder_id,
               const std::u16string& folder_name,
               size_t count) {
  auto show = base::BindOnce(
      [](base::WeakPtr<BrowserWindowInterface> weak_browser, int64_t id) {
        if (BrowserWindowInterface* b = weak_browser.get()) {
          chrome::ShowBookmarkManagerForNode(b, id);
        }
      },
      browser->GetWeakPtr(), folder_id);
  const std::u16string tabs =
      count == 1 ? u"1 tab is" : base::NumberToString16(count) + u" tabs are";
  auto model =
      ui::DialogModel::Builder()
          .SetTitle(u"Tabs saved")
          .AddParagraph(ui::DialogModelLabel(
              tabs + u" in your bookmarks now, in the folder \"" +
              folder_name + u"\"."))
          .AddOkButton(std::move(show),
                       ui::DialogModel::Button::Params().SetLabel(u"Show"))
          .AddCancelButton(base::DoNothing(),
                           ui::DialogModel::Button::Params().SetLabel(u"Done"))
          .OverrideDefaultButton(ui::mojom::DialogButton::kCancel)
          .Build();
  constrained_window::ShowBrowserModal(
      std::move(model), browser->GetWindow()->GetNativeWindow());
}

}  // namespace

std::u16string SavedTabsFolderName(base::Time when) {
  return u"Tabs " + base::TimeFormatShortDateAndTime(when);
}

void SaveAllTabs(BrowserWindowInterface* browser) {
  Profile* profile = browser->GetProfile();
  bookmarks::BookmarkModel* model =
      BookmarkModelFactory::GetForBrowserContext(profile);
  if (!model || !model->loaded()) {
    return;
  }

  // Every ordinary window of this profile: from an incognito window, its
  // own incognito windows, never the other way round.
  std::vector<std::vector<Page>> windows;
  GlobalBrowserCollection::GetInstance()->ForEach(
      [&](BrowserWindowInterface* window) {
        if (window->GetProfile() == profile &&
            window->GetType() == BrowserWindowInterface::TYPE_NORMAL) {
          std::vector<Page> pages = PagesOf(window);
          if (!pages.empty()) {
            windows.push_back(std::move(pages));
          }
        }
        return true;
      });
  if (windows.empty()) {
    return;
  }

  const bookmarks::BookmarkNode* parent = model->other_node();
  const std::u16string name = SavedTabsFolderName(base::Time::Now());
  const bookmarks::BookmarkNode* folder =
      model->AddFolder(parent, parent->children().size(), name);
  size_t count = 0;
  for (size_t w = 0; w < windows.size(); ++w) {
    const bookmarks::BookmarkNode* into = folder;
    if (windows.size() > 1) {
      into = model->AddFolder(folder, w,
                              u"Window " + base::NumberToString16(w + 1));
    }
    for (const Page& page : windows[w]) {
      model->AddNewURL(into, into->children().size(), page.title, page.url);
      ++count;
    }
  }
  ShowSaved(browser, folder->id(), name, count);
}

}  // namespace boring
