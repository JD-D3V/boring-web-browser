// Copyright 2026 boring. BSD style license.

#include "chrome/browser/ui/views/boring/boring_earlier_tabs_service.h"

#include <algorithm>
#include <optional>
#include <set>
#include <utility>

#include "base/files/file_util.h"
#include "base/files/important_file_writer.h"
#include "base/functional/bind.h"
#include "base/functional/callback_helpers.h"
#include "base/task/task_traits.h"
#include "base/task/thread_pool.h"
#include "base/uuid.h"
#include "chrome/browser/history/history_service_factory.h"
#include "chrome/browser/performance_manager/policies/cannot_discard_reason.h"
#include "chrome/browser/performance_manager/policies/discard_eligibility_policy.h"
#include "chrome/browser/profiles/profile.h"
#include "chrome/browser/ui/browser_tabrestore.h"
#include "chrome/browser/ui/browser_window/public/browser_window_interface.h"
#include "chrome/browser/ui/browser_window/public/browser_window_interface_iterator.h"
#include "chrome/browser/ui/tabs/tab_enums.h"
#include "chrome/browser/ui/tabs/tab_strip_model.h"
#include "components/boring/core/boring_prefs.h"
#include "components/keyed_service/core/service_access_type.h"
#include "components/performance_manager/public/performance_manager.h"
#include "components/prefs/pref_service.h"
#include "components/sessions/core/serialized_navigation_entry.h"
#include "components/tabs/public/tab_interface.h"
#include "content/public/browser/navigation_controller.h"
#include "content/public/browser/navigation_entry.h"
#include "content/public/browser/visibility.h"
#include "content/public/browser/web_contents.h"
#include "ui/base/page_transition_types.h"

