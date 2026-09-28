// Copyright 2026 boring. BSD style license.

#ifndef COMPONENTS_BORING_ADBLOCK_ADBLOCK_SERVICE_H_
#define COMPONENTS_BORING_ADBLOCK_ADBLOCK_SERVICE_H_

#include <atomic>
#include <cstdint>
#include <map>
#include <set>
#include <string>
#include <string_view>
#include <utility>
#include <vector>

#include "base/files/file_path.h"
#include "base/memory/ref_counted.h"
#include "base/memory/scoped_refptr.h"
#include "base/no_destructor.h"
#include "base/synchronization/lock.h"
#include "base/task/sequenced_task_runner.h"
#include "base/thread_annotations.h"
#include "base/time/time.h"
#include "components/boring/adblock/mojom/adblock.mojom.h"
#include "services/network/public/mojom/fetch_api.mojom-shared.h"

class GURL;

namespace content {
class BrowserContext;
}

namespace boring {

// One built filter engine, reference counted so the lists can be
// rebuilt while another thread is part way through a check. The last
// holder frees it, so a refresh never pulls the engine out from under a
// request that is already using it.
class AdblockEngine : public base::RefCountedThreadSafe<AdblockEngine> {
 public:
  explicit AdblockEngine(void* handle);

  AdblockEngine(const AdblockEngine&) = delete;
  AdblockEngine& operator=(const AdblockEngine&) = delete;

  void* handle() const { return handle_; }

 private:
  friend class base::RefCountedThreadSafe<AdblockEngine>;
  ~AdblockEngine();

  void* const handle_;
};

// The optional lists a profile has turned on, on top of the main ones
// (EasyList and uBO's lists), which are always in use.
struct EnabledLists {
  EnabledLists();
  EnabledLists(const EnabledLists&);
  EnabledLists& operator=(const EnabledLists&);
  ~EnabledLists();

  bool cookie_notices = false;        // prefs::kBoringHideCookieNotices
  std::vector<std::string> regional;  // prefs::kBoringRegionalLists
  bool aggressive = false;            // prefs::kBoringBlockingLevel is 1
  // The profile's own rules (prefs::kBoringCustomRules), built into an
  // engine of their own. Null when there are none, or while they are
  // being built.
  scoped_refptr<AdblockEngine> custom;
};

// One profile's EnabledLists, copied from its prefs so the checks that
// answer renderers off the UI thread can read them. Refreshed the same
// way as BlockingOffSites, on every navigation, so a change on the
// Protection page is picked up by the next page load.
class ProfileLists : public base::RefCountedThreadSafe<ProfileLists> {
 public:
  // The copy for this profile, made on first use and brought up to date
  // from the prefs on every call. UI thread only.
  static scoped_refptr<ProfileLists> ForContext(
      content::BrowserContext* context);

  ProfileLists();

  ProfileLists(const ProfileLists&) = delete;
  ProfileLists& operator=(const ProfileLists&) = delete;

  // Safe on any thread. Get() includes the custom rules engine; Set()
  // leaves it alone.
  EnabledLists Get() const;
  void Set(EnabledLists lists);

  // Notes the custom rules text the prefs hold now. True when it differs
  // from the last text noted, meaning the engine must be built again.
  bool NoteCustomRules(const std::string& text);
  // Puts in the engine built from `text`, unless the rules changed again
  // while it was being built. Null for no rules.
  void SetCustomEngine(const std::string& text,
                       scoped_refptr<AdblockEngine> engine);

 private:
  friend class base::RefCountedThreadSafe<ProfileLists>;
  ~ProfileLists();

  mutable base::Lock lock_;
  EnabledLists lists_ GUARDED_BY(lock_);
  // The newest custom rules text noted, and the engine built from the
  // text it was built from, which may lag behind for a moment.
  std::string custom_text_ GUARDED_BY(lock_);
  bool custom_noted_ GUARDED_BY(lock_) = false;
  scoped_refptr<AdblockEngine> custom_ GUARDED_BY(lock_);
};

// Browser process owner of the ad blocking engines. Loads the filter
// lists from disk in the background, then answers from any thread.
// Until the lists are loaded every request passes and no page gets any
// cosmetic filters.
//
// The lists are split over several engines so that turning an optional
// list on or off never rebuilds the big one:
//   main        easylist.txt (standard) + ubo.txt (trusted), always used
//   cookies     cookies.txt, only for profiles hiding cookie notices
//   regional    one engine per regional\<id>.txt, only where chosen
//   aggressive  aggressive-ubo.txt (trusted) + aggressive-fanboy.txt
//               (standard), only for profiles on the Aggressive level
//   custom      a profile's own rules, standard permissions, one engine
//               per profile, checked last so its exceptions win
// Optional engines are built the first time a profile asks for them.
// All engines share one copy of resources.json, the one that shipped
// with the browser: a list download never changes the scriptlets.
//
// Engines built from list files are cached on disk, serialized, keyed
// on the lists' SHA-256s, the adblock crate version and a format
// number, so a start with unchanged lists loads instead of parsing.
class AdblockService {
 public:
  // Where the filter lists got to. A failure means every request is
  // passing through unblocked, which is worth saying out loud.
  enum class Status {
    kLoading,  // not finished yet, or never started
    kReady,    // lists are loaded and being used
    kFailed,   // no lists, so nothing is being blocked
  };

  // What to do with one request.
  struct Decision {
    Decision();
    Decision(const Decision&);
    Decision& operator=(const Decision&);
    ~Decision();

    bool block = false;
    // Set only when blocking: a data: URL to serve in place of the
    // request, from a $redirect rule.
    std::string redirect;
  };

