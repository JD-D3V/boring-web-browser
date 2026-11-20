// Copyright 2026 boring. BSD style license.

#ifndef COMPONENTS_BORING_PASSPORT_PASSPORT_TEST_H_
#define COMPONENTS_BORING_PASSPORT_PASSPORT_TEST_H_

#include "base/values.h"

namespace content {
class WebContents;
}

namespace boring::passport {

// Test only. With kPassportTestSwitch (passport_words.h) the new tab page
// takes "passportTest" messages, which smoke_passport.py uses to read and
// drive the Passport without any input from the OS. Declared here for the
// new tab page and defined in
// chrome/browser/ui/views/boring/boring_passport_test.cc, built into the
// location bar (the same split as search_engine_menu.h). Returns none
// without the switch.
base::Value RunPassportTestCommand(content::WebContents* page,
                                   const base::ListValue& args);

}  // namespace boring::passport

#endif  // COMPONENTS_BORING_PASSPORT_PASSPORT_TEST_H_
