// Copyright 2026 boring. BSD style license.

#ifndef COMPONENTS_BORING_ADBLOCK_BLOCKING_OFF_SITES_H_
#define COMPONENTS_BORING_ADBLOCK_BLOCKING_OFF_SITES_H_

#include <string>

#include "base/containers/flat_set.h"
#include "base/memory/ref_counted.h"
#include "base/memory/scoped_refptr.h"
#include "base/synchronization/lock.h"
#include "base/thread_annotations.h"

class GURL;

namespace content {
class BrowserContext;
}

namespace boring {

// One profile's sites with blocking turned off (prefs::kBlockingOffSites),
// copied so the checks that answer renderers off the UI thread can read
// it. Lives as long as the profile or the last check still holding it,
// whichever is later.
class BlockingOffSites : public base::RefCountedThreadSafe<BlockingOffSites> {
 public:
  // The copy for this profile, made on first use and brought up to date
  // from the pref on every call. UI thread only.
  static scoped_refptr<BlockingOffSites> ForContext(
      content::BrowserContext* context);

  BlockingOffSites();

  BlockingOffSites(const BlockingOffSites&) = delete;
  BlockingOffSites& operator=(const BlockingOffSites&) = delete;

  // True when blocking is off for the site of the page in the tab. Safe
  // on any thread.
  bool IsOff(const GURL& top_frame_url) const;

  // Replaces the copy.
  void Set(base::flat_set<std::string> sites);

 private:
  friend class base::RefCountedThreadSafe<BlockingOffSites>;
  ~BlockingOffSites();

  mutable base::Lock lock_;
  base::flat_set<std::string> sites_ GUARDED_BY(lock_);
};

}  // namespace boring

#endif  // COMPONENTS_BORING_ADBLOCK_BLOCKING_OFF_SITES_H_