namespace boring::earlier {

namespace {

// At most this many tabs move in one check, so a big restore never empties
// the strip in one go.
constexpr size_t kMaxMovesPerCheck = 20;

// The address of this is the key the service is stored under on the profile.
const int kUserDataKey = 0;

// Something the discard rules would refuse for a reason that only says the
// tab is already asleep is no reason to keep it open.
bool IsHarmlessReason(
    performance_manager::policies::CannotDiscardReason reason) {
  using performance_manager::policies::CannotDiscardReason;
  return reason == CannotDiscardReason::kAlreadyDiscarded ||
         reason == CannotDiscardReason::kDiscardAttempted ||
         reason == CannotDiscardReason::kRecentlyVisible;
}

}  // namespace

// static
EarlierTabsService* EarlierTabsService::Get(Profile* profile) {
  if (!profile || profile->IsOffTheRecord() || profile->IsGuestSession() ||
      !profile->IsRegularProfile()) {
    return nullptr;
  }
  if (auto* existing = profile->GetUserData(&kUserDataKey)) {
    return static_cast<EarlierTabsService*>(existing);
  }
  auto owned = std::make_unique<EarlierTabsService>(profile);
  EarlierTabsService* service = owned.get();
  profile->SetUserData(&kUserDataKey, std::move(owned));
  return service;
}

EarlierTabsService::EarlierTabsService(Profile* profile)
    : profile_(profile),
      path_(profile->GetPath().AppendASCII(kFileName)),
      limits_(GetLimits()),
      file_runner_(base::ThreadPool::CreateSequencedTaskRunner(
          {base::MayBlock(), base::TaskPriority::BEST_EFFORT,
           base::TaskShutdownBehavior::BLOCK_SHUTDOWN})) {
  if (history::HistoryService* history = HistoryServiceFactory::GetForProfile(
          profile, ServiceAccessType::EXPLICIT_ACCESS)) {
    history_observation_.Observe(history);
  }
  file_runner_->PostTaskAndReplyWithResult(
      FROM_HERE, base::BindOnce(&EarlierTabsService::ReadFile, path_),
      base::BindOnce(&EarlierTabsService::OnFileRead,
                     weak_factory_.GetWeakPtr()));
}

EarlierTabsService::~EarlierTabsService() = default;

bool EarlierTabsService::IsEnabled() const {
  return profile_->GetPrefs()->GetBoolean(boring::prefs::kEarlierEnabled);
}

// static
EarlierTabsService::LoadedFile EarlierTabsService::ReadFile(
    const base::FilePath& path) {
  // The ".bad" copy an earlier build set aside is never kept.
  base::DeleteFile(path.AddExtension(FILE_PATH_LITERAL("bad")));
  LoadedFile file;
  file.exists = base::PathExists(path);
  if (file.exists &&
      !base::ReadFileToStringWithMaxSize(path, &file.text,
                                         32 * 1024 * 1024)) {
    file.read_failed = true;
  }
  return file;
}

// static
bool EarlierTabsService::WriteFile(const base::FilePath& path,
                                   std::string text) {
  // A temporary file, flushed, then renamed over the old one: the old file
  // is replaced only by a complete new one.
  return base::ImportantFileWriter::WriteFileAtomically(path, text);
}

// static
void EarlierTabsService::DeleteFiles(const base::FilePath& path) {
  // Deleted, never set aside: a kept copy would hold addresses and titles
  // that Clear, Forget, history deletion and the 30 days cannot reach.
  base::DeleteFile(path);
  base::DeleteFile(path.AddExtension(FILE_PATH_LITERAL("bad")));
}

void EarlierTabsService::OnFileRead(LoadedFile file) {
  loaded_ = true;
  if (file.read_failed) {
    // Cannot tell what is in it: show nothing, move nothing, write nothing.
    read_only_ = true;
  } else if (file.exists) {
    ParseResult parsed = ParseEarlierFile(file.text);
    switch (parsed.status) {
      case ParseStatus::kOk:
        entries_ = std::move(parsed.entries);
        break;
      case ParseStatus::kNewer:
        entries_ = std::move(parsed.entries);
        read_only_ = true;
        break;
      case ParseStatus::kCorrupt:
        file_runner_->PostTask(
            FROM_HERE, base::BindOnce(&EarlierTabsService::DeleteFiles, path_));
        paused_ = true;
        break;
    }
  }
  if (clear_when_loaded_) {
    clear_when_loaded_ = false;
    entries_.clear();
    file_runner_->PostTask(
        FROM_HERE, base::BindOnce(&EarlierTabsService::DeleteFiles, path_));
  }
  std::stable_sort(entries_.begin(), entries_.end(),
                   [](const EarlierEntry& a, const EarlierEntry& b) {
                     return a.moved > b.moved;
                   });
  if (!read_only_ &&
      RemoveExpired(&entries_, base::Time::Now(), limits_.keep) > 0) {
    WriteList(base::NullCallback());
  }
  NotifyChanged();
  // The first check waits, so session restore has finished.
  settle_timer_.Start(
      FROM_HERE, limits_.settle, base::BindOnce(&EarlierTabsService::StartTimers,
                                                 base::Unretained(this)));
}

void EarlierTabsService::StartTimers() {
  Check();
  check_timer_.Start(FROM_HERE, limits_.check,
                     base::BindRepeating(&EarlierTabsService::Check,
                                         base::Unretained(this)));
}

void EarlierTabsService::NotifyChanged() {
  for (Observer& observer : observers_) {
    observer.OnEarlierTabsChanged();
  }
}

void EarlierTabsService::WriteList(base::OnceCallback<void(bool)> done) {
  if (read_only_ || !loaded_) {
    if (done) {
      std::move(done).Run(false);
    }
    return;
  }
  if (!done) {
    done = base::DoNothing();
  }
  file_runner_->PostTaskAndReplyWithResult(
      FROM_HERE,
      base::BindOnce(&EarlierTabsService::WriteFile, path_,
                     SerializeEarlierFile(entries_)),
      std::move(done));
}

void EarlierTabsService::RemoveEntries(const std::vector<std::string>& ids) {
  std::erase_if(entries_, [&](const EarlierEntry& e) {
    return std::find(ids.begin(), ids.end(), e.id) != ids.end();
  });
}

bool EarlierTabsService::DiscardRulesAllow(
    content::WebContents* contents) const {
  using performance_manager::PerformanceManager;
  using performance_manager::policies::DiscardEligibilityPolicy;
  if (!PerformanceManager::IsAvailable()) {
    return false;
  }
  base::WeakPtr<performance_manager::PageNode> page =
      PerformanceManager::GetPrimaryPageNodeForWebContents(contents);
  if (!page) {
    return false;
  }
  DiscardEligibilityPolicy* policy =
      DiscardEligibilityPolicy::GetFromGraph(PerformanceManager::GetGraph());
  if (!policy) {
    return false;
  }
  // Chromium's own rules for a tab that must not be put to sleep: playing or
  // recently playing sound, picture in picture, camera, microphone, screen
  // sharing, mirroring, Bluetooth or USB, DevTools open, form input or edits,
  // notifications, an extension's protection, the person's never-sleep list,
  // and (with our tab_activity patch) a playing video or a running download.
  // No list of our own.
  std::vector<performance_manager::policies::CannotDiscardReason> reasons;
  policy->CanDiscardWithCustomRecentVisibilityWindow(
      page.get(), DiscardEligibilityPolicy::DiscardReason::PROACTIVE,
      base::TimeDelta(), &reasons);
  return std::all_of(reasons.begin(), reasons.end(), IsHarmlessReason);
}

bool EarlierTabsService::CanMove(BrowserWindowInterface* browser,
                                 TabStripModel* strip,
                                 int index,
                                 base::Time now) const {
  content::WebContents* contents = strip->GetWebContentsAt(index);
  if (!contents) {
    return false;
  }
  // Never the tab being looked at or any selected one, never pinned, never in
  // a group, never in a split view.
  if (index == strip->active_index() || strip->IsTabSelected(index) ||
      strip->IsTabPinned(index) || strip->GetTabGroupForTab(index)) {
    return false;
  }
  tabs::TabInterface* tab = strip->GetTabAtIndex(index);
  if (!tab || tab->IsPinned() || tab->IsSplit() || tab->GetGroup()) {
    return false;
  }
  if (contents->GetVisibility() == content::Visibility::VISIBLE) {
    return false;
  }
  if (now - contents->GetLastActiveTime() < limits_.idle) {
    return false;
  }
  // An ordinary web page that has finished loading: not chrome:, file:,
  // data:, the new tab page or an error page.
  if (!IsKeepableUrl(contents->GetLastCommittedURL()) ||
      contents->IsLoading()) {
    return false;
  }
  content::NavigationEntry* last =
      contents->GetController().GetLastCommittedEntry();
  if (!last || last->GetPageType() != content::PAGE_TYPE_NORMAL) {
    return false;
  }
  // No "leave this site?" question can appear and nothing waits on the page.
  if (contents->NeedToFireBeforeUnloadOrUnloadEvents()) {
    return false;
  }
  return DiscardRulesAllow(contents);
}

EarlierEntry EarlierTabsService::MakeEntry(content::WebContents* contents,
                                           base::Time now) const {
  EarlierEntry entry;
  entry.id = base::Uuid::GenerateRandomV4().AsLowercaseString();
  entry.moved = now;
  entry.last_used = contents->GetLastActiveTime();
  entry.url = WithoutCredentials(contents->GetLastCommittedURL());
  entry.title = CleanTitle(contents->GetTitle());
  content::NavigationController& controller = contents->GetController();
  const int current = controller.GetCurrentEntryIndex();
  const int from = std::max(0, current - kMaxNavigationsEachSide);
  const int to = std::min(controller.GetEntryCount() - 1,
                          current + kMaxNavigationsEachSide);
  int selected = -1;
  for (int i = from; i <= to; ++i) {
    content::NavigationEntry* nav = controller.GetEntryAtIndex(i);
    if (!nav || !IsKeepableUrl(nav->GetURL())) {
      continue;
    }
    if (i == current) {
      selected = static_cast<int>(entry.navigations.size());
    }
    entry.navigations.push_back(
        {WithoutCredentials(nav->GetURL()), CleanTitle(nav->GetTitle())});
  }
  if (entry.navigations.empty()) {
    entry.navigations.push_back({entry.url, entry.title});
    selected = 0;
  }
  entry.selected_index =
      selected >= 0 ? selected
                    : static_cast<int>(entry.navigations.size()) - 1;
  return entry;
}

void EarlierTabsService::Check() {
  if (!loaded_) {
    return;
  }
  const base::Time now = base::Time::Now();
  // Day 30: the entry goes, the page stays in History.
  if (!read_only_ && RemoveExpired(&entries_, now, limits_.keep) > 0) {
    WriteList(base::NullCallback());
    NotifyChanged();
  }
  // Off means nothing is recorded and no tab moves.
  if (!IsEnabled() || read_only_ || paused_ ||
      entries_.size() >= kMaxEntries) {
    return;
  }
  std::vector<Pending> moved;
  std::vector<EarlierEntry> added;
  const size_t room = kMaxEntries - entries_.size();
  for (BrowserWindowInterface* browser : GetAllBrowserWindowInterfaces()) {
    if (browser->GetProfile() != profile_ ||
        browser->GetType() != BrowserWindowInterface::TYPE_NORMAL) {
      continue;
    }
    TabStripModel* strip = browser->GetTabStripModel();
    for (int i = 0; i < strip->count(); ++i) {
      if (moved.size() >= kMaxMovesPerCheck || moved.size() >= room) {
        break;
      }
      if (!CanMove(browser, strip, i, now)) {
        continue;
      }
      content::WebContents* contents = strip->GetWebContentsAt(i);
      EarlierEntry entry = MakeEntry(contents, now);
      moved.push_back(
          {entry.id, contents->GetWeakPtr(), contents->GetLastCommittedURL()});
      added.push_back(std::move(entry));
    }
  }
  if (moved.empty()) {
    return;
  }
  // Write first, close second. Newest moved first.
  entries_.insert(entries_.begin(), std::make_move_iterator(added.begin()),
                  std::make_move_iterator(added.end()));
  WriteList(base::BindOnce(&EarlierTabsService::OnMoveWritten,
                           weak_factory_.GetWeakPtr(), std::move(moved)));
}

void EarlierTabsService::OnMoveWritten(std::vector<Pending> moved, bool ok) {
  std::vector<std::string> undo;
  if (!ok) {
    // The file is as it was and every tab is still open.
    for (const Pending& p : moved) {
      undo.push_back(p.id);
    }
    RemoveEntries(undo);
    NotifyChanged();
    return;
  }
  const base::Time now = base::Time::Now();
  for (const Pending& p : moved) {
    // A tab is closed only if its entry is still listed (Clear in between
    // would otherwise lose it), it is still there, still eligible and still
    // on the same page.
    const bool listed =
        std::any_of(entries_.begin(), entries_.end(),
                    [&](const EarlierEntry& e) { return e.id == p.id; });
    bool closed = false;
    content::WebContents* contents = p.contents.get();
    if (listed && contents) {
      for (BrowserWindowInterface* browser : GetAllBrowserWindowInterfaces()) {
        if (browser->GetProfile() != profile_) {
          continue;
        }
        TabStripModel* strip = browser->GetTabStripModel();
        const int index = strip->GetIndexOfWebContents(contents);
        if (index == TabStripModel::kNoTab) {
          continue;
        }
        if (browser->GetType() == BrowserWindowInterface::TYPE_NORMAL &&
            contents->GetLastCommittedURL() == p.url &&
            CanMove(browser, strip, index, now)) {
          // No "recently closed" record, so Ctrl+Shift+T cannot bring back a
          // second copy.
          strip->CloseWebContentsAt(index, TabCloseTypes::CLOSE_NONE);
          closed = true;
        }
        break;
      }
    }
    if (!closed && listed) {
      undo.push_back(p.id);
    }
  }
  if (!undo.empty()) {
    RemoveEntries(undo);
    WriteList(base::NullCallback());
  }
  NotifyChanged();
}

void EarlierTabsService::Reopen(const std::string& id,
                                BrowserWindowInterface* into) {
  auto it = std::find_if(entries_.begin(), entries_.end(),
                         [&](const EarlierEntry& e) { return e.id == id; });
  if (it == entries_.end() || !into || into->GetProfile() != profile_) {
    return;
  }
  // Only web pages, whatever the file says: an ordinary navigation, never a
  // script or an internal page.
  std::vector<sessions::SerializedNavigationEntry> navigations;
  int selected = 0;
  for (size_t i = 0; i < it->navigations.size(); ++i) {
    const EarlierNav& nav = it->navigations[i];
    if (!IsKeepableUrl(nav.url)) {
      continue;
    }
    sessions::SerializedNavigationEntry entry;
    entry.set_index(static_cast<int>(navigations.size()));
    entry.set_virtual_url(nav.url);
    entry.set_title(nav.title);
    entry.set_transition_type(ui::PAGE_TRANSITION_LINK);
    if (static_cast<int>(i) == it->selected_index) {
      selected = static_cast<int>(navigations.size());
    }
    navigations.push_back(std::move(entry));
  }
  if (navigations.empty()) {
    return;
  }
  content::WebContents* contents = chrome::AddRestoredTab(
      into, navigations, into->GetTabStripModel()->count(), selected,
      std::string(), std::nullopt, /*select=*/true, /*pin=*/false,
      base::TimeTicks(), base::Time(), /*storage_namespace=*/nullptr,
      sessions::SerializedUserAgentOverride(), {},
      /*from_session_restore=*/false, /*is_active_browser=*/std::nullopt);
  if (!contents) {
    return;
  }
  // The tab exists; only now does the entry leave the list. A crash in
  // between leaves both, a duplicate and never a loss. A file from a newer
  // build is never written, so its entry stays listed.
  if (!read_only_) {
    RemoveEntries({id});
    WriteList(base::NullCallback());
  }
  NotifyChanged();
}

void EarlierTabsService::ClearAll() {
  if (!loaded_ || read_only_) {
    return;
  }
  entries_.clear();
  file_runner_->PostTask(
      FROM_HERE, base::BindOnce(&EarlierTabsService::DeleteFiles, path_));
  WriteList(base::NullCallback());
  NotifyChanged();
}

void EarlierTabsService::OnHistoryDeletions(
    history::HistoryService* history_service,
    const history::DeletionInfo& info) {
  // History expiring by age does not touch this list: it has its own 30 days.
  if (info.is_from_expiration()) {
    return;
  }
  if (info.IsAllHistory() && (!loaded_ || read_only_)) {
    // Not read yet, or a file this build may not rewrite: the whole list
    // goes all the same (on reading, or now).
    if (!loaded_) {
      clear_when_loaded_ = true;
    } else {
      entries_.clear();
      file_runner_->PostTask(
          FROM_HERE, base::BindOnce(&EarlierTabsService::DeleteFiles, path_));
      NotifyChanged();
    }
    return;
  }
  if (!loaded_ || read_only_) {
    return;
  }
  if (info.IsAllHistory()) {
    file_runner_->PostTask(
        FROM_HERE, base::BindOnce(&EarlierTabsService::DeleteFiles, path_));
  }
  const history::DeletionTimeRange& range = info.time_range();
  const std::set<GURL>* restrict = info.restrict_urls().has_value()
                                       ? &*info.restrict_urls()
                                       : nullptr;
  // Any page of the entry counts, its back and forward list too: a page
  // deleted from History must not stay on disk or come back on Reopen.
  auto deleted = [&](const GURL& url) {
    if (range.IsValid() && restrict && restrict->contains(url)) {
      return true;
    }
    return std::ranges::any_of(info.deleted_rows(),
                               [&](const history::URLRow& row) {
                                 return WithoutCredentials(row.url()) == url;
                               });
  };
  const size_t before = entries_.size();
  std::erase_if(entries_, [&](const EarlierEntry& e) {
    if (info.IsAllHistory()) {
      return true;
    }
    if (range.IsValid() && !restrict && e.last_used >= range.begin() &&
        e.last_used <= range.end()) {
      return true;
    }
    return deleted(e.url) ||
           std::ranges::any_of(e.navigations, [&](const EarlierNav& nav) {
             return deleted(nav.url);
           });
  });
  if (entries_.size() != before) {
    WriteList(base::NullCallback());
    NotifyChanged();
  }
}

void EarlierTabsService::HistoryServiceBeingDeleted(
    history::HistoryService* history_service) {
  history_observation_.Reset();
}

}  // namespace boring::earlier
