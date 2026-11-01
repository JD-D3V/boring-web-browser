// Copyright 2026 boring. BSD style license.

#ifndef COMPONENTS_BORING_GUARDS_REMOTE_ACCESS_TOOLS_H_
#define COMPONENTS_BORING_GUARDS_REMOTE_ACCESS_TOOLS_H_

#include <string>
#include <string_view>

namespace boring {
namespace guards {

// Remote access tools are the pivot step in tech support and bank
// scams: the caller says "install this so I can help", and from then on
// they are at the keyboard. The real products are fine software, so the
// browser does not block them. It asks first, in plain words.
//
// Decides from the name of the downloaded file and, where the name says
// nothing (a "setup.exe" from the vendor's own server), the host the
// file came from. Returns the tool's display name, or an empty string
// when this does not look like one. Only program and archive file types
// count, so a manual called anydesk-guide.pdf is left alone.
//
// Plain standard C++ on purpose: tools/tests/test_scam_guards.py
// compiles this file by itself and checks it against a table.
std::string MatchRemoteAccessTool(std::string_view file_name,
                                  std::string_view host);

}  // namespace guards
}  // namespace boring

#endif  // COMPONENTS_BORING_GUARDS_REMOTE_ACCESS_TOOLS_H_
