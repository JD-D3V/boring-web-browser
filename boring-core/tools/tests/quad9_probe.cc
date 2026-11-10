// Command line front for the Quad9 answer parser, so a test can feed it
// captured answers without a Chromium build. See test_quad9_answer.py.
//
// Reads lines from stdin:
//   A <host> <hex of the answer>   prints blocked, not_blocked or invalid
//   Q <host>                       prints the hex of the query, or "none"

#include <cstdio>
#include <iostream>
#include <sstream>
#include <string>

#include "components/boring/scam/quad9_answer.h"

namespace {

int HexValue(char c) {
  if (c >= '0' && c <= '9') return c - '0';
  if (c >= 'a' && c <= 'f') return c - 'a' + 10;
  if (c >= 'A' && c <= 'F') return c - 'A' + 10;
  return -1;
}

std::string FromHex(const std::string& hex) {
  std::string out;
  for (size_t i = 0; i + 1 < hex.size(); i += 2) {
    out.push_back(
        static_cast<char>(HexValue(hex[i]) * 16 + HexValue(hex[i + 1])));
  }
  return out;
}

std::string ToHex(const std::string& bytes) {
  std::string out;
  char buffer[3];
  for (unsigned char c : bytes) {
    std::snprintf(buffer, sizeof(buffer), "%02x", c);
    out += buffer;
  }
  return out;
}

}  // namespace

int main() {
  std::string line;
  while (std::getline(std::cin, line)) {
    if (!line.empty() && line.back() == '\r') {
      line.pop_back();
    }
    std::istringstream in(line);
    std::string command, host, hex;
    in >> command >> host >> hex;
    if (command == "Q") {
      std::string query = boring::BuildDnsQuery(host);
      std::cout << (query.empty() ? "none" : ToHex(query)) << "\n";
      continue;
    }
    switch (boring::ParseQuad9Answer(FromHex(hex), host)) {
      case boring::Quad9Verdict::kBlocked:
        std::cout << "blocked\n";
        break;
      case boring::Quad9Verdict::kNotBlocked:
        std::cout << "not_blocked\n";
        break;
      case boring::Quad9Verdict::kInvalid:
        std::cout << "invalid\n";
        break;
    }
  }
  return 0;
}
