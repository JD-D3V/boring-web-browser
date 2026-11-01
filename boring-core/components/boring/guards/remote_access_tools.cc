// Copyright 2026 boring. BSD style license.

#include "components/boring/guards/remote_access_tools.h"

#include <cstddef>
#include <string>
#include <string_view>

namespace boring {
namespace guards {

namespace {

struct Tool {
  const char* name;
  const char* token;  // Looked for in the file name, see the list.
  const char* host;   // The vendor's download server, see the list.
};

constexpr Tool kTools[] = {
#define TOOL(name, token, host) {name, token, host},
#include "components/boring/guards/remote_access_tools.inc"
#undef TOOL
};

// Things a person runs or installs. Judged by the end of the name.
constexpr const char* kProgramTypes[] = {
    "exe",  "msi", "msix", "msixbundle", "appx", "appxbundle",
    "dmg",  "pkg", "deb",  "rpm",        "apk",  "appimage",
};

// Could hold one of them. Counts for a name match, but not for a host
// match: a zip from the vendor's server is as likely to be a manual.
constexpr const char* kArchiveTypes[] = {"zip", "7z", "rar"};

char Lower(char c) {
  return (c >= 'A' && c <= 'Z') ? static_cast<char>(c - 'A' + 'a') : c;
}

bool IsAlnum(char c) {
  return (c >= 'a' && c <= 'z') || (c >= '0' && c <= '9');
}

template <size_t N>
bool OneOf(const std::string& value, const char* const (&list)[N]) {
  for (const char* item : list) {
    if (value == item) {
      return true;
    }
  }
  return false;
}

bool HostIsOrEndsWith(const std::string& host, const std::string& domain) {
  if (host == domain) {
    return true;
  }
  return host.size() > domain.size() &&
         host.compare(host.size() - domain.size(), domain.size(), domain) ==
             0 &&
         host[host.size() - domain.size() - 1] == '.';
}

}  // namespace

std::string MatchRemoteAccessTool(std::string_view file_name,
                                  std::string_view host) {
  // Only the last part of a path is the name.
  const size_t slash = file_name.find_last_of("/\\");
  if (slash != std::string_view::npos) {
    file_name.remove_prefix(slash + 1);
  }
  const size_t dot = file_name.find_last_of('.');
  if (dot == std::string_view::npos) {
    return std::string();
  }

  std::string extension;
  for (char c : file_name.substr(dot + 1)) {
    extension.push_back(Lower(c));
  }
  const bool program = OneOf(extension, kProgramTypes);
  if (!program && !OneOf(extension, kArchiveTypes)) {
    return std::string();
  }

  std::string squashed;
  for (char c : file_name.substr(0, dot)) {
    c = Lower(c);
    if (IsAlnum(c)) {
      squashed.push_back(c);
    }
  }
  for (const Tool& tool : kTools) {
    if (tool.token[0] != '\0' &&
        squashed.find(tool.token) != std::string::npos) {
      return tool.name;
    }
  }

  if (!program) {
    return std::string();
  }
  std::string lowered_host;
  for (char c : host) {
    lowered_host.push_back(Lower(c));
  }
  while (!lowered_host.empty() && lowered_host.back() == '.') {
    lowered_host.pop_back();
  }
  for (const Tool& tool : kTools) {
    if (tool.host[0] != '\0' && HostIsOrEndsWith(lowered_host, tool.host)) {
      return tool.name;
    }
  }
  return std::string();
}

}  // namespace guards
}  // namespace boring
