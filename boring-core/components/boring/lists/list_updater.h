// Copyright 2026 boring. BSD style license.

#ifndef COMPONENTS_BORING_LISTS_LIST_UPDATER_H_
#define COMPONENTS_BORING_LISTS_LIST_UPDATER_H_

#include <cstdint>
#include <memory>
#include <optional>
#include <string>
#include <string_view>
#include <vector>

#include "base/memory/scoped_refptr.h"
#include "base/memory/weak_ptr.h"
#include "base/no_destructor.h"
#include "base/sequence_checker.h"
#include "base/time/time.h"
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
// a stale list misses what people are actually being sent to this
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
// The manifest has to be signed by a key this browser was built with
// before anything in it is believed. The hashes in it catch a file that
// arrived corrupted; they say nothing about who wrote the manifest, and
// whoever can replace the lists on the release host can replace the
// manifest that describes them.
//
// Lives on the UI thread. Disk reads, hashing and writes go to the
// thread pool.
class ListUpdater {
 public:
  // How the last finished check went. Read off the disk, so it is the
  // same answer after a restart.
  struct Status {
    // When the last check finished, null when none ever has.
    base::Time checked_at;
    // Manifest version in use, 0 when no check has applied one.
    int version = 0;
    // The publisher said it built this bundle without one of its
    // sources. The lists are real but thinner than usual.
    bool degraded = false;
    // One word for how the last check ended: ok, network, signature,
    // manifest, content or stale. Empty when none has finished.
    std::string outcome;
  };

  static ListUpdater* GetInstance();

  ListUpdater(const ListUpdater&) = delete;
  ListUpdater& operator=(const ListUpdater&) = delete;

  // What the last check did. Looks at the disk, so call this somewhere
  // blocking is allowed. Anything showing how fresh the lists are
  // should say what this says and not what it hopes.
  static Status ReadStatus();

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

  // False while this build trusts no real publishing key. Lists then
  // change only when a newer version of the browser is installed, and
  // nothing is asked for.
  static bool CanUpdate();

  // True unless this build cannot update, the person turned updates off
  // in Protection, or the command line did.
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
    // Whether that bundle was a degraded one. Carried forward when a
    // check fails, so the recorded state keeps describing the lists
    // actually on disk rather than quietly calling them complete.
    bool degraded = false;
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
  // Notes that a check happened, which version it saw and how it went.
  static void RecordCheck(int version, bool degraded, std::string outcome);

  void OnLookedAtDisk(Local local);
  void OnManifest(std::optional<std::string> body);
  void OnManifestSignature(std::optional<std::string> body);
  // Reads a manifest whose signature has already been checked.
  void ApplyManifest();
  void FetchNextList();
  void OnListDownloaded(std::optional<std::string> body);
  void OnListSaved(bool saved);
  // Ends the check, recording why. Every path out goes through here.
  void FinishWith(std::string_view outcome);
  void Finish();

  scoped_refptr<network::SharedURLLoaderFactory> factory_;
  std::unique_ptr<network::SimpleURLLoader> loader_;
  Local local_;
  std::vector<Wanted> wanted_;
  // The manifest as it arrived, held while its signature is fetched.
  // Kept as the bytes that were served, because that is what was
  // signed, and re-encoding them would check a different thing.
  std::string manifest_;
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
  // What the verified manifest said about its own sources. False until
  // a manifest has been verified, so a check that never got that far
  // cannot claim to know anything about the bundle.
  bool degraded_ = false;
  // One word for how this check ended, written down when it does.
  std::string outcome_;

  SEQUENCE_CHECKER(sequence_checker_);

  base::WeakPtrFactory<ListUpdater> weak_factory_{this};
};

}  // namespace boring

#endif  // COMPONENTS_BORING_LISTS_LIST_UPDATER_H_
