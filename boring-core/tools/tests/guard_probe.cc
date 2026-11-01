// Command line front for the two scam guard matchers, so a test can ask
// them questions without a Chromium build. See test_scam_guards.py.
//
// Reads one request per line from stdin: a kind, then hex encoded
// arguments, separated by tabs.
//   tool <file name> <host>   prints the tool name, or nothing
//   cmd  <clipboard text>     prints 1 or 0
// Hex because clipboard text has newlines, tabs and quotes in it.

#include <iostream>
#include <string>
#include <vector>

#include "components/boring/guards/remote_access_tools.h"
#include "components/boring/guards/shell_command.h"

namespace {

std::string Unhex(const std::string& hex) {
  std::string out;
  for (size_t i = 0; i + 1 < hex.size(); i += 2) {
    out.push_back(static_cast<char>(std::stoi(hex.substr(i, 2), nullptr, 16)));
  }
  return out;
}

std::vector<std::string> Split(const std::string& line) {
  std::vector<std::string> parts;
  size_t start = 0;
  for (;;) {
    const size_t tab = line.find('\t', start);
    if (tab == std::string::npos) {
      parts.push_back(line.substr(start));
      return parts;
    }
    parts.push_back(line.substr(start, tab - start));
    start = tab + 1;
  }
}

}  // namespace

int main() {
  std::string line;
  while (std::getline(std::cin, line)) {
    if (!line.empty() && line.back() == '\r') {
      line.pop_back();
    }
    const std::vector<std::string> parts = Split(line);
    if (parts[0] == "tool" && parts.size() == 3) {
      std::cout << boring::guards::MatchRemoteAccessTool(Unhex(parts[1]),
                                                         Unhex(parts[2]))
                << "\n";
    } else if (parts[0] == "cmd" && parts.size() == 2) {
      std::cout << (boring::guards::LooksLikeShellCommand(Unhex(parts[1]))
                        ? "1"
                        : "0")
                << "\n";
    } else {
      std::cout << "bad request\n";
    }
  }
  return 0;
}
