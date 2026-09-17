// Copyright 2026 boring. BSD style license.

#include "components/boring/lists/list_paths.h"

#include "base/base_paths.h"
#include "base/command_line.h"
#include "base/files/file.h"
#include "base/files/file_util.h"
#include "base/path_service.h"
#include "base/time/time.h"
#include "build/build_config.h"

namespace boring {

namespace {

// Lists sit in a folder called boring, both next to the browser and in
// the per machine folder.
constexpr base::FilePath::CharType kListDir[] = FILE_PATH_LITERAL("boring");
constexpr base::FilePath::CharType kDownloadDir[] = FILE_PATH_LITERAL("lists");

// Keep downloaded lists somewhere else. The smoke test points
// this at a temporary folder so a test run never touches the
// lists the person on this machine is actually browsing with.
constexpr char kListDirSwitch[] = "boring-list-dir";

constexpr char kFiltersFile[] = "easylist.txt";
constexpr char kScamFile[] = "scamlist.txt";

}  // namespace

base::Time GetWrittenAt(const base::FilePath& path) {
  base::File::Info info;
  if (path.empty() || !base::GetFileInfo(path, &info)) {
    return base::Time();
  }
  return info.last_modified;
}

const char* ListFileName(ListKind kind) {
  return kind == ListKind::kFilters ? kFiltersFile : kScamFile;
}

std::optional<ListKind> ListKindFromName(std::string_view name) {
  if (name == kFiltersFile) {
    return ListKind::kFilters;
  }
  if (name == kScamFile) {
    return ListKind::kScam;
  }
  return std::nullopt;
}

base::FilePath GetShippedListPath(ListKind kind) {
  base::FilePath dir;
  if (!base::PathService::Get(base::DIR_MODULE, &dir)) {
    return base::FilePath();
  }
  return dir.Append(kListDir).AppendASCII(ListFileName(kind));
}

base::FilePath GetDownloadedListDir() {
  const base::CommandLine* command_line =
      base::CommandLine::ForCurrentProcess();
  if (command_line->HasSwitch(kListDirSwitch)) {
    return command_line->GetSwitchValuePath(kListDirSwitch);
  }
#if BUILDFLAG(IS_WIN)
  base::FilePath dir;
  // Local rather than roaming. These files are large and can always be
  // fetched again, so they have no business being copied around a
  // domain with someone's roaming profile.
  if (!base::PathService::Get(base::DIR_LOCAL_APP_DATA, &dir)) {
    return base::FilePath();
  }
  return dir.Append(kListDir).Append(kDownloadDir);
#else
  // Windows is the only platform we build today. Returning nothing
  // leaves the browser on its shipped lists, which is better than
  // guessing at a folder nobody has tested.
  return base::FilePath();
#endif
}

base::FilePath GetDownloadedListPath(ListKind kind) {
  const base::FilePath dir = GetDownloadedListDir();
  return dir.empty() ? base::FilePath() : dir.AppendASCII(ListFileName(kind));
}

base::FilePath GetListPath(ListKind kind) {
  const base::FilePath shipped = GetShippedListPath(kind);
  const base::FilePath downloaded = GetDownloadedListPath(kind);
  const base::Time shipped_at = GetWrittenAt(shipped);
  const base::Time downloaded_at = GetWrittenAt(downloaded);

  if (downloaded_at.is_null()) {
    return shipped_at.is_null() ? base::FilePath() : shipped;
  }
  if (shipped_at.is_null() || downloaded_at > shipped_at) {
    return downloaded;
  }
  return shipped;
}

}  // namespace boring
