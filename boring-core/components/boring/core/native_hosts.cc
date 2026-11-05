// Copyright 2026 boring. BSD style license.

#include "components/boring/core/native_hosts.h"

#include <algorithm>
#include <set>
#include <string>
#include <string_view>
#include <utility>
#include <vector>

#include "base/files/file_path.h"
#include "base/strings/utf_string_conversions.h"
#include "build/build_config.h"

#if BUILDFLAG(IS_WIN)
#include <windows.h>

#include "base/win/registry.h"
#endif

namespace boring {

bool IsValidNativeHostName(std::string_view name) {
  if (name.empty() || name.front() == '.' || name.back() == '.') {
    return false;
  }
  char previous = 0;
  for (char c : name) {
    const bool word = (c >= 'a' && c <= 'z') || (c >= '0' && c <= '9') ||
                      c == '_';
    if (!word && !(c == '.' && previous != '.')) {
      return false;
    }
    previous = c;
  }
  return true;
}

std::vector<NativeHostRegistration> RegisteredNativeHosts() {
  std::vector<NativeHostRegistration> found;
#if BUILDFLAG(IS_WIN)
  static constexpr const wchar_t* kFamilies[] = {
      L"SOFTWARE\\Chromium\\NativeMessagingHosts",
      L"SOFTWARE\\Google\\Chrome\\NativeMessagingHosts"};
  std::set<std::string> seen;
  for (HKEY root : {HKEY_CURRENT_USER, HKEY_LOCAL_MACHINE}) {
    for (REGSAM view : {KEY_WOW64_32KEY, KEY_WOW64_64KEY}) {
      for (const wchar_t* family : kFamilies) {
        for (base::win::RegistryKeyIterator it(root, family, view); it.Valid();
             ++it) {
          const std::string name = base::WideToUTF8(it.Name());
          if (!IsValidNativeHostName(name) || seen.count(name)) {
            continue;
          }
          base::win::RegKey key(
              root, (std::wstring(family) + L"\\" + it.Name()).c_str(),
              KEY_QUERY_VALUE | view);
          std::wstring manifest;
          if (key.ReadValue(nullptr, &manifest) != ERROR_SUCCESS ||
              manifest.empty()) {
            continue;
          }
          seen.insert(name);
          found.push_back({name, base::FilePath(manifest)});
        }
      }
    }
  }
  std::sort(found.begin(), found.end(),
            [](const auto& a, const auto& b) { return a.name < b.name; });
#endif
  return found;
}

}  // namespace boring
