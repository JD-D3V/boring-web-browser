// Command line front for the look-alike matcher, so a test can ask it
// questions without a Chromium build. See test_lookalike.py.
//
// Reads one registrable domain per line from stdin and prints the real
// domain it is dressed up as, or an empty line.

#include <iostream>
#include <string>

#include "components/boring/scam/lookalike_brands.h"

int main() {
  std::string line;
  while (std::getline(std::cin, line)) {
    if (!line.empty() && line.back() == '\r') {
      line.pop_back();
    }
    std::cout << boring::FindLookalikeBrand(line) << "\n";
  }
  return 0;
}
