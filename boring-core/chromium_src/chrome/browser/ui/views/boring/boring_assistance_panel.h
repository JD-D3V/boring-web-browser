// Copyright 2026 boring. BSD style license.

#ifndef CHROME_BROWSER_UI_VIEWS_BORING_BORING_ASSISTANCE_PANEL_H_
#define CHROME_BROWSER_UI_VIEWS_BORING_BORING_ASSISTANCE_PANEL_H_

class BrowserWindowInterface;

namespace tabs {
class TabInterface;
}

namespace boring {

// True when the Ask Gemini panel may open for `tab`: an ordinary profile
// (not incognito or guest) showing an http or https page.
bool CanAssist(tabs::TabInterface* tab);

// Opens the Ask Gemini panel beside the active tab of `browser`, or closes
// it when it is already showing for that tab. The panel belongs to that
// tab: switching tabs hides it and never points it at the new tab.
void ToggleAssistancePanel(BrowserWindowInterface* browser);

}  // namespace boring

#endif  // CHROME_BROWSER_UI_VIEWS_BORING_BORING_ASSISTANCE_PANEL_H_
