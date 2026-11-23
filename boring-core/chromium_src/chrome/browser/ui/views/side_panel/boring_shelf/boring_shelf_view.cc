// Copyright 2026 boring. BSD style license.

#include "chrome/browser/ui/views/side_panel/boring_shelf/boring_shelf_view.h"

#include <algorithm>
#include <limits>
#include <map>
#include <set>
#include <utility>
#include <vector>

#include "base/functional/bind.h"
#include "base/i18n/rtl.h"
#include "base/no_destructor.h"
#include "base/task/single_thread_task_runner.h"
#include "base/strings/utf_string_conversions.h"
#include "base/time/time.h"
#include "chrome/app/vector_icons/vector_icons.h"
#include "chrome/browser/bookmarks/bookmark_model_factory.h"
#include "chrome/browser/profiles/profile.h"
#include "chrome/browser/reading_list/reading_list_model_factory.h"
#include "chrome/browser/tab_group_sync/tab_group_sync_service_factory.h"
#include "chrome/browser/ui/browser_window/public/browser_window_interface.h"
#include "chrome/browser/ui/color/chrome_color_id.h"
#include "chrome/browser/ui/navigator/browser_navigator.h"
#include "chrome/browser/ui/navigator/browser_navigator_params.h"
#include "chrome/browser/ui/tabs/saved_tab_groups/saved_tab_group_utils.h"
#include "chrome/browser/ui/tabs/tab_group_model.h"
#include "chrome/browser/ui/tabs/tab_strip_model.h"
#include "chrome/browser/ui/views/side_panel/boring_shelf/boring_shelf_coordinator.h"
#include "chrome/browser/ui/views/side_panel/boring_shelf/shelf_row.h"
#include "chrome/common/pref_names.h"
#include "components/boring/newtab/newtab_ui.h"
#include "components/bookmarks/browser/bookmark_model.h"
#include "components/bookmarks/browser/bookmark_node.h"
#include "components/prefs/pref_service.h"
#include "components/reading_list/core/reading_list_entry.h"
#include "components/reading_list/core/reading_list_model.h"
#include "components/saved_tab_groups/public/saved_tab_group.h"
#include "components/saved_tab_groups/public/tab_group_sync_service.h"
#include "components/saved_tab_groups/public/types.h"
#include "components/tabs/public/tab_group.h"
#include "content/public/browser/web_contents.h"
#include "ui/base/metadata/metadata_impl_macros.h"
#include "ui/base/page_transition_types.h"
#include "ui/base/window_open_disposition.h"
#include "ui/views/accessibility/view_accessibility.h"
#include "ui/views/border.h"
#include "ui/views/controls/scroll_view.h"
#include "ui/views/layout/box_layout_view.h"
#include "ui/views/layout/table_layout_view.h"

