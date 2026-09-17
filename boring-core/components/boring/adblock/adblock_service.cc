// Copyright 2026 boring. BSD style license.

#include "components/boring/adblock/adblock_service.h"

#include <string>
#include <utility>

#include "base/command_line.h"
#include "base/files/file.h"
#include "base/files/file_path.h"
#include "base/files/file_util.h"
#include "base/functional/bind.h"
#include "base/logging.h"
#include "base/memory/ref_counted.h"
#include "base/no_destructor.h"
#include "base/task/thread_pool.h"
#include "base/time/time.h"
#include "components/boring/adblock/adblock_ffi.h"
#include "components/boring/lists/list_paths.h"
#include "url/gurl.h"

namespace boring {

namespace {

constexpr char kDisableSwitch[] = "disable-boring-adblock";

// How often the file is looked at again. Long enough to cost nothing
// per request, short enough that refreshed lists are picked up without
// restarting the browser.
constexpr base::TimeDelta kCheckInterval = base::Minutes(30);

}  // namespace

AdblockEngine::AdblockEngine(void* handle) : handle_(handle) {}

AdblockEngine::~AdblockEngine() {
  if (!handle_) {
    return;
  }
  if (const BoringLibrary* lib = GetBoringLibrary()) {
    lib->adblock_free(handle_);
  }
}

// static
AdblockService* AdblockService::GetInstance() {
  static base::NoDestructor<AdblockService> instance;
  return instance.get();
}

AdblockService::AdblockService() = default;

// static
bool AdblockService::IsDisabled() {
  return base::CommandLine::ForCurrentProcess()->HasSwitch(kDisableSwitch);
}

void AdblockService::EnsureLoading() {
  const int64_t now_us =
      base::Time::Now().ToDeltaSinceWindowsEpoch().InMicroseconds();

  if (!load_started_.exchange(true)) {
    last_checked_us_.store(now_us, std::memory_order_relaxed);
    base::ThreadPool::PostTask(
        FROM_HERE, {base::MayBlock(), base::TaskPriority::USER_VISIBLE},
        base::BindOnce(&AdblockService::LoadOnBackgroundThread,
                       base::Unretained(this)));
    return;
  }

  // Already loaded once. Look for newer lists now and then, rate
  // limited so this never touches the disk on a per request path.
  int64_t last = last_checked_us_.load(std::memory_order_relaxed);
  if (now_us - last < kCheckInterval.InMicroseconds()) {
    return;
  }
  if (!last_checked_us_.compare_exchange_strong(last, now_us,
                                                std::memory_order_relaxed)) {
    return;  // Another thread is already doing the check.
  }
  base::ThreadPool::PostTask(
      FROM_HERE, {base::MayBlock(), base::TaskPriority::BEST_EFFORT},
      base::BindOnce(&AdblockService::LoadOnBackgroundThread,
                     base::Unretained(this)));
}

void AdblockService::LoadOnBackgroundThread() {
  auto fail = [this](const std::string& why) {
    base::AutoLock lock(lock_);
    // A failed refresh leaves the engine already in use alone. Only
    // report blocking as off when there is genuinely nothing loaded.
    if (!engine_) {
      status_ = Status::kFailed;
      status_message_ = why;
    }
  };

  // Whichever copy is newer: the one that shipped with the browser, or
  // one the updater has downloaded since.
  const base::FilePath path = GetListPath(ListKind::kFilters);
  base::File::Info info;
  if (path.empty() || !base::GetFileInfo(path, &info)) {
    LOG(ERROR) << "boring adblock: no filter list to load, ad and tracker "
                  "blocking is OFF";
    fail("the filter list file is missing");
    return;
  }
  const int64_t mtime_us =
      info.last_modified.ToDeltaSinceWindowsEpoch().InMicroseconds();
  {
    base::AutoLock lock(lock_);
    if (engine_ && mtime_us == loaded_mtime_us_) {
      return;  // Nothing has changed since we read it.
    }
  }

  std::string rules;
  if (!base::ReadFileToString(path, &rules) || rules.empty()) {
    LOG(ERROR) << "boring adblock: filter list at " << path
               << " is empty or unreadable, ad and tracker blocking is OFF";
    fail("the filter list is empty or unreadable");
    return;
  }
  const BoringLibrary* lib = GetBoringLibrary();
  if (!lib) {
    LOG(ERROR) << "boring adblock: the engine did not load, ad and tracker "
                  "blocking is OFF";
    fail("the engine did not load");
    return;
  }
  void* handle = lib->adblock_new(
      reinterpret_cast<const unsigned char*>(rules.data()), rules.size());
  if (!handle) {
    LOG(ERROR) << "boring adblock: engine failed to build, ad and tracker "
                  "blocking is OFF";
    fail("the filter lists could not be read");
    return;
  }

  auto built = base::MakeRefCounted<AdblockEngine>(handle);
  {
    base::AutoLock lock(lock_);
    engine_ = std::move(built);
    loaded_mtime_us_ = mtime_us;
    status_ = Status::kReady;
    status_message_.clear();
  }
  VLOG(1) << "boring adblock: ready, " << rules.size() << " bytes of rules";
}

scoped_refptr<AdblockEngine> AdblockService::current() const {
  base::AutoLock lock(lock_);
  return engine_;
}

bool AdblockService::IsReady() const {
  return status() == Status::kReady;
}

AdblockService::Status AdblockService::status() const {
  base::AutoLock lock(lock_);
  return status_;
}

std::string AdblockService::status_message() const {
  base::AutoLock lock(lock_);
  return status_message_;
}

base::Time AdblockService::list_time() const {
  base::AutoLock lock(lock_);
  if (loaded_mtime_us_ == 0) {
    return base::Time();
  }
  return base::Time::FromDeltaSinceWindowsEpoch(
      base::Microseconds(loaded_mtime_us_));
}

bool AdblockService::ShouldBlock(const GURL& url,
                                 const GURL& initiator,
                                 const std::string& request_type) {
  scoped_refptr<AdblockEngine> engine = current();
  if (!engine) {
    return false;
  }
  if (!url.SchemeIsHTTPOrHTTPS()) {
    return false;
  }
  const BoringLibrary* lib = GetBoringLibrary();
  if (!lib) {
    return false;
  }
  const std::string source = initiator.is_valid() ? initiator.spec() : "";
  return lib->adblock_check(engine->handle(), url.spec().c_str(),
                            source.c_str(), request_type.c_str()) == 1;
}

// static
const char* AdblockService::RequestTypeFromDestination(
    network::mojom::RequestDestination destination,
    const GURL& url) {
  using network::mojom::RequestDestination;
  switch (destination) {
    case RequestDestination::kScript:
    case RequestDestination::kWorker:
    case RequestDestination::kSharedWorker:
    case RequestDestination::kServiceWorker:
      return "script";
    case RequestDestination::kImage:
      return "image";
    case RequestDestination::kStyle:
    case RequestDestination::kXslt:
      return "stylesheet";
    case RequestDestination::kDocument:
      return "document";
    case RequestDestination::kFrame:
    case RequestDestination::kIframe:
    case RequestDestination::kFencedframe:
    case RequestDestination::kEmbed:
    case RequestDestination::kObject:
      return "subdocument";
    case RequestDestination::kFont:
      return "font";
    case RequestDestination::kAudio:
    case RequestDestination::kVideo:
    case RequestDestination::kTrack:
      return "media";
    case RequestDestination::kReport:
      return "ping";
    case RequestDestination::kEmpty:
      if (url.SchemeIsWSOrWSS()) {
        return "websocket";
      }
      return "xmlhttprequest";
    case RequestDestination::kJson:
      return "xmlhttprequest";
    default:
      return "other";
  }
}

}  // namespace boring
