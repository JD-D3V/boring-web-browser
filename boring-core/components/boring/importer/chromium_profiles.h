// Copyright 2026 boring. BSD style license.

#ifndef COMPONENTS_BORING_IMPORTER_CHROMIUM_PROFILES_H_
#define COMPONENTS_BORING_IMPORTER_CHROMIUM_PROFILES_H_

#include <vector>

#include "base/files/file_path.h"
#include "components/user_data_importer/common/importer_data_types.h"

namespace boring {

// Google Chrome and today's Microsoft Edge keep their data the same way:
// a "User Data" folder with a Local State file that names each profile,
// and one folder per profile holding Bookmarks (JSON), History (SQLite)
// and Web Data (SQLite, where the search engines live). Chromium's own
// import dialog knows neither, so this finds them for it.
//
// Passwords and cookies are never offered. Chrome encrypts them with a
// key only Chrome itself can unlock, so another browser cannot read them.

// The files read from each profile folder.
inline constexpr base::FilePath::CharType kChromiumBookmarksFile[] =
    FILE_PATH_LITERAL("Bookmarks");
// Bookmarks saved to a signed in Google account, kept apart from the
// ones on this computer by newer versions of Chrome.
inline constexpr base::FilePath::CharType kChromiumAccountBookmarksFile[] =
    FILE_PATH_LITERAL("AccountBookmarks");
inline constexpr base::FilePath::CharType kChromiumHistoryFile[] =
    FILE_PATH_LITERAL("History");
inline constexpr base::FilePath::CharType kChromiumWebDataFile[] =
    FILE_PATH_LITERAL("Web Data");

// Adds one entry per Chrome or Edge profile found on this computer, for
// the import dialog. Blocks on the disk: call it where blocking is
// allowed.
void DetectChromiumProfiles(
    std::vector<user_data_importer::SourceProfile>* profiles);

// True when DetectChromiumProfiles would add anything. Blocks too.
bool HasChromiumProfiles();

}  // namespace boring

#endif  // COMPONENTS_BORING_IMPORTER_CHROMIUM_PROFILES_H_
