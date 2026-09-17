// Copyright 2026 boring. BSD style license.

#include "components/boring/scam/scam_service.h"

#include <memory>
#include <set>
#include <string>

#include "base/files/file.h"
#include "base/files/file_path.h"
#include "base/files/file_util.h"
#include "base/functional/bind.h"
#include "base/logging.h"
#include "base/memory/ref_counted.h"
#include "base/path_service.h"
#include "base/supports_user_data.h"
#include "base/task/thread_pool.h"
#include "base/time/time.h"
#include "content/public/browser/browser_context.h"
#include "url/gurl.h"

#include "components/boring/adblock/adblock_ffi.h"

namespace boring {

namespace {
constexpr base::FilePath::CharType kListPath[] =
    FILE_PATH_LITERAL("boring/scamlist.txt");

// How often the file is looked at again. Long enough that it costs
// nothing per navigation, short enough that a refreshed list is picked
// up without restarting the browser.
constexpr base::TimeDelta kCheckInterval = base::Minutes(30);

// Hosts this profile chose to continue to, kept on the browser context
// so they die with the profile and never reach another one.
constexpr char kAllowedHostsKey[] = "boring_scam_allowed_hosts";

class AllowedHosts : public base::SupportsUserData::Data {
 public:
  std::set<std::string> hosts;
};

// Returns this profile's allow list, making it on first use. Pass
// create=false to look without creating one.
AllowedHosts* GetAllowedHosts(content::BrowserContext* context, bool create) {
  if (!context) {
    return nullptr;
  }
  auto* allowed =
      static_cast<AllowedHosts*>(context->GetUserData(kAllowedHostsKey));
  if (!allowed && create) {
    auto owned = std::make_unique<AllowedHosts>();
    allowed = owned.get();
    context->SetUserData(kAllowedHostsKey, std::move(owned));
  }
  return allowed;
}
}  // namespace

ScamBlocklist::ScamBlocklist(void* handle) : handle_(handle) {}

ScamBlocklist::~ScamBlocklist() {
  if (!handle_) {
    return;
  }
  if (const BoringLibrary* lib = GetBoringLibrary()) {
    lib->scamlist_free(handle_);
  }
}

// static
ScamService* ScamService::GetInstance() {
  static base::NoDestructor<ScamService> instance;
  return instance.get();
}

ScamService::ScamService() = default;

void ScamService::EnsureLoading() {
  const int64_t now_us =
      base::Time::Now().ToDeltaSinceWindowsEpoch().InMicroseconds();

  if (!load_started_.exchange(true)) {
    last_checked_us_.store(now_us, std::memory_order_relaxed);
    base::ThreadPool::PostTask(
        FROM_HERE, {base::MayBlock(), base::TaskPriority::USER_VISIBLE},
        base::BindOnce(&ScamService::LoadOnBackgroundThread,
                       base::Unretained(this)));
    return;
  }

  // Already loaded once. Look for a newer list now and then. Reading the
  // file's timestamp touches the disk, so it is rate limited here rather
  // than done on every navigation.
  int64_t last = last_checked_us_.load(std::memory_order_relaxed);
  if (now_us - last < kCheckInterval.InMicroseconds()) {
    return;
  }
  if (!last_checked_us_.compare_exchange_strong(last, now_us,
                                                std::memory_order_relaxed)) {
    // Another thread got there first, and is doing the check.
    return;
  }
  base::ThreadPool::PostTask(
      FROM_HERE, {base::MayBlock(), base::TaskPriority::BEST_EFFORT},
      base::BindOnce(&ScamService::LoadOnBackgroundThread,
                     base::Unretained(this)));
}

void ScamService::LoadOnBackgroundThread() {
  auto fail = [this](const std::string& why) {
    base::AutoLock lock(lock_);
    // A refresh that fails leaves the list already in use alone. Only
    // say protection is off when there is genuinely nothing loaded.
    if (!list_) {
      status_ = Status::kFailed;
      status_message_ = why;
    }
  };

  base::FilePath dir;
  if (!base::PathService::Get(base::DIR_MODULE, &dir)) {
    LOG(ERROR) << "boring scam: cannot find the browser folder, scam "
                  "protection is OFF";
    fail("cannot find the browser folder");
    return;
  }
  const base::FilePath path = dir.Append(kListPath);

  base::File::Info info;
  if (!base::GetFileInfo(path, &info)) {
    LOG(ERROR) << "boring scam: no blocklist at " << path
               << ", scam protection is OFF";
    fail("the blocklist file is missing");
    return;
  }
  const int64_t mtime_us =
      info.last_modified.ToDeltaSinceWindowsEpoch().InMicroseconds();
  {
    base::AutoLock lock(lock_);
    if (list_ && mtime_us == loaded_mtime_us_) {
      return;  // Nothing has changed since we read it.
    }
  }

  std::string text;
  if (!base::ReadFileToString(path, &text) || text.empty()) {
    LOG(ERROR) << "boring scam: blocklist at " << path
               << " is empty or unreadable, scam protection is OFF";
    fail("the blocklist file is empty or unreadable");
    return;
  }
  const BoringLibrary* lib = GetBoringLibrary();
  if (!lib) {
    LOG(ERROR) << "boring scam: the engine did not load, scam protection "
                  "is OFF";
    fail("the engine did not load");
    return;
  }
  void* handle = lib->scamlist_new(
      reinterpret_cast<const unsigned char*>(text.data()), text.size());
  if (!handle) {
    LOG(ERROR) << "boring scam: blocklist failed to parse, scam protection "
                  "is OFF";
    fail("the blocklist could not be read");
    return;
  }

  auto built = base::MakeRefCounted<ScamBlocklist>(handle);
  const size_t hosts = lib->scamlist_size(handle);
  {
    base::AutoLock lock(lock_);
    // Dropping the old reference here does not free anything that is
    // still being read; the last holder frees it.
    list_ = std::move(built);
    loaded_mtime_us_ = mtime_us;
    status_ = Status::kReady;
    status_message_.clear();
  }
  VLOG(1) << "boring scam: ready, " << hosts << " hosts";
}

scoped_refptr<ScamBlocklist> ScamService::current() const {
  base::AutoLock lock(lock_);
  return list_;
}

bool ScamService::IsReady() const {
  return status() == Status::kReady;
}

ScamService::Status ScamService::status() const {
  base::AutoLock lock(lock_);
  return status_;
}

std::string ScamService::status_message() const {
  base::AutoLock lock(lock_);
  return status_message_;
}

bool ScamService::ShouldBlock(content::BrowserContext* context,
                              const GURL& url) const {
  scoped_refptr<ScamBlocklist> list = current();
  if (!list || !url.SchemeIsHTTPOrHTTPS() || !url.has_host()) {
    return false;
  }
  const std::string host(url.host());
  const AllowedHosts* allowed = GetAllowedHosts(context, /*create=*/false);
  if (allowed && allowed->hosts.count(host)) {
    return false;
  }
  const BoringLibrary* lib = GetBoringLibrary();
  if (!lib) {
    return false;
  }
  return lib->scamlist_contains(list->handle(), host.c_str()) == 1;
}

void ScamService::AllowHostForSession(content::BrowserContext* context,
                                      const std::string& host) {
  if (AllowedHosts* allowed = GetAllowedHosts(context, /*create=*/true)) {
    allowed->hosts.insert(host);
  }
}

}  // namespace boring
