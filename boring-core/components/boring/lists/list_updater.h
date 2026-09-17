// Copyright 2026 boring. BSD style license.

#ifndef COMPONENTS_BORING_LISTS_LIST_UPDATER_H_
#define COMPONENTS_BORING_LISTS_LIST_UPDATER_H_

#include <cstdint>
#include <memory>
#include <optional>
#include <string>
#include <vector>

#include "base/memory/scoped_refptr.h"
#include "base/memory/weak_ptr.h"
#include "base/no_destructor.h"
#include "base/sequence_checker.h"
#include "components/boring/lists/list_paths.h"
#include "url/gurl.h"

class PrefService;

namespace network {
class SharedURLLoaderFactory;
class SimpleURLLoader;
}  // namespace network

namespace boring {

// Keeps the blocking lists current on a browser that is already
// installed.
//
// Lists are baked in when the browser is built, so without this they
// only ever get older: the ad rules stop matching new ad servers, and
// the scam list misses the sites people are actually being sent to this
// week. That is a safety failure rather than a cosmetic one, which is
// why it is on by default.
//
// This is also the only thing in the browser that talks to us, so it is
// kept to the least it can be. No identifier and no cookies are sent.
// Nothing is asked for at all while the lists already in use are fresh,
// so a browser installed this week stays silent. When they are not, one
// small manifest is read at most once a day, and a list is downloaded
// only when its hash says it actually changed.
//
// Lives on the UI thread. Disk reads, hashing and writes go to the
// thread pool.
class ListUpdater {
 public:
  static ListUpdater* GetInstance();

  ListUpdater(const ListUpdater&) = delete;
  ListUpdater& operator=(const ListUpdater&) = delete;

  // Fetches newer lists if there are any and it is time to look. Does
  // nothing when updates are off, when a check is already running, or
  // when the lists in use are recent enough to leave alone. Cheap to
  // call often, and safe to call on every new tab.
  //
  // Pass an ordinary profile's loader factory, never an incognito
  // one: this has nothing to do with what the person is browsing and
  // should not ride on a session that is meant to disappear.
  void MaybeCheck(const PrefService* prefs,
                  scoped_refptr<network::SharedURLLoaderFactory> factory);

  // Where lists are read from, ending in a slash. Our release host,
  // unless --boring-list-url points somewhere else for a test.
  static GURL GetFeedUrl();

  // True unless the person turned updates off in Protection, or the
  // command line did.
  static bool IsEnabled(const PrefService* prefs);

 private:
  friend class base::NoDestructor<ListUpdater>;

  // What we already have, worked out on the thread pool before anything
  // is asked for over the network.
  struct Local {
    // False when the lists in use are still fresh, or when the last
    // check was too recent to repeat. Nothing is sent in that case.
    bool worth_asking = false;
    // Hash of each downloaded list we hold, empty when we hold none.
    // A list whose hash already matches the manifest is not fetched.
    std::string filters_sha256;
    std::string scam_sha256;
    // Manifest version the last check applied, 0 when there was none.
    int version = 0;
  };

  // One list the manifest offers that we do not already have.
  struct Wanted {
    ListKind kind;
    std::string sha256;
    int64_t size = 0;
  };

  ListUpdater();
  ~ListUpdater();

  // These three run on the thread pool, not the UI thread.
  //
  // Reads what is on disk and decides whether to ask at all.
  static Local LookAtWhatWeHave();
  // Checks a downloaded list against the size and hash the manifest
  // promised, then puts it in place. False leaves the old list alone.
  static bool SaveList(ListKind kind,
                       std::string sha256,
                       int64_t size,
                       std::string body);
  // Notes that a check happened, and which version it saw.
  static void RecordCheck(int version);

  void OnLookedAtDisk(Local local);
  void OnManifest(std::optional<std::string> body);
  void FetchNextList();
  void OnListDownloaded(std::optional<std::string> body);
  void OnListSaved(bool saved);
  void Finish();

  scoped_refptr<network::SharedURLLoaderFactory> factory_;
  std::unique_ptr<network::SimpleURLLoader> loader_;
  Local local_;
  std::vector<Wanted> wanted_;
  size_t next_ = 0;
  bool running_ = false;
  // True once this check has actually gone to the network. Only then is
  // it worth writing down that a check happened.
  bool asked_ = false;
  // Cleared by anything that did not arrive or did not match, which
  // keeps the recorded version at the one still on disk.
  bool all_saved_ = true;
  // Version of the manifest being applied, written down once it is.
  int version_ = 0;

  SEQUENCE_CHECKER(sequence_checker_);

  base::WeakPtrFactory<ListUpdater> weak_factory_{this};
};

}  // namespace boring

#endif  // COMPONENTS_BORING_LISTS_LIST_UPDATER_H_
