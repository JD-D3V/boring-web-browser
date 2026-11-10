// Copyright 2026 boring. BSD style license.

#ifndef COMPONENTS_BORING_FOLDER_COPY_FOLDER_COPY_SETTINGS_H_
#define COMPONENTS_BORING_FOLDER_COPY_FOLDER_COPY_SETTINGS_H_

#include <cstddef>
#include <optional>
#include <string>
#include <string_view>
#include <vector>

#include "base/values.h"

class PrefService;

namespace boring::folder_copy {

// The settings file is read from a folder somebody else may share, so it
// is capped and read by a strict schema.
inline constexpr size_t kMaxSettingsFileBytes = 64 * 1024;

// One setting the file would change, as the person is shown it before
// agreeing.
struct SettingChange {
  std::string pref;
  std::string label;
  std::string from;
  std::string to;
  // Turns a protection off or lowers it. Listed first.
  bool weakens = false;
};

// The names of the settings that can be in the file, to watch for changes.
// Passwords, cookies, history, keys and tokens are not among them, nor
// are the sites the person trusted or the filter lists added by address.
std::vector<std::string> SettingNames();

// The text of boring-settings.json: the settings on the list that the
// person changed from their defaults.
std::string BuildSettingsFile(const PrefService* prefs);

// Reads the text of a settings file. Unknown names and values of the wrong
// kind are dropped; nullopt when it is not a settings file at all.
std::optional<base::DictValue> ParseSettingsFile(std::string_view text);

// What applying `values` would change, protections turned off first.
std::vector<SettingChange> DiffSettings(const PrefService* prefs,
                                        const base::DictValue& values);

// Sets what differs. Returns how many settings changed.
int ApplySettings(PrefService* prefs, const base::DictValue& values);

}  // namespace boring::folder_copy

#endif  // COMPONENTS_BORING_FOLDER_COPY_FOLDER_COPY_SETTINGS_H_
