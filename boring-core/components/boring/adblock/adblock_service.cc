// Copyright 2026 boring. BSD style license.

#include "components/boring/adblock/adblock_service.h"

#include <string>
#include <utility>

#include "base/command_line.h"
#include "base/files/file_path.h"
#include "base/files/file_util.h"
#include "base/functional/bind.h"
#include "base/logging.h"
#include "base/no_destructor.h"
#include "base/path_service.h"
#include "base/task/thread_pool.h"
#include "components/boring/adblock/adblock_ffi.h"
#include "url/gurl.h"

namespace boring {

namespace {

// Filter lists are shipped next to the browser module in this folder.
constexpr base::FilePath::CharType kListDir[] = FILE_PATH_LITERAL("boring");
constexpr base::FilePath::CharType kListFile[] =
    FILE_PATH_LITERAL("easylist.txt");

constexpr char kDisableSwitch[] = "disable-boring-adblock";

}  // namespace

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
  bool expected = false;
  if (!load_started_.compare_exchange_strong(expected, true)) {
    return;
  }
  base::ThreadPool::PostTask(
      FROM_HERE, {base::MayBlock(), base::TaskPriority::USER_VISIBLE},
      base::BindOnce(&AdblockService::LoadOnBackgroundThread,
                     base::Unretained(this)));
}

void AdblockService::LoadOnBackgroundThread() {
  base::FilePath dir;
  if (!base::PathService::Get(base::DIR_MODULE, &dir)) {
    LOG(ERROR) << "boring adblock: no module dir";
    return;
  }
  base::FilePath path = dir.Append(kListDir).Append(kListFile);
  std::string rules;
  if (!base::ReadFileToString(path, &rules) || rules.empty()) {
    LOG(WARNING) << "boring adblock: no filter list at " << path
                 << ", blocking is off";
    return;
  }
  const BoringLibrary* lib = GetBoringLibrary();
  if (!lib) {
    return;
  }
  void* engine = lib->adblock_new(
      reinterpret_cast<const unsigned char*>(rules.data()), rules.size());
  if (!engine) {
    LOG(ERROR) << "boring adblock: engine failed to build";
    return;
  }
  engine_.store(engine, std::memory_order_release);
  VLOG(1) << "boring adblock: ready, " << rules.size() << " bytes of rules";
}

bool AdblockService::IsReady() const {
  return engine_.load(std::memory_order_acquire) != nullptr;
}

bool AdblockService::ShouldBlock(const GURL& url,
                                 const GURL& initiator,
                                 const std::string& request_type) {
  void* engine = engine_.load(std::memory_order_acquire);
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
  return lib->adblock_check(engine, url.spec().c_str(), source.c_str(),
                            request_type.c_str()) == 1;
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
