// Copyright 2026 boring. BSD style license.

#ifndef COMPONENTS_BORING_ASSISTANCE_ASSISTANCE_TEST_HOOK_H_
#define COMPONENTS_BORING_ASSISTANCE_ASSISTANCE_TEST_HOOK_H_

#include "base/values.h"

namespace content {
class WebContents;
}

namespace boring {

// Test only. With this switch the new tab page takes "assistanceTest"
// messages, which smoke_assistance_ui.py uses to open and drive the Ask
// Gemini panel without any input from the OS.
inline constexpr char kAssistanceTestSwitch[] = "boring-assistance-test";

// Test only. Honoured only together with kAssistanceTestSwitch, and only for
// an http://127.0.0.1:<port>/ URL, so a test can point the panel at a fake
// Gemini that runs on this machine and nothing leaves it.
inline constexpr char kAssistanceProviderForTestSwitch[] =
    "boring-assistance-provider-for-test";

// Declared here for the new tab page and defined in
// chrome/browser/ui/views/boring/boring_assistance_panel.cc, which is built
// into chrome/browser/ui (the panel lives in a browser window, which
// components/boring cannot reach). The same split as search_engine_menu.h.

// Runs one test command, see kAssistanceTestSwitch. The first element of
// `args` names the command:
//   ["open", url_part]    find the tab whose address contains url_part, in
//                         any window, make it active and open its panel
//   ["state"]             report that tab's panel
//   ["setQuestion", text] set the question
//   ["preview"]           show the exact text that would be shared
//   ["share"]             press "Ask Gemini with this page"
//   ["find"]              press "Find on page" (local, nothing is shared)
//   ["showMatch", index]  outline one Find result
//   ["showMe"]            outline the control the reply named
//   ["pressSend"]         stand in for the person pressing the chat's Send
//   ["close"]             close the panel
// "open" returns {found, available}; "state" returns {open, showing,
// available, sourceUrl, providerUrl, state, reason, canShowMe, prompt,
// status, previewing, matches}. Returns none without the switch.
base::Value RunAssistanceTestCommand(content::WebContents* page,
                                     const base::ListValue& args);

}  // namespace boring

#endif  // COMPONENTS_BORING_ASSISTANCE_ASSISTANCE_TEST_HOOK_H_
