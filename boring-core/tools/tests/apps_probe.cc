// Command line front for the "Apps you added" helpers, so a test can ask
// them questions without a Chromium build. See test_apps_rows.py.
//
// Each stdin line is one question:
//   group <extension id>                   prints its group key
//   ai <provider> [ollama host] [local]     prints on|off, label, host

#include <iostream>
#include <sstream>
#include <string>

#include "components/boring/protection/apps_data.h"

int main() {
  std::string line;
  while (std::getline(std::cin, line)) {
    if (!line.empty() && line.back() == '\r') {
      line.pop_back();
    }
    std::istringstream in(line);
    std::string kind, a, b, local;
    in >> kind >> a >> b >> local;
    if (kind == "group") {
      std::cout << boring::AddonGroupKey(boring::GroupForAddon(a))
                << "\n";
    } else if (kind == "ai") {
      const boring::AiRow row = boring::DescribeAiRow(a, b, local == "local");
      std::cout << (row.on ? "on" : "off") << "|" << row.label << "|"
                << row.host << "\n";
    } else {
      std::cout << "?\n";
    }
  }
  return 0;
}
