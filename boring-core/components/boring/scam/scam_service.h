// Copyright 2026 boring. BSD style license.

#ifndef COMPONENTS_BORING_SCAM_SCAM_SERVICE_H_
#define COMPONENTS_BORING_SCAM_SCAM_SERVICE_H_

#include <atomic>
#include <set>
#include <string>

#include "base/no_destructor.h"

class GURL;

namespace boring {

// Browser process owner of the scam and phishing blocklist. The list is
// plain hosts, one per line, shipped next to the browser and refreshed
// by tools/get_scamlist.py. Matching happens in the shared Rust core.
class ScamService {
 public:
  static ScamService* GetInstance();

  ScamService(const ScamService&) = delete;
  ScamService& operator=(const ScamService&) = delete;

  // Starts loading the blocklist if not started yet. Call from any
  // thread; cheap when already called.
  void EnsureLoading();

  bool IsReady() const;

  // True when this page should be blocked with a warning. Main thread.
  bool ShouldBlock(const GURL& url) const;

  // Remembers that the user chose to continue to this host, for the
  // rest of this run. Main thread.
  void AllowHostForSession(const std::string& host);

 private:
  friend class base::NoDestructor<ScamService>;

  ScamService();
  ~ScamService() = default;

  void LoadOnBackgroundThread();

  std::atomic<bool> load_started_{false};
  std::atomic<void*> list_{nullptr};

  // Hosts the user chose to continue to. Main thread only.
  std::set<std::string> allowed_hosts_;
};

}  // namespace boring

#endif  // COMPONENTS_BORING_SCAM_SCAM_SERVICE_H_
