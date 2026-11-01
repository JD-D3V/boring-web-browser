// Copyright 2026 boring. BSD style license.

#ifndef COMPONENTS_BORING_GUARDS_SHELL_COMMAND_H_
#define COMPONENTS_BORING_GUARDS_SHELL_COMMAND_H_

#include <string_view>

namespace boring {
namespace guards {

// ClickFix: a fake "verify you are human" or "fix this error" page puts
// a command on the clipboard, then tells the person to press Win+R (or
// open a terminal), paste and press Enter. That hands the computer to
// the page's author. This says whether copied text looks like such a
// command: a PowerShell, cmd or mshta one-liner, a download piped into
// iex or a shell, an encoded blob, or one of the Windows tools scammers
// borrow (certutil, regsvr32 and the like).
//
// It looks for the commands themselves, wherever they sit in the text,
// because the page often adds a fake captcha comment around them. Plain
// sentences, addresses, URLs, ordinary code and the commands developer
// sites hand out every day (git, npm, pip, winget, a curl that prints a
// page, a Unix install script) do not match: the patterns aim at what a
// Windows run box takes.
//
// The trade-off is on purpose and written down: a Windows installer
// one-liner (irm ... | iex, as Scoop and Deno publish) matches too,
// because that is exactly the shape ClickFix copies. Those are rare for
// most people, and the guard has its own switch.
//
// Plain standard C++ on purpose: tools/tests/test_scam_guards.py
// compiles this file by itself and checks it against a table. `text` is
// UTF-8.
bool LooksLikeShellCommand(std::string_view text);

}  // namespace guards
}  // namespace boring

#endif  // COMPONENTS_BORING_GUARDS_SHELL_COMMAND_H_
