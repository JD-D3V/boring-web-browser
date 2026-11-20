// Copyright 2026 boring. BSD style license.

#ifndef CHROME_BROWSER_UI_VIEWS_SIDE_PANEL_BORING_SHELF_BORING_SHELF_VIEW_H_
#define CHROME_BROWSER_UI_VIEWS_SIDE_PANEL_BORING_SHELF_BORING_SHELF_VIEW_H_

#include <memory>
#include <string>

#include "base/memory/raw_ptr.h"
#include "base/memory/weak_ptr.h"
#include "base/scoped_multi_source_observation.h"
#include "base/scoped_observation.h"
#include "chrome/browser/ui/tabs/tab_strip_model.h"
#include "chrome/browser/ui/tabs/tab_strip_model_observer.h"
#include "chrome/browser/ui/views/side_panel/boring_shelf/shelf_data.h"
#include "components/prefs/pref_change_registrar.h"
#include "components/reading_list/core/reading_list_model_observer.h"
#include "components/download/public/common/download_item.h"
#include "content/public/browser/download_manager.h"
#include "ui/base/metadata/metadata_header_macros.h"
#include "ui/views/controls/scroll_view.h"

class BrowserWindowInterface;
class ReadingListModel;
class TabStripModel;

namespace boring::shelf {

// The Shelf with top tabs (screen C03): pinned sites, tab groups, earlier
// tabs, saved pages and downloads, in one column. It only reads models that
// are already in the profile and never fetches anything. Every title is page
// text, so it is drawn as a plain one-line label that elides, the way the
// tab strip draws a tab title.
class BoringShelfView : public views::ScrollView,
                        public TabStripModelObserver,
                        public ReadingListModelObserver,
                        public content::DownloadManager::Observer,
                        public download::DownloadItem::Observer {
  METADATA_HEADER(BoringShelfView, views::ScrollView)

 public:
  explicit BoringShelfView(BrowserWindowInterface* browser);
  BoringShelfView(const BoringShelfView&) = delete;
  BoringShelfView& operator=(const BoringShelfView&) = delete;
  ~BoringShelfView() override;

  // Runs the rebuild now instead of after the current task (tests).
  void RebuildForTesting() { Rebuild(); }

  // views::View:
  void AddedToWidget() override;
  void VisibilityChanged(views::View* starting_from, bool is_visible) override;

  // TabStripModelObserver:
  void OnTabStripModelChanged(
      TabStripModel* tab_strip_model,
      const TabStripModelChange& change,
      const TabStripSelectionChange& selection) override;
  void OnTabGroupChanged(const TabGroupChange& change) override;
  void OnTabStripModelDestroyed(TabStripModel* tab_strip_model) override;

  // ReadingListModelObserver:
  void ReadingListModelLoaded(const ReadingListModel* model) override;
  void ReadingListDidAddEntry(const ReadingListModel* model,
                              const GURL& url,
                              reading_list::EntrySource source) override;
  void ReadingListDidRemoveEntry(const ReadingListModel* model,
                                 const GURL& url) override;
  void ReadingListDidApplyChanges(ReadingListModel* model) override;

  // content::DownloadManager::Observer:
  void OnDownloadCreated(content::DownloadManager* manager,
                         download::DownloadItem* item) override;
  void ManagerGoingDown(content::DownloadManager* manager) override;

  // download::DownloadItem::Observer:
  void OnDownloadUpdated(download::DownloadItem* download) override;
  void OnDownloadDestroyed(download::DownloadItem* download) override;

 private:
  // Asks for a rebuild after the current task. Many events in a row cost one.
  void ScheduleRebuild();
  void Rebuild();

  // Builds one section: its heading and its rows, or nothing.
  std::unique_ptr<views::View> BuildPinned();
  std::unique_ptr<views::View> BuildGroups();
  std::unique_ptr<views::View> BuildEarlier();
  std::unique_ptr<views::View> BuildSaved();

  // What pressing a row does.
  void OpenUrl(const GURL& url, bool switch_to_open_tab);
  void ActivateItem(const ShelfItem& item);
  void ActivateOpenGroup(int first_tab_index);
  void ActivateSavedGroup(const std::string& guid);
  void ActivateDownload(const std::string& guid);
  void ShowAllEarlier();

  // The Shelf lists the regular profile's history of things; a private or
  // guest window shows Pinned and its own open groups only.
  bool IsRegular() const;

  raw_ptr<BrowserWindowInterface> browser_;
  bool rebuild_pending_ = false;
  bool earlier_expanded_ = false;

  PrefChangeRegistrar pref_registrar_;
  raw_ptr<TabStripModel> tabs_ = nullptr;
  base::ScopedObservation<ReadingListModel, ReadingListModelObserver>
      reading_list_{this};
  base::ScopedObservation<content::DownloadManager,
                          content::DownloadManager::Observer>
      downloads_{this};
  base::ScopedMultiSourceObservation<download::DownloadItem,
                                     download::DownloadItem::Observer>
      download_items_{this};

  base::WeakPtrFactory<BoringShelfView> weak_factory_{this};
};

}  // namespace boring::shelf

#endif  // CHROME_BROWSER_UI_VIEWS_SIDE_PANEL_BORING_SHELF_BORING_SHELF_VIEW_H_
