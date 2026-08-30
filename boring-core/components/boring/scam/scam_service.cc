// Copyright 2026 boring. BSD style license.

#include "components/boring/scam/scam_service.h"

#include <string>

#include "base/files/file_path.h"
#include "base/files/file_util.h"
#include "base/functional/bind.h"
#include "base/logging.h"
#include "base/path_service.h"
#include "base/task/thread_pool.h"
#include "url/gurl.h"

extern "C" {
void* boring_scamlist_new(const unsigned char* text, size_t len);
int boring_scamlist_contains(const void* list, const char* host);
size_t boring_scamlist_size(const void* list);
}

namespace boring {

namespace {
constexpr base::FilePath::CharType kListPath[] =
    FILE_PATH_LITERAL("boring/scamlist.txt");
}

// static
ScamService* ScamService::GetInstance() {
  static base::NoDestructor<ScamService> instance;
  return instance.get();
}

ScamService::ScamService() = default;

void ScamService::EnsureLoading() {
  bool expected = false;
  if (!load_started_.compare_exchange_strong(expected, true)) {
    return;
  }
  base::ThreadPool::PostTask(
      FROM_HERE, {base::MayBlock(), base::TaskPriority::USER_VISIBLE},
      base::BindOnce(&ScamService::LoadOnBackgroundThread,
                     base::Unretained(this)));
}

void ScamService::LoadOnBackgroundThread() {
  base::FilePath dir;
  if (!base::PathService::Get(base::DIR_MODULE, &dir)) {
    return;
  }
  std::string text;
  if (!base::ReadFileToString(dir.Append(kListPath), &text) || text.empty()) {
    LOG(WARNING) << "boring scam: no blocklist file, protection is off";
    return;
  }
  void* list = boring_scamlist_new(
      reinterpret_cast<const unsigned char*>(text.data()), text.size());
  if (!list) {
    LOG(ERROR) << "boring scam: blocklist failed to parse";
    return;
  }
  list_.store(list, std::memory_order_release);
  VLOG(1) << "boring scam: ready, " << boring_scamlist_size(list) << " hosts";
}

bool ScamService::IsReady() const {
  return list_.load(std::memory_order_acquire) != nullptr;
}

bool ScamService::ShouldBlock(const GURL& url) const {
  void* list = list_.load(std::memory_order_acquire);
  if (!list || !url.SchemeIsHTTPOrHTTPS() || !url.has_host()) {
    return false;
  }
  const std::string host = url.host();
  if (allowed_hosts_.count(host)) {
    return false;
  }
  return boring_scamlist_contains(list, host.c_str()) == 1;
}

void ScamService::AllowHostForSession(const std::string& host) {
  allowed_hosts_.insert(host);
}

}  // namespace boring
