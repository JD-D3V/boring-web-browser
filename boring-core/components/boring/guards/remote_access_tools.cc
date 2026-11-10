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
    // Programs under another name, or a disk image that opens as a drive.
    "scr",  "com", "pif",  "bat",        "cmd",  "ps1",
    "vbs",  "hta", "lnk",  "msp",        "iso",
};

// Could hold one of them. Counts for a name match, but not for a host
// match: a zip from the vendor's server is as likely to be a manual.
constexpr const char* kArchiveTypes[] = {"zip", "7z", "rar",
                                         "img", "vhd", "vhdx", "cab"};

char Lower(char c) {
  return (c >= 'A' && c <= 'Z') ? static_cast<char>(c - 'A' + 'a') : c;
}

bool IsAlnum(char c) {
  return (c >= 'a' && c <= 'z') || (c >= '0' && c <= '9');
}

// Letters of other alphabets that read as a Latin letter, as lower case
// ASCII, or 0 for any other code point. Enough for a Cyrillic A in AnyDesk to
// be seen as "anydesk": Cyrillic and Greek capitals and small letters, and
// full width Latin.
char Confusable(uint32_t cp) {
  static constexpr struct {
    uint32_t cp;
    char to;
  } kTable[] = {
      {0x0410, 'a'}, {0x0412, 'b'}, {0x0415, 'e'}, {0x041A, 'k'},
      {0x041C, 'm'}, {0x041D, 'h'}, {0x041E, 'o'}, {0x0420, 'p'},
      {0x0421, 'c'}, {0x0422, 't'}, {0x0423, 'y'}, {0x0425, 'x'},
      {0x0430, 'a'}, {0x0435, 'e'}, {0x043E, 'o'}, {0x0440, 'p'},
      {0x0441, 'c'}, {0x0443, 'y'}, {0x0445, 'x'}, {0x0455, 's'},
      {0x0456, 'i'}, {0x0458, 'j'}, {0x0391, 'a'}, {0x0392, 'b'},
      {0x0395, 'e'}, {0x0396, 'z'}, {0x0397, 'h'}, {0x0399, 'i'},
      {0x039A, 'k'}, {0x039C, 'm'}, {0x039D, 'n'}, {0x039F, 'o'},
      {0x03A1, 'p'}, {0x03A4, 't'}, {0x03A5, 'y'}, {0x03A7, 'x'},
      {0x03B1, 'a'}, {0x03B9, 'i'}, {0x03BD, 'v'}, {0x03BF, 'o'},
      {0x03C1, 'p'},
  };
  for (const auto& entry : kTable) {
    if (entry.cp == cp) {
      return entry.to;
    }
  }
  if (cp >= 0xFF21 && cp <= 0xFF3A) {
    return static_cast<char>('a' + (cp - 0xFF21));
  }
  if (cp >= 0xFF41 && cp <= 0xFF5A) {
    return static_cast<char>('a' + (cp - 0xFF41));
  }
  return 0;
}

// The letters and digits of a UTF-8 name as lower case ASCII, with look-alike
// letters folded and everything else (spaces, marks, other scripts) dropped.
std::string Squash(std::string_view name) {
  std::string out;
  for (size_t i = 0; i < name.size();) {
    const unsigned char lead = static_cast<unsigned char>(name[i]);
    uint32_t cp = lead;
    size_t length = 1;
    if (lead >= 0xF0) {
      length = 4;
      cp = lead & 0x07;
    } else if (lead >= 0xE0) {
      length = 3;
      cp = lead & 0x0F;
    } else if (lead >= 0xC0) {
      length = 2;
      cp = lead & 0x1F;
    }
    if (length > 1) {
      if (i + length > name.size()) {
        break;
      }
      for (size_t k = 1; k < length; ++k) {
        cp = (cp << 6) | (static_cast<unsigned char>(name[i + k]) & 0x3F);
      }
    }
    i += length;
    const char c = length == 1 ? Lower(static_cast<char>(cp)) : Confusable(cp);
    if (IsAlnum(c)) {
      out.push_back(c);
    }
  }
  return out;
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
  // A name with no ending may be saved as a program once the type is known
  // (served as application/x-msdownload), so it counts as one.
  const size_t dot = file_name.find_last_of('.');
  const bool no_extension = dot == std::string_view::npos;

  std::string extension;
  if (!no_extension) {
    for (char c : file_name.substr(dot + 1)) {
      extension.push_back(Lower(c));
    }
  }
  const bool program = no_extension || OneOf(extension, kProgramTypes);
  if (!program && !OneOf(extension, kArchiveTypes)) {
    return std::string();
  }

  const std::string squashed = Squash(
      no_extension ? file_name : file_name.substr(0, dot));
  for (const Tool& tool : kTools) {
    if (tool.token[0] != '\0' &&
        squashed.find(tool.token) != std::string::npos) {
      return tool.name;
    }
  }

  // A host match needs a real program ending: an unnamed file from the
  // vendor's server may be anything.
  if (no_extension || !program) {
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