  static AdblockService* GetInstance();

  AdblockService(const AdblockService&) = delete;
  AdblockService& operator=(const AdblockService&) = delete;

  // Starts loading the filter lists, and later re-reads them when a
  // file on disk has changed. Cheap to call often, from any thread.
  void EnsureLoading();

  // Starts building the optional engines `lists` names, if they are not
  // built or on their way. Called when a profile's prefs are read, which
  // happens before its first page, so the cookie and regional lists are
  // ready with the main ones instead of one page late.
  void WantLists(const EnabledLists& lists);

  // True when the main engine is ready.
  bool IsReady() const;

  // Where the filter lists got to, and a line explaining a failure.
  Status status() const;
  std::string status_message() const;

  // When the newest of the main lists in use was written, so the
  // Protection page can say how old the rules are. A null Time when
  // none is loaded.
  base::Time list_time() const;

  // Decides whether to block, and what to serve instead. Checks the
  // main engine and the optional ones in `lists` as one, the way uBO
  // checks all its lists together: an exception in any list cancels a
  // block from another, and an $important block cancels every
  // exception. Thread safe.
  Decision Check(const GURL& url,
                 const GURL& initiator,
                 const std::string& request_type,
                 const EnabledLists& lists);

  // The same, main engine only, block or not.
  bool ShouldBlock(const GURL& url,
                   const GURL& initiator,
                   const std::string& request_type);

  // Cosmetic filters for a frame at `url`, merged across the engines in
  // use. Null when the main engine is not ready or `url` is not http or
  // https. Thread safe.
  mojom::UrlCosmeticResourcesPtr GetCosmeticResources(
      const GURL& url,
      const EnabledLists& lists);

  // Generic hide selectors for class names and ids seen on a page.
  // Thread safe.
  std::vector<std::string> GetHiddenClassIdSelectors(
      const std::vector<std::string>& classes,
      const std::vector<std::string>& ids,
      const std::vector<std::string>& exceptions,
      const EnabledLists& lists);

  // Builds `lists`' custom rules engine from `text` in the background
  // and hands it to them when done. Empty text clears it.
  void BuildCustomRules(scoped_refptr<ProfileLists> lists, std::string text);

  // Maps a fetch destination to the filter list request type name.
  static const char* RequestTypeFromDestination(
      network::mojom::RequestDestination destination,
      const GURL& url);

  // True when ad blocking is turned off for this run (test switch).
  static bool IsDisabled();

 private:
  friend class base::NoDestructor<AdblockService>;

  // The files one engine was built from, by path and write time, so a
  // refresh can tell whether it needs rebuilding.
  using Sources = std::map<base::FilePath, int64_t>;

  AdblockService();
  ~AdblockService();

  // Runs on load_runner_ only, so two loads never race.
  void LoadOnBackgroundThread();
  void LoadResources();
  void LoadMain();
  void LoadCookies();
  void LoadRegional(const std::string& id);
  void LoadAggressive();
  void BuildCustomOnBackgroundThread(scoped_refptr<ProfileLists> lists,
                                     std::string text);

  // Builds one engine from the lists given, or returns null. Reads the
  // files and records what it read in `sources`. Loads the engine from
  // the cache file `cache_name` when it was built from the same lists,
  // and writes it there when it had to be built. load_runner_ only.
  scoped_refptr<AdblockEngine> Build(
      const std::vector<std::pair<base::FilePath, bool>>& lists,
      Sources* sources,
      std::string_view cache_name);

  // The engines to ask for `lists`, main first. Empty when the main one
  // is not ready. Asks for any optional engine not built yet.
  std::vector<scoped_refptr<AdblockEngine>> EnginesFor(
      const EnabledLists& lists);

  void PostLoad();

  const scoped_refptr<base::SequencedTaskRunner> load_runner_;

  std::atomic<bool> load_started_{false};
  // When the files were last looked at, so we do not stat them per
  // request.
  std::atomic<int64_t> last_checked_us_{0};

  // Only touched on load_runner_. The parsed resources.json handed to
  // every engine built, or null. Never freed while the service lives:
  // the service itself is never destroyed.
  void* resources_ = nullptr;
  int64_t resources_mtime_us_ = 0;

  mutable base::Lock lock_;
  scoped_refptr<AdblockEngine> main_ GUARDED_BY(lock_);
  Sources main_sources_ GUARDED_BY(lock_);
  scoped_refptr<AdblockEngine> cookies_ GUARDED_BY(lock_);
  Sources cookies_sources_ GUARDED_BY(lock_);
  std::map<std::string, scoped_refptr<AdblockEngine>> regional_
      GUARDED_BY(lock_);
  std::map<std::string, Sources> regional_sources_ GUARDED_BY(lock_);
  scoped_refptr<AdblockEngine> aggressive_ GUARDED_BY(lock_);
  Sources aggressive_sources_ GUARDED_BY(lock_);
  // Optional engines some profile has asked for. Kept once asked, so a
  // list that is missing now is picked up when it appears.
  bool cookies_wanted_ GUARDED_BY(lock_) = false;
  bool aggressive_wanted_ GUARDED_BY(lock_) = false;
  std::set<std::string> regional_wanted_ GUARDED_BY(lock_);
  // Newest write time of the main lists in use.
  int64_t loaded_mtime_us_ GUARDED_BY(lock_) = 0;
  Status status_ GUARDED_BY(lock_) = Status::kLoading;
  std::string status_message_ GUARDED_BY(lock_);
};

}  // namespace boring

#endif  // COMPONENTS_BORING_ADBLOCK_ADBLOCK_SERVICE_H_
