// Copyright 2026 boring. BSD style license.

#include "components/boring/importer/chromium_profiles.h"

#include <optional>
#include <string>
#include <string_view>

#include "base/base_paths.h"
#include "base/command_line.h"
#include "base/files/file_path.h"
#include "base/files/file_util.h"
#include "base/json/json_reader.h"
#include "base/path_service.h"
#include "base/strings/utf_string_conversions.h"
#include "base/threading/scoped_blocking_call.h"
#include "base/values.h"
#include "build/build_config.h"
#include "components/user_data_importer/common/importer_type.h"

namespace boring {

namespace {

// Point the importer at another "User Data" folder instead of the real
// one. The smoke tests use these with a made up profile under E:\tmp,
// so a test run never reads the Chrome or Edge data of the person on
// this machine. Like --boring-list-dir, they only change where we look.
constexpr char kChromeDirSwitch[] = "boring-import-chrome-dir";
constexpr char kEdgeDirSwitch[] = "boring-import-edge-dir";

// Local State is a few kilobytes. Anything past this is not one.
constexpr size_t kMaxLocalStateSize = 16 * 1024 * 1024;

struct Source {
  const char* name;
  const char* dir_switch;
  // Under %LOCALAPPDATA%.
  const base::FilePath::CharType* user_data;
};

constexpr Source kSources[] = {
    {"Google Chrome", kChromeDirSwitch,
     FILE_PATH_LITERAL("Google\\Chrome\\User Data")},
    {"Microsoft Edge", kEdgeDirSwitch,
     FILE_PATH_LITERAL("Microsoft\\Edge\\User Data")},
};

base::FilePath UserDataDir(const Source& source) {
  const base::CommandLine* command_line =
      base::CommandLine::ForCurrentProcess();
  if (command_line->HasSwitch(source.dir_switch)) {
    return command_line->GetSwitchValuePath(source.dir_switch);
  }
#if BUILDFLAG(IS_WIN)
  base::FilePath local;
  if (!base::PathService::Get(base::DIR_LOCAL_APP_DATA, &local)) {
    return base::FilePath();
  }
  return local.Append(source.user_data);
#else
  // Windows is the only platform we build.
  return base::FilePath();
#endif
}

// What can be imported from one profile folder, as ImportItem bits.
uint16_t ItemsIn(const base::FilePath& profile_dir) {
  uint16_t items = user_data_importer::NONE;
  if (base::PathExists(profile_dir.Append(kChromiumBookmarksFile)) ||
      base::PathExists(profile_dir.Append(kChromiumAccountBookmarksFile))) {
    items |= user_data_importer::FAVORITES;
  }
  if (base::PathExists(profile_dir.Append(kChromiumHistoryFile))) {
    items |= user_data_importer::HISTORY;
  }
  if (base::PathExists(profile_dir.Append(kChromiumWebDataFile))) {
    items |= user_data_importer::SEARCH_ENGINES;
  }
  return items;
}

// A profile folder name from Local State, only if it is a plain folder
// name. The file is not ours, so it does not get to point elsewhere.
std::optional<base::FilePath> ProfileFolder(const base::FilePath& user_data,
                                            std::string_view key) {
  const base::FilePath name = base::FilePath::FromUTF8Unsafe(key);
  if (name.empty() || name.BaseName() != name ||
      name.value() == FILE_PATH_LITERAL(".") ||
      name.value() == FILE_PATH_LITERAL("..")) {
    return std::nullopt;
  }
  return user_data.Append(name);
}

void AddProfile(const Source& source,
                const base::FilePath& profile_dir,
                const std::string& display_name,
                std::vector<user_data_importer::SourceProfile>* profiles) {
  const uint16_t items = ItemsIn(profile_dir);
  if (!items) {
    return;
  }
  user_data_importer::SourceProfile profile;
  profile.importer_name = base::UTF8ToUTF16(source.name);
#if BUILDFLAG(IS_WIN)
  profile.importer_type = user_data_importer::TYPE_CHROMIUM;
#endif
  profile.source_path = profile_dir;
  profile.services_supported = items;
  profile.profile = base::UTF8ToUTF16(display_name);
  profiles->push_back(profile);
}

void DetectOne(const Source& source,
               std::vector<user_data_importer::SourceProfile>* profiles) {
  const base::FilePath user_data = UserDataDir(source);
  if (user_data.empty() || !base::DirectoryExists(user_data)) {
    return;
  }

  std::string json;
  std::optional<base::DictValue> local_state;
  if (base::ReadFileToStringWithMaxSize(
          user_data.Append(FILE_PATH_LITERAL("Local State")), &json,
          kMaxLocalStateSize)) {
    local_state = base::JSONReader::ReadDict(json, base::JSON_PARSE_RFC);
  }
  const base::DictValue* info_cache =
      local_state ? local_state->FindDictByDottedPath("profile.info_cache")
                  : nullptr;

  if (!info_cache || info_cache->empty()) {
    // No list of profiles: the one every install starts with.
    AddProfile(source, user_data.Append(FILE_PATH_LITERAL("Default")),
               std::string(), profiles);
    return;
  }
  for (const auto [key, value] : *info_cache) {
    const std::optional<base::FilePath> dir = ProfileFolder(user_data, key);
    if (!dir) {
      continue;
    }
    const std::string* name =
        value.is_dict() ? value.GetDict().FindString("name") : nullptr;
    AddProfile(source, *dir, name ? *name : key, profiles);
  }
}

}  // namespace

void DetectChromiumProfiles(
    std::vector<user_data_importer::SourceProfile>* profiles) {
  base::ScopedBlockingCall scoped_blocking_call(FROM_HERE,
                                                base::BlockingType::MAY_BLOCK);
  for (const Source& source : kSources) {
    DetectOne(source, profiles);
  }
}

bool HasChromiumProfiles() {
  std::vector<user_data_importer::SourceProfile> profiles;
  DetectChromiumProfiles(&profiles);
  return !profiles.empty();
}

}  // namespace boring
