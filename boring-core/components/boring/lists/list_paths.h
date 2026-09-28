// Copyright 2026 boring. BSD style license.

#ifndef COMPONENTS_BORING_LISTS_LIST_PATHS_H_
#define COMPONENTS_BORING_LISTS_LIST_PATHS_H_

#include <optional>
#include <string>
#include <string_view>
#include <vector>

#include "base/files/file_path.h"
#include "base/time/time.h"

namespace boring {

// The lists the browser blocks with. Each is one file, kept under the
// same name in both places a list can live.
enum class ListKind {
  kFilters,    // easylist.txt: EasyList and EasyPrivacy
  kScam,       // scamlist.txt: scam and phishing hosts
  kUbo,        // ubo.txt: uBlock filters, Quick fixes, Privacy, Unbreak
  kCookies,    // cookies.txt: cookie notices, used only when asked for
  kResources,  // resources.json: scriptlets and $redirect stubs. Only
               // ever the shipped copy; list downloads never carry it.
  // aggressive-ubo.txt: uBlock filters, Annoyances. Trusted like ubo.txt.
  // Used only on the Aggressive blocking level.
  kAggressiveUbo,
  // aggressive-fanboy.txt: Fanboy's Social, Newsletter and Notifications
  // lists. Used only on the Aggressive blocking level.
  kAggressiveFanboy,
};

// Every kind, for code that has to go through them all.
inline constexpr ListKind kAllListKinds[] = {
    ListKind::kFilters,       ListKind::kScam,
    ListKind::kUbo,           ListKind::kCookies,
    ListKind::kResources,     ListKind::kAggressiveUbo,
    ListKind::kAggressiveFanboy,
};

// The file a list is kept in. The same name wherever it lives, and the
// name the manifest uses for it.
const char* ListFileName(ListKind kind);

// The list a manifest entry names, or nothing when the name is not one
// of ours.
std::optional<ListKind> ListKindFromName(std::string_view name);

// The copy of a list that shipped with the browser. That folder is read
// only once the browser is installed, which is the whole reason there
// is a second one.
base::FilePath GetShippedListPath(ListKind kind);

// Where downloaded lists are kept: one folder per machine, outside the
// install, writable by the person running the browser. Shared by every
// profile on purpose, since a blocklist is the same for all of them and
// nothing in it says anything about who was browsing.
//
// Empty when the folder cannot be worked out.
base::FilePath GetDownloadedListDir();
base::FilePath GetDownloadedListPath(ListKind kind);

// The copy the browser should read: whichever of the two was written
// last. Empty when there is neither.
//
// Newest wins, rather than a download always winning. A fresh install
// then is not held back by a download from months ago, and lists
// refreshed by hand during development are picked up without ceremony.
//
// Looks at the disk, so call this somewhere blocking is allowed.
base::FilePath GetListPath(ListKind kind);

// When a file was last written, or a null Time when it is not there.
// How fresh a list is, is the timestamp on the file itself rather
// than anything we write down about it, so the two can never drift
// apart. Looks at the disk.
base::Time GetWrittenAt(const base::FilePath& path);

// Regional lists live in a folder called regional, in both places, as
// <id>.txt. A profile picks them by id (prefs::kBoringRegionalLists).

// True for an id that is safe as a file name and as a pref value: 1 to
// 32 characters of a-z, 0-9 and "-", not starting with "-". Nothing
// else is ever turned into a path.
bool IsValidRegionalListId(std::string_view id);

// The copy of regional list `id` to read: whichever of the shipped and
// the downloaded one was written last, as GetListPath() chooses. Empty
// for an invalid id or when there is neither. Looks at the disk.
base::FilePath GetRegionalListPath(std::string_view id);

// The index of regional lists, boring\regional\index.json:
// [{id, title, locales, licence, source}]. Whichever of the shipped and
// the downloaded one was written last, as GetListPath() chooses, so a
// list update can add a regional list. Empty when there is neither.
// Looks at the disk.
base::FilePath GetRegionalIndexPath();

// Where a file named in a list update manifest goes, relative to
// GetDownloadedListDir(), or nothing when the name is not one this
// browser takes from a download. Manifest names are flat, because a
// release host keeps files in one folder:
//   easylist.txt, ubo.txt, ...  the ListKind files, except
//                               resources.json, which is code and
//                               changes only with the browser
//   regional-<id>.txt           regional\<id>.txt, for a valid id
//   regional-index.json         regional\index.json
std::optional<base::FilePath> GetDownloadTarget(std::string_view name);

// One entry of that index.
struct RegionalListInfo {
  RegionalListInfo();
  RegionalListInfo(const RegionalListInfo&);
  RegionalListInfo& operator=(const RegionalListInfo&);
  ~RegionalListInfo();

  std::string id;
  std::string title;
  std::vector<std::string> locales;
};

// The regional lists this build ships, in the index's order. Entries
// with an invalid id or no title are left out; a missing or unreadable
// index reads as none. Looks at the disk.
std::vector<RegionalListInfo> ReadRegionalIndex();

}  // namespace boring

#endif  // COMPONENTS_BORING_LISTS_LIST_PATHS_H_
