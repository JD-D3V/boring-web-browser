// Copyright 2026 boring. BSD style license.

#ifndef CHROME_BROWSER_UI_VIEWS_BORING_BORING_FORGET_H_
#define CHROME_BROWSER_UI_VIEWS_BORING_BORING_FORGET_H_

#include <string>

#include "base/memory/weak_ptr.h"

class BrowserWindowInterface;
class GURL;
class Profile;

namespace content {
class WebContents;
}

namespace boring {

// "Forget this site", from the shield's panel, after the panel has asked.
// Deletes the site's cookies, storage and cache with Chromium's browsing
// data remover, the same as the site data dialog, resets what the person
// allowed or blocked for it, then reloads `tab`. `site` is a key from
// GetBlockingSite(): the registrable domain, or the IP address or
// internal name where there is no domain. `url` is the page it was
// asked on. The site's own rules (blocking off, clear when the browser
// closes, never sleep) are kept; they are choices about the site, not
// something it was told.
void ForgetSite(Profile* profile,
                const std::string& site,
                const GURL& url,
                base::WeakPtr<content::WebContents> tab);

// "Forget this session", from the app menu. Asks once with a plain
// dialog. On yes it closes every tab and window of the profile without
// running their unload prompts, deletes the history, cookies, site data
// and cache made since the browser started (what was there before is
// kept, sign-ins included), and opens one new tab.
void ShowForgetSessionDialog(BrowserWindowInterface* browser);

}  // namespace boring

#endif  // CHROME_BROWSER_UI_VIEWS_BORING_BORING_FORGET_H_