namespace boring::shelf {

namespace {

constexpr int kSectionGap = 18;
constexpr int kRowGap = 2;
constexpr int kTileGap = 6;
constexpr int kTileColumns = 4;

// A vertical column of children.
std::unique_ptr<views::BoxLayoutView> Column(int spacing) {
  auto column = std::make_unique<views::BoxLayoutView>();
  column->SetOrientation(views::BoxLayout::Orientation::kVertical);
  column->SetBetweenChildSpacing(spacing);
  return column;
}

// A section is its heading and rows; a section with no rows is not drawn.
std::unique_ptr<views::View> Section(const std::u16string& heading,
                                     const std::u16string& note,
                                     std::vector<std::unique_ptr<views::View>>
                                         rows) {
  if (rows.empty()) {
    return nullptr;
  }
  auto column = Column(kRowGap);
  column->AddChildView(std::make_unique<ShelfSectionHeading>(heading, note));
  for (auto& row : rows) {
    column->AddChildView(std::move(row));
  }
  return column;
}

// The Shelf of each window, and the windows whose Shelf is to open Earlier out
// when it is built (the command can arrive before the panel exists).
std::map<BrowserWindowInterface*, BoringShelfView*>& LiveShelves() {
  static base::NoDestructor<std::map<BrowserWindowInterface*, BoringShelfView*>>
      shelves;
  return *shelves;
}
std::set<BrowserWindowInterface*>& PendingExpand() {
  static base::NoDestructor<std::set<BrowserWindowInterface*>> pending;
  return *pending;
}

struct SavedRow {
  base::Time when;
  ShelfItem item;
};

}  // namespace

BoringShelfView::BoringShelfView(BrowserWindowInterface* browser)
    : browser_(browser) {
  SetBackgroundColor(kColorBoringShelfBackground);
  SetDrawOverflowIndicator(false);
  SetHorizontalScrollBarMode(views::ScrollView::ScrollBarMode::kDisabled);
  // Bounded, so the scroll view sizes its contents to the panel's width and
  // their own height. Unbounded, it leaves them 0 by 0: nothing is drawn and
  // no tile or row can be pressed.
  ClipHeightTo(0, std::numeric_limits<int>::max());
  // The Shelf's edge on the side next to the page: a 1 px line, as drawn.
  const bool rtl = base::i18n::IsRTL();
  SetBorder(views::CreateSolidSidedBorder(
      rtl ? gfx::Insets::TLBR(0, 1, 0, 0) : gfx::Insets::TLBR(0, 0, 0, 1),
      kColorBoringShelfEdge));
  GetViewAccessibility().SetRole(ax::mojom::Role::kPane);
  GetViewAccessibility().SetName(u"The Shelf");

  Profile* profile = browser_->GetProfile();
  pref_registrar_.Init(profile->GetPrefs());
  auto rebuild = base::BindRepeating(&BoringShelfView::ScheduleRebuild,
                                     base::Unretained(this));
  pref_registrar_.Add(boring::kNewTabShortcutsPref, rebuild);
  pref_registrar_.Add(kShowBookmarksPref, rebuild);
  pref_registrar_.Add(prefs::kVerticalTabsEnabled,
                      base::BindRepeating(&BoringShelfView::OnSideTabsChanged,
                                          base::Unretained(this)));

  tabs_ = browser_->GetTabStripModel();
  tabs_->AddObserver(this);
  LiveShelves()[browser_] = this;
  if (PendingExpand().erase(browser_)) {
    earlier_expanded_ = true;
  }
  if (IsRegular()) {
    // boring: item 16. Earlier tabs changing rebuilds the section.
    earlier_service_ = boring::earlier::EarlierTabsService::Get(profile);
    if (earlier_service_) {
      earlier_service_->AddObserver(this);
    }
    if (ReadingListModel* model =
            ReadingListModelFactory::GetForBrowserContext(profile)) {
      reading_list_.Observe(model);
    }
    if (content::DownloadManager* manager = profile->GetDownloadManager()) {
      downloads_.Observe(manager);
    }
  }
  Rebuild();
}

BoringShelfView::~BoringShelfView() {
  auto it = LiveShelves().find(browser_);
  if (it != LiveShelves().end() && it->second == this) {
    LiveShelves().erase(it);
  }
  if (earlier_service_) {
    earlier_service_->RemoveObserver(this);
  }
  // TabStripModel takes plain AddObserver, not a ScopedObservation.
  if (tabs_) {
    tabs_->RemoveObserver(this);
  }
}

bool BoringShelfView::IsRegular() const {
  return browser_->GetProfile()->IsRegularProfile();
}

void BoringShelfView::AddedToWidget() {
  views::ScrollView::AddedToWidget();
  ScheduleRebuild();
}

void BoringShelfView::VisibilityChanged(views::View* starting_from,
                                        bool is_visible) {
  views::ScrollView::VisibilityChanged(starting_from, is_visible);
  // A cached view comes back when the panel opens: refresh what could have
  // changed while it was away (closed groups, bookmarks).
  if (is_visible) {
    ScheduleRebuild();
  }
}

void BoringShelfView::OnTabStripModelChanged(
    TabStripModel* tab_strip_model,
    const TabStripModelChange& change,
    const TabStripSelectionChange& selection) {
  ScheduleRebuild();
}

void BoringShelfView::OnTabGroupChanged(const TabGroupChange& change) {
  ScheduleRebuild();
}

void BoringShelfView::OnTabStripModelDestroyed(TabStripModel* tab_strip_model) {
  // The window is going away; the model goes first.
  if (tabs_ == tab_strip_model) {
    tabs_->RemoveObserver(this);
    tabs_ = nullptr;
  }
}

void BoringShelfView::ReadingListModelLoaded(const ReadingListModel* model) {
  ScheduleRebuild();
}

void BoringShelfView::ReadingListDidAddEntry(
    const ReadingListModel* model,
    const GURL& url,
    reading_list::EntrySource source) {
  ScheduleRebuild();
}

void BoringShelfView::ReadingListDidRemoveEntry(const ReadingListModel* model,
                                                const GURL& url) {
  ScheduleRebuild();
}

void BoringShelfView::ReadingListDidApplyChanges(ReadingListModel* model) {
  ScheduleRebuild();
}

void BoringShelfView::OnDownloadCreated(content::DownloadManager* manager,
                                        download::DownloadItem* item) {
  download_items_.AddObservation(item);
  ScheduleRebuild();
}

void BoringShelfView::ManagerGoingDown(content::DownloadManager* manager) {
  download_items_.RemoveAllObservations();
  downloads_.Reset();
}

void BoringShelfView::OnDownloadUpdated(download::DownloadItem* download) {
  if (download->GetState() == download::DownloadItem::COMPLETE) {
    ScheduleRebuild();
  }
}

void BoringShelfView::OnDownloadDestroyed(download::DownloadItem* download) {
  if (download_items_.IsObservingSource(download)) {
    download_items_.RemoveObservation(download);
  }
  ScheduleRebuild();
}

void BoringShelfView::ScheduleRebuild() {
  if (rebuild_pending_) {
    return;
  }
  rebuild_pending_ = true;
  // After the current task: a press on a row rebuilds the rows, so the
  // rebuild must not run inside the row's own click.
  base::SingleThreadTaskRunner::GetCurrentDefault()->PostTask(
      FROM_HERE, base::BindOnce(
                     [](base::WeakPtr<BoringShelfView> view) {
                       if (view) {
                         view->Rebuild();
                       }
                     },
                     weak_factory_.GetWeakPtr()));
}

void BoringShelfView::OnSideTabsChanged() {
  if (!browser_->GetProfile()->GetPrefs()->GetBoolean(
          prefs::kVerticalTabsEnabled)) {
    return;
  }
  // After the current task: closing the panel can delete this view.
  base::SingleThreadTaskRunner::GetCurrentDefault()->PostTask(
      FROM_HERE, base::BindOnce(
                     [](base::WeakPtr<BoringShelfView> view) {
                       if (view) {
                         CloseShelf(view->browser_);
                       }
                     },
                     weak_factory_.GetWeakPtr()));
}

void BoringShelfView::Rebuild() {
  rebuild_pending_ = false;
  auto content = Column(kSectionGap);
  content->SetInsideBorderInsets(gfx::Insets::VH(16, 12));
  std::unique_ptr<views::View> sections[] = {BuildPinned(), BuildGroups(),
                                             BuildEarlier(), BuildSaved()};
  for (auto& section : sections) {
    if (section) {
      content->AddChildView(std::move(section));
    }
  }
  SetContents(std::move(content));
}

std::unique_ptr<views::View> BoringShelfView::BuildPinned() {
  const std::vector<ShelfItem> items = PinnedItems(browser_->GetProfile());
  if (items.empty()) {
    return nullptr;
  }
  auto column = Column(4);  // The heading's own 4 makes the drawn 8.
  column->AddChildView(std::make_unique<ShelfSectionHeading>(u"Pinned",
                                                             std::u16string()));
  auto grid = std::make_unique<views::TableLayoutView>();
  for (int i = 0; i < kTileColumns; ++i) {
    if (i > 0) {
      grid->AddPaddingColumn(views::TableLayout::kFixedSize, kTileGap);
    }
    grid->AddColumn(views::LayoutAlignment::kStretch,
                    views::LayoutAlignment::kStretch, 1.0f,
                    views::TableLayout::ColumnSize::kFixed, 0, 0);
  }
  for (size_t i = 0; i < items.size(); ++i) {
    if (i % kTileColumns == 0) {
      if (i > 0) {
        grid->AddPaddingRow(views::TableLayout::kFixedSize, kTileGap);
      }
      grid->AddRows(1, views::TableLayout::kFixedSize, ShelfTile::kHeight);
    }
    grid->AddChildView(std::make_unique<ShelfTile>(
        base::BindRepeating(&BoringShelfView::ActivateItem,
                            base::Unretained(this), items[i]),
        items[i].mark, items[i].title));
  }
  column->AddChildView(std::move(grid));
  return column;
}

std::unique_ptr<views::View> BoringShelfView::BuildGroups() {
  std::vector<std::unique_ptr<views::View>> rows;
  TabStripModel* strip = browser_->GetTabStripModel();
  TabGroupModel* groups = strip->group_model();
  std::vector<base::Uuid> open_saved;
  if (groups) {
    tab_groups::TabGroupSyncService* service =
        IsRegular() ? tab_groups::TabGroupSyncServiceFactory::GetForProfile(
                          browser_->GetProfile())
                    : nullptr;
    for (const tab_groups::TabGroupId& id : groups->ListTabGroups()) {
      const TabGroup* group = groups->GetTabGroup(id);
      if (!group) {
        continue;
      }
      const gfx::Range tabs = group->ListTabs();
      std::u16string title =
          ShelfTitle(group->visual_data()->title(), GURL());
      if (title.empty()) {
        title = u"Group";
      }
      rows.push_back(std::make_unique<ShelfRow>(
          base::BindRepeating(&BoringShelfView::ActivateOpenGroup,
                              base::Unretained(this),
                              static_cast<int>(tabs.start())),
          kBoringFolderIcon, title, TabCountText(tabs.length())));
      if (service) {
        if (auto saved = service->GetGroup(id)) {
          open_saved.push_back(saved->saved_guid());
        }
      }
    }
  }
  // Closed groups that are saved on this device.
  if (IsRegular()) {
    if (tab_groups::TabGroupSyncService* service =
            tab_groups::TabGroupSyncServiceFactory::GetForProfile(
                browser_->GetProfile())) {
      for (const tab_groups::SavedTabGroup& saved : service->GetAllGroups()) {
        if (saved.local_group_id().has_value() ||
            saved.is_shared_tab_group() ||
            std::ranges::contains(open_saved, saved.saved_guid())) {
          continue;
        }
        std::u16string title = ShelfTitle(saved.title(), GURL());
        if (title.empty()) {
          title = u"Group";
        }
        rows.push_back(std::make_unique<ShelfRow>(
            base::BindRepeating(&BoringShelfView::ActivateSavedGroup,
                                base::Unretained(this),
                                saved.saved_guid().AsLowercaseString()),
            kBoringFolderIcon, title, TabCountText(saved.saved_tabs().size())));
      }
    }
  }
  return Section(u"Groups", std::u16string(), std::move(rows));
}

std::unique_ptr<views::View> BoringShelfView::BuildEarlier() {
  if (!IsRegular()) {
    return nullptr;
  }
  const EarlierState state = GetEarlierState(browser_->GetProfile());
  if (!state.enabled && state.newest.empty()) {
    return nullptr;
  }
  std::vector<std::unique_ptr<views::View>> rows;
  const size_t shown = earlier_expanded_
                           ? state.newest.size()
                           : std::min<size_t>(2, state.newest.size());
  for (size_t i = 0; i < shown; ++i) {
    const ShelfItem& item = state.newest[i];
    rows.push_back(std::make_unique<ShelfRow>(
        base::BindRepeating(&BoringShelfView::ActivateItem,
                            base::Unretained(this), item),
        item.icon ? *item.icon : kBoringDocIcon, item.title, item.meta));
  }
  if (!earlier_expanded_ && state.total > shown) {
    rows.push_back(std::make_unique<ShelfRow>(
        base::BindRepeating(&BoringShelfView::ShowAllEarlier,
                            base::Unretained(this)),
        kBoringClockIcon, ShowAllText(state.total), std::u16string()));
  }
  if (rows.empty()) {
    // Earlier is on but holds nothing yet: say so in one quiet row-less
    // heading is not drawn; the section simply waits.
    return nullptr;
  }
  return Section(u"Earlier", u"kept 30 days", std::move(rows));
}

std::unique_ptr<views::View> BoringShelfView::BuildSaved() {
  if (!IsRegular()) {
    return nullptr;
  }
  Profile* profile = browser_->GetProfile();
  const base::Time now = base::Time::Now();
  std::vector<SavedRow> saved;

  // Read later: unread reading list entries.
  ReadingListModel* reading = ReadingListModelFactory::GetForBrowserContext(
      profile);
  if (reading && reading->loaded()) {
    for (const GURL& url : reading->GetKeys()) {
      scoped_refptr<const ReadingListEntry> entry =
          reading->GetEntryByURL(url);
      if (!entry || entry->IsRead() || !url.SchemeIsHTTPOrHTTPS()) {
        continue;
      }
      ShelfItem item;
      item.title = ShelfTitle(base::UTF8ToUTF16(entry->Title()), url);
      item.meta = u"Read later";
      item.icon = &kBoringEyeIcon;
      item.url = url;
      item.kind = ShelfKind::kReadingList;
      saved.push_back(
          {base::Time::FromDeltaSinceWindowsEpoch(
               base::Microseconds(entry->UpdateTime())),
           std::move(item)});
    }
  }

  // Bookmarks, when the Bookmarks setting includes the Shelf.
  if (profile->GetPrefs()->GetBoolean(kShowBookmarksPref)) {
    if (bookmarks::BookmarkModel* model =
            BookmarkModelFactory::GetForBrowserContext(profile);
        model && model->loaded()) {
      for (const auto& node : model->bookmark_bar_node()->children()) {
        if (!node->is_url() || !node->url().SchemeIsHTTPOrHTTPS()) {
          continue;
        }
        ShelfItem item;
        item.title = ShelfTitle(node->GetTitle(), node->url());
        item.icon = &kBoringBookIcon;
        item.url = node->url();
        item.kind = ShelfKind::kBookmark;
        saved.push_back({node->date_added(), std::move(item)});
      }
    }
  }

  // Downloads that finished.
  if (content::DownloadManager* manager = profile->GetDownloadManager()) {
    std::vector<raw_ptr<download::DownloadItem, VectorExperimental>> all;
    manager->GetAllDownloads(&all);
    for (download::DownloadItem* download : all) {
      if (download->GetState() != download::DownloadItem::COMPLETE ||
          download->IsTemporary() || download->IsDangerous()) {
        continue;
      }
      ShelfItem item;
      item.title = ShelfTitle(
          download->GetTargetFilePath().BaseName().AsUTF16Unsafe(), GURL());
      item.meta = AgeText(now, download->GetEndTime());
      item.icon = &kBoringDownIcon;
      item.kind = ShelfKind::kDownload;
      item.id = download->GetGuid();
      saved.push_back({download->GetEndTime(), std::move(item)});
    }
  }

  std::stable_sort(saved.begin(), saved.end(),
                   [](const SavedRow& a, const SavedRow& b) {
                     return a.when > b.when;
                   });
  std::vector<std::unique_ptr<views::View>> rows;
  for (size_t i = 0; i < saved.size() && i < kMaxSaved; ++i) {
    const ShelfItem& item = saved[i].item;
    if (item.kind == ShelfKind::kDownload) {
      rows.push_back(std::make_unique<ShelfRow>(
          base::BindRepeating(&BoringShelfView::ActivateDownload,
                              base::Unretained(this), item.id),
          *item.icon, item.title, item.meta));
    } else {
      rows.push_back(std::make_unique<ShelfRow>(
          base::BindRepeating(&BoringShelfView::ActivateItem,
                              base::Unretained(this), item),
          *item.icon, item.title, item.meta));
    }
  }
  return Section(u"Saved and downloaded", std::u16string(), std::move(rows));
}

void BoringShelfView::OpenUrl(const GURL& url, bool switch_to_open_tab) {
  if (!url.is_valid() || !url.SchemeIsHTTPOrHTTPS()) {
    return;
  }
  TabStripModel* strip = browser_->GetTabStripModel();
  if (switch_to_open_tab) {
    // The same site already open here: go to it instead of opening another.
    for (int i = 0; i < strip->count(); ++i) {
      content::WebContents* contents = strip->GetWebContentsAt(i);
      if (contents && contents->GetLastCommittedURL() == url) {
        strip->ActivateTabAt(i);
        return;
      }
    }
  }
  NavigateParams params(browser_, url, ui::PAGE_TRANSITION_AUTO_BOOKMARK);
  params.disposition = WindowOpenDisposition::NEW_FOREGROUND_TAB;
  Navigate(&params);
}

void BoringShelfView::ActivateItem(const ShelfItem& item) {
  if (item.kind == ShelfKind::kEarlier) {
    // A tab that was moved to Earlier comes back as a tab at the end of this
    // window's strip. The address was checked when the list was read.
    if (earlier_service_) {
      earlier_service_->Reopen(item.id, browser_);
    }
    return;
  }
  OpenUrl(item.url, item.kind == ShelfKind::kPinned);
}

void BoringShelfView::ActivateOpenGroup(int first_tab_index) {
  TabStripModel* strip = browser_->GetTabStripModel();
  if (first_tab_index >= 0 && first_tab_index < strip->count()) {
    strip->ActivateTabAt(first_tab_index);
  }
}

void BoringShelfView::ActivateSavedGroup(const std::string& guid) {
  base::Uuid id = base::Uuid::ParseLowercase(guid);
  if (!id.is_valid()) {
    return;
  }
  tab_groups::SavedTabGroupUtils::OpenSavedTabGroup(
      browser_, id, tab_groups::OpeningSource::kOpenedFromRevisitUi);
}

void BoringShelfView::ActivateDownload(const std::string& guid) {
  content::DownloadManager* manager =
      browser_->GetProfile()->GetDownloadManager();
  if (!manager) {
    return;
  }
  download::DownloadItem* item = manager->GetDownloadByGuid(guid);
  // The row was built earlier: check again at the press that the download
  // is still there, finished, and not marked dangerous, insecure or removed
  // since. Otherwise the press does nothing.
  if (!item || item->GetState() != download::DownloadItem::COMPLETE ||
      item->IsTemporary() || item->IsTransient() || item->IsDangerous() ||
      item->IsInsecure() || item->GetFileExternallyRemoved() ||
      item->GetTargetFilePath().empty()) {
    return;
  }
  item->OpenDownload();
}

// static
void BoringShelfView::ExpandEarlierFor(BrowserWindowInterface* browser) {
  auto it = LiveShelves().find(browser);
  if (it != LiveShelves().end()) {
    it->second->ShowAllEarlier();
  } else {
    PendingExpand().insert(browser);
  }
}

void BoringShelfView::OnEarlierTabsChanged() {
  ScheduleRebuild();
}

void BoringShelfView::ShowAllEarlier() {
  earlier_expanded_ = true;
  ScheduleRebuild();
}

BEGIN_METADATA(BoringShelfView)
END_METADATA

}  // namespace boring::shelf
