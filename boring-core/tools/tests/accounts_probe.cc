// Command line front for the Chromium-free half of Accounts, so a test can
// ask it questions without a Chromium build. See test_accounts_table.py.
//
// Reads lines from stdin:
//   U <address>        prints ok <text to parse>, or the problem's name
//   N <name>           prints the cleaned name between brackets
//   D <base>|<taken>|<taken>...   prints the default name
//   T                  prints the table, one company per line, tab separated
//   M                  prints the most accounts a list may hold

#include <iostream>
#include <sstream>
#include <string>
#include <vector>

#include "components/boring/accounts/accounts_rules.h"

namespace {

const char* ProblemName(boring::accounts::UrlProblem problem) {
  using boring::accounts::UrlProblem;
  switch (problem) {
    case UrlProblem::kNone:
      return "ok";
    case UrlProblem::kEmpty:
      return "empty";
    case UrlProblem::kTooLong:
      return "too_long";
    case UrlProblem::kNotHttps:
      return "not_https";
    case UrlProblem::kCredentials:
      return "credentials";
    case UrlProblem::kNotWebAddress:
      return "not_web_address";
  }
  return "?";
}

std::vector<std::string> Split(const std::string& text, char by) {
  std::vector<std::string> parts;
  std::stringstream in(text);
  std::string part;
  while (std::getline(in, part, by)) {
    parts.push_back(part);
  }
  return parts;
}

}  // namespace

int main() {
  std::string line;
  while (std::getline(std::cin, line)) {
    if (!line.empty() && line.back() == '\r') {
      line.pop_back();
    }
    if (line.empty()) {
      continue;
    }
    const char what = line[0];
    const std::string arg = line.size() > 2 ? line.substr(2) : std::string();
    if (what == 'U') {
      std::string out;
      const auto problem = boring::accounts::PreCheckOtherUrl(arg, &out);
      std::cout << ProblemName(problem);
      if (problem == boring::accounts::UrlProblem::kNone) {
        std::cout << " " << out;
      }
      std::cout << "\n";
    } else if (what == 'N') {
      std::cout << "[" << boring::accounts::CleanName(arg) << "]\n";
    } else if (what == 'D') {
      std::vector<std::string> parts = Split(arg, '|');
      const std::string base = parts.empty() ? std::string() : parts[0];
      if (!parts.empty()) {
        parts.erase(parts.begin());
      }
      std::cout << boring::accounts::DefaultName(base, parts) << "\n";
    } else if (what == 'T') {
      for (const auto& known : boring::accounts::KnownProviders()) {
        std::cout << known.key << "\t" << known.name << "\t" << known.sign_in
                  << "\t" << known.mail << "\t" << known.calendar << "\t"
                  << known.files << "\n";
      }
      std::cout << "end\n";
    } else if (what == 'M') {
      std::cout << boring::accounts::kMaxAccounts << "\n";
    }
  }
  return 0;
}
