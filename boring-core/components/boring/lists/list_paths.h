// Copyright 2026 boring. BSD style license.

#ifndef COMPONENTS_BORING_LISTS_LIST_PATHS_H_
#define COMPONENTS_BORING_LISTS_LIST_PATHS_H_

#include <optional>
#include <string_view>

#include "base/files/file_path.h"
#include "base/time/time.h"

namespace boring {

// The two lists the browser blocks with.
enum class ListKind {
  kFilters,  // ad and tracker rules
  kScam,     // scam and phishing hosts
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

}  // namespace boring

#endif  // COMPONENTS_BORING_LISTS_LIST_PATHS_H_
