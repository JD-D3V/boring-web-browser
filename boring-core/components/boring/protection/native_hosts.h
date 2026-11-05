// Copyright 2026 boring. BSD style license.

// The "Apps on this computer" rows on the Protection page: which native
// messaging hosts are registered for this browser and which add-ons their
// manifests name. Reads the registry and files, so call it where blocking
// is allowed.

#ifndef COMPONENTS_BORING_PROTECTION_NATIVE_HOSTS_H_
#define COMPONENTS_BORING_PROTECTION_NATIVE_HOSTS_H_

#include <string>
#include <vector>

#include "base/files/file_path.h"

namespace boring {

struct NativeHost {
  std::string name;
  // The manifest's own words about the program. Untrusted text, only
  // ever shown as text.
  std::string description;
  // The program the host starts.
  base::FilePath app;
  // Ids of the add-ons the manifest lets use it.
  std::vector<std::string> add_on_ids;
};

// Every registered host whose manifest Chromium would accept, in name
// order.
std::vector<NativeHost> ScanNativeHosts();

}  // namespace boring

#endif  // COMPONENTS_BORING_PROTECTION_NATIVE_HOSTS_H_
