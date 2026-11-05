// Copyright 2026 boring. BSD style license.

#include "components/boring/protection/native_hosts.h"

#include <optional>
#include <string>
#include <string_view>
#include <utility>
#include <vector>

#include "base/files/file_path.h"
#include "base/files/file_util.h"
#include "base/json/json_reader.h"
#include "base/values.h"
#include "components/boring/core/native_hosts.h"

namespace boring {

namespace {

// A manifest is a few lines; anything bigger is not one.
constexpr size_t kMaxManifestBytes = 1024 * 1024;

// "chrome-extension://<32 letters a to p>/" gives the add-on id, anything
// else gives nothing.
std::optional<std::string> AddOnIdFromOrigin(std::string_view origin) {
  constexpr std::string_view kPrefix = "chrome-extension://";
  if (origin.substr(0, kPrefix.size()) != kPrefix) {
    return std::nullopt;
  }
  origin.remove_prefix(kPrefix.size());
  const size_t slash = origin.find('/');
  const std::string_view id = origin.substr(0, slash);
  if (id.size() != 32) {
    return std::nullopt;
  }
  for (char c : id) {
    if (c < 'a' || c > 'p') {
      return std::nullopt;
    }
  }
  return std::string(id);
}

std::optional<NativeHost> ReadHost(const NativeHostRegistration& registered) {
  std::string contents;
  if (!base::ReadFileToStringWithMaxSize(registered.manifest, &contents,
                                         kMaxManifestBytes)) {
    return std::nullopt;
  }
  std::optional<base::DictValue> manifest =
      base::JSONReader::ReadDict(contents, base::JSON_PARSE_RFC);
  if (!manifest) {
    return std::nullopt;
  }
  // Chromium refuses a manifest that does not name the host it was found
  // for, or has no description, stdio type, path or origins, so such a
  // host cannot run and is not listed.
  const std::string* name = manifest->FindString("name");
  const std::string* description = manifest->FindString("description");
  const std::string* type = manifest->FindString("type");
  const std::string* path = manifest->FindString("path");
  const base::ListValue* origins = manifest->FindList("allowed_origins");
  if (!name || *name != registered.name || !description ||
      description->empty() || !type || *type != "stdio" || !path ||
      path->empty() || !origins) {
    return std::nullopt;
  }
  NativeHost host;
  host.name = registered.name;
  host.description = *description;
  host.app = base::FilePath::FromUTF8Unsafe(*path);
  if (!host.app.IsAbsolute()) {
    host.app = registered.manifest.DirName().Append(host.app);
  }
  for (const base::Value& origin : *origins) {
    if (!origin.is_string()) {
      continue;
    }
    if (std::optional<std::string> id = AddOnIdFromOrigin(origin.GetString())) {
      host.add_on_ids.push_back(std::move(*id));
    }
  }
  return host;
}

}  // namespace

std::vector<NativeHost> ScanNativeHosts() {
  std::vector<NativeHost> hosts;
  for (const NativeHostRegistration& registered : RegisteredNativeHosts()) {
    if (std::optional<NativeHost> host = ReadHost(registered)) {
      hosts.push_back(std::move(*host));
    }
  }
  return hosts;
}

}  // namespace boring
