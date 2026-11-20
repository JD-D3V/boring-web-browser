// Small program for test_passport_words.py: reads one question per line on
// stdin and prints one answer per line. Every string in the tests is plain
// ASCII, so the answers are narrowed character by character.

#include <iostream>
#include <sstream>
#include <string>

#include "components/boring/passport/passport_words.h"

using namespace boring::passport;

namespace {

std::string Narrow(const std::u16string& s) {
  return std::string(s.begin(), s.end());
}

std::u16string Widen(const std::string& s) {
  return std::u16string(s.begin(), s.end());
}

const char* FactName(Fact f) {
  switch (f) {
    case Fact::kScamList:
      return "scam";
    case Fact::kVisits:
      return "visits";
    case Fact::kTwin:
      return "twin";
    case Fact::kCard:
      return "card";
    case Fact::kConnection:
      return "connection";
    case Fact::kPassword:
      return "password";
  }
  return "?";
}

}  // namespace

int main() {
  std::string line;
  while (std::getline(std::cin, line)) {
    std::istringstream in(line);
    std::string op;
    in >> op;
    if (op == "chip" || op == "layout") {
      ChipInputs c;
      in >> c.eligible >> c.blocked_page >> c.scam_listed >> c.chromium_text >>
          c.marked_known >> c.visited_before_today >> c.lookalike >> c.pending;
      const Chip chip = op == "chip" ? DecideChip(c) : DecideLayout(c);
      std::cout << static_cast<int>(chip) << "|" << Narrow(ChipText(chip))
                << "|" << Narrow(Verdict(chip)) << "|";
      for (const auto& b : ButtonsFor(chip)) {
        std::cout << Narrow(b) << ";";
      }
      std::cout << "\n";
    } else if (op == "visits") {
      int before, total, fy, today, ty;
      std::string month;
      in >> before >> total >> fy >> today >> ty >> month;
      std::cout << Narrow(VisitsFact(before, total, fy, today != 0, ty,
                                     Widen(month)))
                << "\n";
    } else if (op == "twin") {
      std::string domain;
      int used;
      in >> domain >> used;
      std::cout << Narrow(TwinFact(Widen(domain), used != 0)) << "\n";
    } else if (op == "footer") {
      uint32_t a, t, c, s, p;
      in >> a >> t >> c >> s >> p;
      std::cout << Narrow(FooterText(a, t, c, s, p)) << "\n";
    } else if (op == "facts") {
      int layout;
      FactInputs f;
      in >> layout >> f.lookalike >> f.asks_card >> f.connection_private >>
          f.saved_password;
      for (Fact fact : FactsFor(static_cast<Chip>(layout), f)) {
        std::cout << FactName(fact) << ";";
      }
      std::cout << "\n";
    } else if (op == "connection") {
      int priv;
      in >> priv;
      std::cout << Narrow(ConnectionFact(priv != 0)) << "\n";
    } else {
      std::cout << "?\n";
    }
  }
  return 0;
}
