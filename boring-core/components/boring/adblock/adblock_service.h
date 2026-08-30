// Copyright 2026 boring. BSD style license.

#ifndef COMPONENTS_BORING_ADBLOCK_ADBLOCK_SERVICE_H_
#define COMPONENTS_BORING_ADBLOCK_ADBLOCK_SERVICE_H_

#include <atomic>
#include <string>

#include "base/no_destructor.h"
#include "services/network/public/mojom/fetch_api.mojom-shared.h"

class GURL;

namespace boring {

// Browser process owner of the ad blocking engine. Loads the filter
// lists from disk once, in the background, then answers ShouldBlock
// from any thread. Until the lists are loaded every request passes.
class AdblockService {
 public:
  static AdblockService* GetInstance();

  AdblockService(const AdblockService&) = delete;
  AdblockService& operator=(const AdblockService&) = delete;

  // Starts loading the filter lists if not started yet. Cheap to call
  // more than once. Call from any thread.
  void EnsureLoading();

  // True when the engine is ready.
  bool IsReady() const;

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

  std::atomic<bool> load_started_{false};
  std::atomic<void*> engine_{nullptr};
};

}  // namespace boring

#endif  // COMPONENTS_BORING_ADBLOCK_ADBLOCK_SERVICE_H_
