// Copyright 2026 boring. BSD style license.

#ifndef COMPONENTS_BORING_SCAM_SCAM_SERVICE_H_
#define COMPONENTS_BORING_SCAM_SCAM_SERVICE_H_

#include <atomic>
#include <cstdint>
#include <string>

#include "base/memory/ref_counted.h"
#include "base/memory/scoped_refptr.h"
#include "base/no_destructor.h"
#include "base/synchronization/lock.h"
#include "base/thread_annotations.h"
#include "base/time/time.h"

class GURL;

namespace content {
class BrowserContext;
}  // namespace content

namespace boring {

// One built blocklist, reference counted.
//
// The list is rebuilt when the file on disk changes. Reference counting
// is what makes that safe: a thread part way through a lookup keeps the
// old list alive until it is done, so a refresh never pulls the ground
// out from under a check in progress.
class ScamBlocklist : public base::RefCountedThreadSafe<ScamBlocklist> {
 public:
  explicit ScamBlocklist(void* handle);

  ScamBlocklist(const ScamBlocklist&) = delete;
  ScamBlocklist& operator=(const ScamBlocklist&) = delete;

  void* handle() const { return handle_; }

 private:
  friend class base::RefCountedThreadSafe<ScamBlocklist>;
  ~ScamBlocklist();

  void* const handle_;
};

// Browser process owner of the scam and phishing blocklist. The list is
// plain hosts, one per line, shipped next to the browser and refreshed
// by tools/get_scamlist.py. Matching happens in the shared Rust core.
class ScamService {
 public:
  // Where the blocklist got to. A failure is worth telling someone
  // about: it means the browser is running with no scam protection.
  enum class Status {
    kLoading,  // not finished yet, or never started
    kReady,    // a list is loaded and being used
    kFailed,   // there is no list, so nothing is being blocked
  };

  static ScamService* GetInstance();

  ScamService(const ScamService&) = delete;
  ScamService& operator=(const ScamService&) = delete;

  // Starts loading the blocklist, and later re-reads it when the file on
  // disk has changed. Call from any thread; cheap to call often.
  void EnsureLoading();

  bool IsReady() const;

  // Where the blocklist got to, and a line explaining a failure.
  Status status() const;
  std::string status_message() const;

  // When the list in use was last written, so the Protection page can
  // say how old it is. A null Time when none is loaded.
  base::Time list_time() const;

  // True when this page should be blocked with a warning. Main thread.
  //
  // The context decides whose "continue anyway" choices count. They are
  // kept per profile on purpose: waving a warning through in an
  // ordinary window must not also wave it through in an incognito one.
  bool ShouldBlock(content::BrowserContext* context, const GURL& url) const;

  // Remembers that the user chose to continue to this host, for the
  // rest of this run, in this profile only. Main thread.
  void AllowHostForSession(content::BrowserContext* context,
                           const std::string& host);

 private:
  friend class base::NoDestructor<ScamService>;

  ScamService();
  ~ScamService() = default;

  void LoadOnBackgroundThread();

  // The list in use right now, or null when there is none.
  scoped_refptr<ScamBlocklist> current() const;

  std::atomic<bool> load_started_{false};
  // When the file was last looked at, so we do not stat it per request.
  std::atomic<int64_t> last_checked_us_{0};

  mutable base::Lock lock_;
  scoped_refptr<ScamBlocklist> list_ GUARDED_BY(lock_);
  // Modification time of the file the current list was built from.
  int64_t loaded_mtime_us_ GUARDED_BY(lock_) = 0;
  Status status_ GUARDED_BY(lock_) = Status::kLoading;
  std::string status_message_ GUARDED_BY(lock_);
};

}  // namespace boring

#endif  // COMPONENTS_BORING_SCAM_SCAM_SERVICE_H_
