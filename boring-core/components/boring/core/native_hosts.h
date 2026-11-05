// Copyright 2026 boring. BSD style license.

#ifndef COMPONENTS_BORING_CORE_NATIVE_HOSTS_H_
#define COMPONENTS_BORING_CORE_NATIVE_HOSTS_H_

#include <string>
#include <string_view>
#include <vector>

#include "base/files/file_path.h"

namespace boring {

// A native messaging host (a program on this computer an add-on can talk
// to) as registered for this browser.
struct NativeHostRegistration {
  std::string name;
  // The host's JSON manifest, as the registry gives it.
  base::FilePath manifest;
};

// True for a name Chromium accepts for a host: lowercase letters, digits
// and underscores in parts joined by single dots.
bool IsValidNativeHostName(std::string_view name);

// Every host registered where this browser looks, per user then per
// machine, under both the Chromium and the Google\Chrome key (the same
// places as launch_context_win.cc), once per name, sorted by name. Reads
// the registry only. Empty off Windows.
std::vector<NativeHostRegistration> RegisteredNativeHosts();

}  // namespace boring

#endif  // COMPONENTS_BORING_CORE_NATIVE_HOSTS_H_
