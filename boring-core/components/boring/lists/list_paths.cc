// Copyright 2026 boring. BSD style license.

#include "components/boring/lists/list_paths.h"

#include <utility>

#include "base/base_paths.h"
#include "base/command_line.h"
#include "base/files/file.h"
#include "base/files/file_util.h"
#include "base/json/json_reader.h"
#include "base/notreached.h"
#include "base/path_service.h"
#include "base/strings/strcat.h"
#include "base/strings/string_util.h"
#include "base/time/time.h"
#include "base/values.h"
#include "build/build_config.h"

namespace boring {

namespace {

// Lists sit in a folder called boring, both next to the browser and in
// the per machine folder.
constexpr base::FilePath::CharType kListDir[] = FILE_PATH_LITERAL("boring");
constexpr base::FilePath::CharType kDownloadDir[] = FILE_PATH_LITERAL("lists");
constexpr base::FilePath::CharType kRegionalDir[] =
    FILE_PATH_LITERAL("regional");

// Keep downloaded lists somewhere else. The smoke test points
// this at a temporary folder so a test run never touches the
// lists the person on this machine is actually browsing with.
constexpr char kListDirSwitch[] = "boring-list-dir";

constexpr char kFiltersFile[] = "easylist.txt";
constexpr char kScamFile[] = "scamlist.txt";
constexpr char kUboFile[] = "ubo.txt";
constexpr char kCookiesFile[] = "cookies.txt";
constexpr char kResourcesFile[] = "resources.json";
constexpr char kAggressiveUboFile[] = "aggressive-ubo.txt";
constexpr char kAggressiveFanboyFile[] = "aggressive-fanboy.txt";
constexpr char kRegionalIndexFile[] = "index.json";

// How regional files are named in a list update manifest.
constexpr std::string_view kRegionalBundlePrefix = "regional-";
constexpr std::string_view kRegionalBundleSuffix = ".txt";
constexpr char kRegionalIndexBundleName[] = "regional-index.json";

// The index is about a kilobyte. This is what we refuse to read, not
// what we expect.
constexpr size_t kMaxRegionalIndexBytes = 64 * 1024;
constexpr size_t kMaxRegionalIdLength = 32;

// The folder the shipped lists are in, beside the browser.
base::FilePath ShippedDir() {
  base::FilePath dir;
  if (!base::PathService::Get(base::DIR_MODULE, &dir)) {
    return base::FilePath();
  }
  return dir.Append(kListDir);
}

// Whichever of the two was written last, see GetListPath().
base::FilePath NewestOf(const base::FilePath& shipped,
                        const base::FilePath& downloaded) {
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

}  // namespace

base::Time GetWrittenAt(const base::FilePath& path) {
  base::File::Info info;
  if (path.empty() || !base::GetFileInfo(path, &info)) {
    return base::Time();
  }
  return info.last_modified;
}

const char* ListFileName(ListKind kind) {
  switch (kind) {
    case ListKind::kFilters:
      return kFiltersFile;
    case ListKind::kScam:
      return kScamFile;
    case ListKind::kUbo:
      return kUboFile;
    case ListKind::kCookies:
      return kCookiesFile;
    case ListKind::kResources:
      return kResourcesFile;
    case ListKind::kAggressiveUbo:
      return kAggressiveUboFile;
    case ListKind::kAggressiveFanboy:
      return kAggressiveFanboyFile;
  }
  NOTREACHED();
}

std::optional<ListKind> ListKindFromName(std::string_view name) {
  for (ListKind kind : kAllListKinds) {
    if (name == ListFileName(kind)) {
      return kind;
    }
  }
  return std::nullopt;
}

base::FilePath GetShippedListPath(ListKind kind) {
  const base::FilePath dir = ShippedDir();
  return dir.empty() ? base::FilePath() : dir.AppendASCII(ListFileName(kind));
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
  return NewestOf(GetShippedListPath(kind), GetDownloadedListPath(kind));
}

bool IsValidRegionalListId(std::string_view id) {
  if (id.empty() || id.size() > kMaxRegionalIdLength || id.front() == '-') {
    return false;
  }
  for (char c : id) {
    if (!base::IsAsciiLower(c) && !base::IsAsciiDigit(c) && c != '-') {
      return false;
    }
  }
  return true;
}

base::FilePath GetRegionalListPath(std::string_view id) {
  if (!IsValidRegionalListId(id)) {
    return base::FilePath();
  }
  const std::string file = base::StrCat({id, ".txt"});
  const base::FilePath shipped = ShippedDir();
  const base::FilePath downloaded = GetDownloadedListDir();
  return NewestOf(
      shipped.empty() ? base::FilePath()
                      : shipped.Append(kRegionalDir).AppendASCII(file),
      downloaded.empty() ? base::FilePath()
                         : downloaded.Append(kRegionalDir).AppendASCII(file));
}

base::FilePath GetRegionalIndexPath() {
  const base::FilePath shipped = ShippedDir();
  const base::FilePath downloaded = GetDownloadedListDir();
  return NewestOf(
      shipped.empty()
          ? base::FilePath()
          : shipped.Append(kRegionalDir).AppendASCII(kRegionalIndexFile),
      downloaded.empty()
          ? base::FilePath()
          : downloaded.Append(kRegionalDir).AppendASCII(kRegionalIndexFile));
}

std::optional<base::FilePath> GetDownloadTarget(std::string_view name) {
  if (const std::optional<ListKind> kind = ListKindFromName(name)) {
    if (*kind == ListKind::kResources) {
      return std::nullopt;
    }
    return base::FilePath().AppendASCII(name);
  }
  if (name == kRegionalIndexBundleName) {
    return base::FilePath(kRegionalDir).AppendASCII(kRegionalIndexFile);
  }
  if (name.starts_with(kRegionalBundlePrefix) &&
      name.ends_with(kRegionalBundleSuffix)) {
    const std::string_view id =
        name.substr(kRegionalBundlePrefix.size(),
                    name.size() - kRegionalBundlePrefix.size() -
                        kRegionalBundleSuffix.size());
    if (IsValidRegionalListId(id)) {
      return base::FilePath(kRegionalDir)
          .AppendASCII(base::StrCat({id, kRegionalBundleSuffix}));
    }
  }
  return std::nullopt;
}

RegionalListInfo::RegionalListInfo() = default;
RegionalListInfo::RegionalListInfo(const RegionalListInfo&) = default;
RegionalListInfo& RegionalListInfo::operator=(const RegionalListInfo&) =
    default;
RegionalListInfo::~RegionalListInfo() = default;

std::vector<RegionalListInfo> ReadRegionalIndex() {
  std::vector<RegionalListInfo> lists;
  const base::FilePath path = GetRegionalIndexPath();
  std::string text;
  if (path.empty() ||
      !base::ReadFileToStringWithMaxSize(path, &text, kMaxRegionalIndexBytes)) {
    return lists;
  }
  // Strict JSON: tools/get_filterlists.py writes this file.
  const std::optional<base::ListValue> parsed =
      base::JSONReader::ReadList(text, base::JSON_PARSE_RFC);
  if (!parsed) {
    return lists;
  }
  for (const base::Value& item : *parsed) {
    const base::DictValue* entry = item.GetIfDict();
    if (!entry) {
      continue;
    }
    const std::string* id = entry->FindString("id");
    const std::string* title = entry->FindString("title");
    if (!id || !title || title->empty() || !IsValidRegionalListId(*id)) {
      continue;
    }
    RegionalListInfo info;
    info.id = *id;
    info.title = *title;
    if (const base::ListValue* locales = entry->FindList("locales")) {
      for (const base::Value& locale : *locales) {
        if (locale.is_string()) {
          info.locales.push_back(locale.GetString());
        }
      }
    }
    lists.push_back(std::move(info));
  }
  return lists;
}

}  // namespace boring
