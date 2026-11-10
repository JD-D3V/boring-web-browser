// Copyright 2026 boring. BSD style license.

#include "components/boring/guards/shell_command.h"

#include <cstddef>
#include <initializer_list>
#include <string>
#include <string_view>
#include <vector>

namespace boring {
namespace guards {

namespace {

using View = std::string_view;

// Nothing shorter is a command worth warning about.
constexpr size_t kMinLength = 6;
constexpr size_t kMaxLength = 64 * 1024;
// Longer text is padding around something. A terminal runs what it is
// pasted, so the start and the end are looked at (see LooksLikeShellCommand).
constexpr size_t kEdge = 4 * 1024;
// How far past a command word its arguments are looked for.
constexpr size_t kReach = 4000;
// Up to this much long text is scanned whole, in overlapping windows, so a
// command padded on both sides is still found. Above it only the ends are.
constexpr size_t kScanCap = 1024 * 1024;

char Lower(char c) {
  return (c >= 'A' && c <= 'Z') ? static_cast<char>(c - 'A' + 'a') : c;
}

bool IsAlnum(char c) {
  return (c >= 'a' && c <= 'z') || (c >= '0' && c <= '9');
}

bool IsWordChar(char c) {
  return IsAlnum(c) || c == '_';
}

bool IsBlank(char c) {
  return c == ' ' || c == '\t';
}

// The next whole word `word` at or after `from`, or npos. Whole means
// not part of a longer name: "powershell" is found in "x | powershell"
// and "C:\...\powershell.exe" but not in "windowspowershell" or
// "powershell_ise".
size_t FindWord(View text, View word, size_t from = 0) {
  while ((from = text.find(word, from)) != View::npos) {
    const bool before_ok =
        from == 0 || !(IsWordChar(text[from - 1]) || text[from - 1] == '-');
    const size_t end = from + word.size();
    const bool after_ok = end >= text.size() || !IsWordChar(text[end]);
    if (before_ok && after_ok) {
      return from;
    }
    ++from;
  }
  return View::npos;
}

bool HasWordAny(View text, std::initializer_list<View> words) {
  for (View word : words) {
    if (FindWord(text, word) != View::npos) {
      return true;
    }
  }
  return false;
}

bool Contains(View text, View part) {
  return text.find(part) != View::npos;
}

// What follows a command word that ends at `end`, past a ".exe", to the
// end of its line: a one-liner keeps its options on one line, and prose
// that happens to mention a command does not.
View After(View text, size_t end) {
  if (text.substr(end, 4) == ".exe") {
    end += 4;
  }
  View rest = text.substr(end, kReach);
  const size_t newline = rest.find('\n');
  return newline == View::npos ? rest : rest.substr(0, newline);
}

View SkipBlanks(View text) {
  size_t i = 0;
  while (i < text.size() && IsBlank(text[i])) {
    ++i;
  }
  return text.substr(i);
}

// The line `pos` is on.
View LineAt(View text, size_t pos) {
  const size_t start = text.rfind('\n', pos);
  const size_t from = start == View::npos ? 0 : start + 1;
  const size_t stop = text.find('\n', pos);
  return text.substr(from, stop == View::npos ? View::npos : stop - from);
}

// "-w", "-enc", "/c": a dash or slash and a letter, after a blank.
bool StartsWithFlag(View rest) {
  if (rest.empty() || !IsBlank(rest[0])) {
    return false;
  }
  rest = SkipBlanks(rest);
  return rest.size() >= 2 && (rest[0] == '-' || rest[0] == '/') &&
         rest[1] >= 'a' && rest[1] <= 'z';
}

// powershell and pwsh: with any option, or anything in the arguments
// that downloads, decodes or runs. A bare mention is only a word.
bool PowerShellCommand(View t) {
  for (View name : {View("powershell"), View("pwsh")}) {
    for (size_t at = FindWord(t, name); at != View::npos;
         at = FindWord(t, name, at + 1)) {
      const View rest = After(t, at + name.size());
      if (StartsWithFlag(rest) ||
          HasWordAny(rest, {"iex", "iwr", "irm", "invoke-expression",
                            "invoke-webrequest", "invoke-restmethod",
                            "downloadstring", "downloadfile",
                            "frombase64string", "start-process",
                            "new-object"})) {
        return true;
      }
    }
  }
  return false;
}

// cmd /c, cmd /k, cmd /r, cmd /v:on: a command prompt told to run
// something and exit or stay.
bool CmdCommand(View t) {
  for (size_t at = FindWord(t, "cmd"); at != View::npos;
       at = FindWord(t, "cmd", at + 1)) {
    View rest = SkipBlanks(After(t, at + 3));
    if (rest.size() >= 2 && rest[0] == '/' &&
        (rest[1] == 'c' || rest[1] == 'k' || rest[1] == 'r' ||
         rest[1] == 'v') &&
        (rest.size() == 2 || !IsAlnum(rest[2]))) {
      return true;
    }
  }
  return false;
}

// mshta runs a remote or inline script, which is all ClickFix needs from
// it: a web address, a script of its own, or a .hta file.
bool MshtaCommand(View t) {
  for (size_t at = FindWord(t, "mshta"); at != View::npos;
       at = FindWord(t, "mshta", at + 1)) {
    const View rest = SkipBlanks(After(t, at + 5));
    for (View target : {View("http"), View("\\\\"), View("vbscript:"),
                        View("javascript:"), View("about:"), View("file:"),
                        View("\""), View("'")}) {
      if (rest.substr(0, target.size()) == target) {
        return true;
      }
    }
    if (Contains(rest, ".hta")) {
      return true;
    }
  }
  return false;
}

// How many characters of `text` make up one command or path.
size_t WordLength(View text) {
  size_t n = 0;
  while (n < text.size() &&
         (IsWordChar(text[n]) || text[n] == '.' || text[n] == '/' ||
          text[n] == '\\' || text[n] == '-')) {
    ++n;
  }
  return n;
}

// What a download can be piped into on Windows to run it.
bool IsRunWord(View word) {
  const size_t slash = word.find_last_of("/\\");
  if (slash != View::npos) {
    word.remove_prefix(slash + 1);
  }
  if (word.size() > 4 && word.substr(word.size() - 4) == ".exe") {
    word.remove_suffix(4);
  }
  for (View shell : {View("cmd"), View("powershell"), View("pwsh"),
                     View("iex"), View("invoke-expression")}) {
    if (word == shell) {
      return true;
    }
  }
  return false;
}

// Something that fetches, a "|", then something that runs what came
// through: curl ... | iex, irm ... | powershell -.
bool PipedIntoShell(View t, size_t from) {
  const View rest = After(t, from);
  for (size_t bar = rest.find('|'); bar != View::npos;
       bar = rest.find('|', bar + 1)) {
    if (bar + 1 < rest.size() && rest[bar + 1] == '|') {
      ++bar;  // "||" is "or", not a pipe.
      continue;
    }
    const View target = SkipBlanks(rest.substr(bar + 1));
    if (IsRunWord(target.substr(0, WordLength(target)))) {
      return true;
    }
  }
  return false;
}

bool FetchedAndRun(View t) {
  for (View tool : {View("curl"), View("wget"), View("iwr"), View("irm"),
                    View("invoke-webrequest"), View("invoke-restmethod")}) {
    for (size_t at = FindWord(t, tool); at != View::npos;
         at = FindWord(t, tool, at + 1)) {
      if (PipedIntoShell(t, at + tool.size())) {
        return true;
      }
    }
  }
  return false;
}

// iex and Invoke-Expression run text as code. Alone the word is a stock
// ticker, so it needs a pipe in front of it or a download on its line.
bool InvokeExpression(View t) {
  for (View name : {View("iex"), View("invoke-expression")}) {
    for (size_t at = FindWord(t, name); at != View::npos;
         at = FindWord(t, name, at + 1)) {
      size_t i = at;
      while (i > 0 && IsBlank(t[i - 1])) {
        --i;
      }
      if (i > 0 && t[i - 1] == '|') {
        return true;
      }
      const View line = LineAt(t, at);
      if (HasWordAny(line, {"irm", "iwr", "invoke-restmethod",
                            "invoke-webrequest", "downloadstring",
                            "new-object", "frombase64string"}) ||
          Contains(line, "http://") || Contains(line, "https://")) {
        return true;
      }
    }
  }
  return false;
}

// Windows tools that scammers borrow to fetch and run things. Each one
// counts only with the option or target that makes it do that.
bool BorrowedTools(View t) {
  struct Tool {
    View word;
    std::vector<View> signs;
  };
  const Tool tools[] = {
      {"certutil", {"-urlcache", "/urlcache", "-decode", "/decode"}},
      {"bitsadmin", {"/transfer"}},
      {"regsvr32", {"scrobj", "/i:", "http"}},
      {"msiexec", {"http:", "https:"}},
      {"rundll32", {"javascript:", "http:", "https:", "mshtml"}},
      {"wscript", {"http", ".vbs", ".js", ".wsf", "//e:"}},
      {"cscript", {"http", ".vbs", ".js", ".wsf", "//e:"}},
      {"conhost", {"--headless"}},
  };
  for (const Tool& tool : tools) {
    for (size_t at = FindWord(t, tool.word); at != View::npos;
         at = FindWord(t, tool.word, at + 1)) {
      const View rest = After(t, at + tool.word.size());
      for (View sign : tool.signs) {
        if (Contains(rest, sign)) {
          return true;
        }
      }
    }
  }
  return false;
}

bool LooksLikeCommandText(View text) {
  std::string lowered;
  lowered.reserve(text.size());
  for (char c : text) {
    lowered.push_back(Lower(c));
  }
  const View t = lowered;
  return PowerShellCommand(t) || CmdCommand(t) || MshtaCommand(t) ||
         FetchedAndRun(t) || InvokeExpression(t) || BorrowedTools(t);
}

// Without the blank space a page pads a command with.
View Trimmed(View text) {
  const auto is_space = [](char c) {
    return c == ' ' || c == '\t' || c == '\r' || c == '\n';
  };
  while (!text.empty() && is_space(text.front())) {
    text.remove_prefix(1);
  }
  while (!text.empty() && is_space(text.back())) {
    text.remove_suffix(1);
  }
  return text;
}

}  // namespace

bool LooksLikeShellCommand(std::string_view text) {
  text = Trimmed(text);
  if (text.size() < kMinLength) {
    return false;
  }
  if (text.size() > kMaxLength) {
    // Padding must not hide a command: a page can put 64 KB of filler on
    // either side of it, or both. Windows of kEdge + kReach, stepping by
    // kEdge, hold every command start with its arguments.
    if (text.size() <= kScanCap) {
      for (size_t at = 0; at < text.size(); at += kEdge) {
        if (LooksLikeCommandText(text.substr(at, kEdge + kReach))) {
          return true;
        }
      }
      return false;
    }
    // Huge text: what a terminal runs is still at one end.
    return LooksLikeCommandText(text.substr(0, kEdge)) ||
           LooksLikeCommandText(text.substr(text.size() - kEdge));
  }
  return LooksLikeCommandText(text);
}

}  // namespace guards
}  // namespace boring
