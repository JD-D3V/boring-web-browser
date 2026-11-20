// Copyright 2026 boring. BSD style license.

#ifndef CHROME_BROWSER_UI_VIEWS_BORING_BORING_BAR_TEST_H_
#define CHROME_BROWSER_UI_VIEWS_BORING_BORING_BAR_TEST_H_

class LocationBarView;

// Test hook for the Bar (tools/smoke_bar.py). Does nothing unless the
// browser was started with --boring-bar-test. Then, a few seconds after the
// window opens, it works the Bar from inside the process (no input reaches
// the desktop) and writes boring-bar-test.txt in the profile folder:
//   --boring-bar-test=<text>[;enter][;open=<header>]
//       types <text>, waits for the results and writes one line per row
//       (group header, title, meta, selected); ";enter" then opens the
//       selected row as Enter would, ";open=<header>" the first row under
//       that header.
//   --boring-bar-test=keys
//       sends Ctrl+K and then Ctrl+E through the window's own accelerators
//       and writes focus, selection, keyword mode, the field's text and the
//       hint's text after each.
void BoringBarMaybeRunTest(LocationBarView* bar);

#endif  // CHROME_BROWSER_UI_VIEWS_BORING_BORING_BAR_TEST_H_
