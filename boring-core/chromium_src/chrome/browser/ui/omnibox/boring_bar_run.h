// Copyright 2026 boring. BSD style license.

#ifndef CHROME_BROWSER_UI_OMNIBOX_BORING_BAR_RUN_H_
#define CHROME_BROWSER_UI_OMNIBOX_BORING_BAR_RUN_H_

struct AutocompleteMatch;
class OmniboxClient;

// True for a Do row of the Bar: a match our own provider
// (chrome/browser/autocomplete/boring_bar_provider.cc) made, carrying an
// id from its table. Such a row is run, never opened as an address.
bool BoringBarIsDoRow(const AutocompleteMatch& match);

// Runs a Do row in the window the address bar belongs to, through the
// window's normal command path. Does nothing outside a browser window or
// for an id that is not in the table.
void BoringBarRunRow(OmniboxClient* client, const AutocompleteMatch& match);

#endif  // CHROME_BROWSER_UI_OMNIBOX_BORING_BAR_RUN_H_
