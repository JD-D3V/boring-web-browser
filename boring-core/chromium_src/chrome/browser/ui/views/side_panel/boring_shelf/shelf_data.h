// Copyright 2026 boring. BSD style license.

#ifndef CHROME_BROWSER_UI_VIEWS_SIDE_PANEL_BORING_SHELF_SHELF_DATA_H_
#define CHROME_BROWSER_UI_VIEWS_SIDE_PANEL_BORING_SHELF_SHELF_DATA_H_

#include <string>
#include <string_view>
#include <vector>

#include "base/time/time.h"
#include "url/gurl.h"

namespace gfx {
struct VectorIcon;
}

class Profile;

// The Shelf's own data: plain structs and helpers with no views in them, so
// the Shelf and the side tabs list (item 14) can share them.
namespace boring::shelf {

// What a row or a tile does when it is pressed.
enum class ShelfKind {
  kPinned,        // A site on the new tab page's Pinned list.
  kOpenGroup,     // A tab group open in this window; id is the group token.
  kSavedGroup,    // A closed, saved tab group; id is its guid.
  kEarlier,       // A tab closed a while ago (item 16).
  kShowAllEarlier,
  kReadingList,
  kBookmark,
  kDownload,      // id is the download's guid.
};

struct ShelfItem {
  std::u16string title;
  std::u16string meta;
  const gfx::VectorIcon* icon = nullptr;
  GURL url;
  ShelfKind kind = ShelfKind::kPinned;
  std::string id;
};

// The Earlier section's data. Item 16 fills this in; until then the section
// is off and empty, and the Shelf draws nothing for it.
struct EarlierState {
  bool enabled = false;
  size_t total = 0;
  // Newest first. The Shelf shows the first two.
  std::vector<ShelfItem> newest;
};

// Row text for a title from a page or a file: one line, no control
// characters, at most 200 characters, and the host when there is no title.
// The label that draws it elides the rest.
std::u16string ShelfTitle(std::u16string_view title, const GURL& url);

// "1 tab", "3 tabs".
std::u16string TabCountText(size_t count);

// "Show all 23".
std::u16string ShowAllText(size_t count);

// "Today", a weekday for the last six days, else a short date.
std::u16string AgeText(base::Time now, base::Time then);

// The profile's Earlier tabs. The default is off and empty (item 16).
EarlierState GetEarlierState(Profile* profile);

// The Pinned sites, newest first as pinned, at most eight. Reads the new tab
// page's list (boring.newtab.shortcuts) and nothing else.
std::vector<ShelfItem> PinnedItems(Profile* profile);

inline constexpr size_t kMaxPinned = 8;
// The newest rows shown in "Saved and downloaded", all kinds together.
inline constexpr size_t kMaxSaved = 3;
// Pref: also list the bookmark bar's top-level bookmarks in the Shelf.
inline constexpr char kShowBookmarksPref[] = "boring.shelf.show_bookmarks";

}  // namespace boring::shelf

#endif  // CHROME_BROWSER_UI_VIEWS_SIDE_PANEL_BORING_SHELF_SHELF_DATA_H_
