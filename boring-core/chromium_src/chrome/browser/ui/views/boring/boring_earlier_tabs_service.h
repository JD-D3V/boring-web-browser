// Copyright 2026 boring. BSD style license.

#ifndef CHROME_BROWSER_UI_VIEWS_BORING_BORING_EARLIER_TABS_SERVICE_H_
#define CHROME_BROWSER_UI_VIEWS_BORING_BORING_EARLIER_TABS_SERVICE_H_

#include <memory>
#include <string>
#include <vector>

#include "base/files/file_path.h"
#include "base/memory/raw_ptr.h"
#include "base/memory/weak_ptr.h"
#include "base/observer_list.h"
#include "base/observer_list_types.h"
#include "base/scoped_observation.h"
#include "base/supports_user_data.h"
#include "base/task/sequenced_task_runner.h"
#include "base/timer/timer.h"
#include "components/boring/earlier/earlier_store.h"
#include "components/history/core/browser/history_service.h"
#include "components/history/core/browser/history_service_observer.h"

class BrowserWindowInterface;
class Profile;
class TabStripModel;

namespace content {
class WebContents;
}

namespace boring::earlier {

// Earlier tabs (ledger item 16, spec earlier.md). One per regular profile;
// private and guest profiles never get one, so nothing from them is ever
// recorded. It owns the list, the file the list lives in, and the mover that
// takes tabs off the strip.
//
// The rule it is built around: a tab is never lost. A tab is written to the
// file first and closed second; if the write fails or the tab changes in the
// meantime it stays open. A crash in between leaves the tab in both places,
// which is a duplicate and never a loss.
//
// Created the first time a normal window of the profile asks for it (the
// chip does, as the window is built), owned by the profile.
class EarlierTabsService : public base::SupportsUserData::Data,
                           public history::HistoryServiceObserver {
 public:
  class Observer : public base::CheckedObserver {
   public:
    virtual void OnEarlierTabsChanged() = 0;
  };

  // The profile's service, created on first use. Null for a private, guest or
  // system profile.
  static EarlierTabsService* Get(Profile* profile);

  explicit EarlierTabsService(Profile* profile);
  EarlierTabsService(const EarlierTabsService&) = delete;
  EarlierTabsService& operator=(const EarlierTabsService&) = delete;
  ~EarlierTabsService() override;

  // True once the file has been read. Until then the list is empty and
  // nothing moves.
  bool IsLoaded() const { return loaded_; }
  // True when a newer build wrote the file (or it could not be read): the
  // entries are shown, tabs never move, and the file is never written.
  bool IsReadOnly() const { return read_only_; }
  // Whether the switch in Settings is on.
  bool IsEnabled() const;

  size_t count() const { return entries_.size(); }
  // Newest moved first.
  const std::vector<EarlierEntry>& entries() const { return entries_; }

  // Opens the entry in a new tab at the end of `into`, selected, ungrouped
  // and unpinned. The entry is removed only after the tab exists.
  void Reopen(const std::string& id, BrowserWindowInterface* into);

  // Removes every entry for good. Open tabs are not touched.
  void ClearAll();

  void AddObserver(Observer* observer) { observers_.AddObserver(observer); }
  void RemoveObserver(Observer* observer) {
    observers_.RemoveObserver(observer);
  }

  // One pass of the mover now, ignoring the timers (tests only through the
  // short timer switches; there is no other way in).
  void CheckForTesting() { Check(); }

 private:
  struct Pending {
    std::string id;
    base::WeakPtr<content::WebContents> contents;
    GURL url;
  };

  struct LoadedFile {
    bool exists = false;
    bool read_failed = false;
    std::string text;
  };

  static LoadedFile ReadFile(const base::FilePath& path);
  static bool WriteFile(const base::FilePath& path, std::string text);
  static void MoveAside(const base::FilePath& path);

  void OnFileRead(LoadedFile file);
  void StartTimers();
  void Check();
  bool CanMove(BrowserWindowInterface* browser,
               TabStripModel* strip,
               int index,
               base::Time now) const;
  bool DiscardRulesAllow(content::WebContents* contents) const;
  EarlierEntry MakeEntry(content::WebContents* contents, base::Time now) const;
  void OnMoveWritten(std::vector<Pending> moved, bool ok);
  void WriteList(base::OnceCallback<void(bool)> done);
  void RemoveEntries(const std::vector<std::string>& ids);
  void NotifyChanged();

  // history::HistoryServiceObserver:
  void OnHistoryDeletions(history::HistoryService* history_service,
                          const history::DeletionInfo& deletion_info) override;
  void HistoryServiceBeingDeleted(
      history::HistoryService* history_service) override;

  const raw_ptr<Profile> profile_;
  const base::FilePath path_;
  const EarlierLimits limits_;
  scoped_refptr<base::SequencedTaskRunner> file_runner_;

  bool loaded_ = false;
  bool read_only_ = false;
  // A corrupt file was set aside this run: no tab moves until the next run.
  bool paused_ = false;
  std::vector<EarlierEntry> entries_;

  base::OneShotTimer settle_timer_;
  base::RepeatingTimer check_timer_;
  base::ObserverList<Observer> observers_;
  base::ScopedObservation<history::HistoryService,
                          history::HistoryServiceObserver>
      history_observation_{this};
  base::WeakPtrFactory<EarlierTabsService> weak_factory_{this};
};

}  // namespace boring::earlier

#endif  // CHROME_BROWSER_UI_VIEWS_BORING_BORING_EARLIER_TABS_SERVICE_H_
