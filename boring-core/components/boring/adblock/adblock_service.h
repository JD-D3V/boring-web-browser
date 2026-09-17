// Copyright 2026 boring. BSD style license.

#ifndef COMPONENTS_BORING_ADBLOCK_ADBLOCK_SERVICE_H_
#define COMPONENTS_BORING_ADBLOCK_ADBLOCK_SERVICE_H_

#include <atomic>
#include <cstdint>
#include <string>

#include "base/memory/ref_counted.h"
#include "base/memory/scoped_refptr.h"
#include "base/no_destructor.h"
#include "base/synchronization/lock.h"
#include "base/thread_annotations.h"
#include "services/network/public/mojom/fetch_api.mojom-shared.h"

class GURL;

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

// Browser process owner of the ad blocking engine. Loads the filter
// lists from disk once, in the background, then answers ShouldBlock
// from any thread. Until the lists are loaded every request passes.
class AdblockService {
 public:
  // Where the filter lists got to. A failure means every request is
  // passing through unblocked, which is worth saying out loud.
  enum class Status {
    kLoading,  // not finished yet, or never started
    kReady,    // lists are loaded and being used
    kFailed,   // no lists, so nothing is being blocked
  };

  static AdblockService* GetInstance();

  AdblockService(const AdblockService&) = delete;
  AdblockService& operator=(const AdblockService&) = delete;

  // Starts loading the filter lists, and later re-reads them when the
  // file on disk has changed. Cheap to call often, from any thread.
  void EnsureLoading();

  // True when the engine is ready.
  bool IsReady() const;

  // Where the filter lists got to, and a line explaining a failure.
  Status status() const;
  std::string status_message() const;

  // Decides whether to block. Thread safe.
  bool ShouldBlock(const GURL& url,
                   const GURL& initiator,
                   const std::string& request_type);

  // Maps a fetch destination to the filter list request type name.
  static const char* RequestTypeFromDestination(
      network::mojom::RequestDestination destination,
      const GURL& url);

  // True when ad blocking is turned off for this run (test switch).
  static bool IsDisabled();

 private:
  friend class base::NoDestructor<AdblockService>;

  AdblockService();
  ~AdblockService() = default;

  void LoadOnBackgroundThread();

  // The engine in use right now, or null when there is none.
  scoped_refptr<AdblockEngine> current() const;

  std::atomic<bool> load_started_{false};
  // When the file was last looked at, so we do not stat it per request.
  std::atomic<int64_t> last_checked_us_{0};

  mutable base::Lock lock_;
  scoped_refptr<AdblockEngine> engine_ GUARDED_BY(lock_);
  // Modification time of the file the current engine was built from.
  int64_t loaded_mtime_us_ GUARDED_BY(lock_) = 0;
  Status status_ GUARDED_BY(lock_) = Status::kLoading;
  std::string status_message_ GUARDED_BY(lock_);
};

}  // namespace boring

#endif  // COMPONENTS_BORING_ADBLOCK_ADBLOCK_SERVICE_H_
