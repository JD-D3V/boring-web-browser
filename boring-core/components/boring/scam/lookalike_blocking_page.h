// Copyright 2026 boring. BSD style license.

#ifndef COMPONENTS_BORING_SCAM_LOOKALIKE_BLOCKING_PAGE_H_
#define COMPONENTS_BORING_SCAM_LOOKALIKE_BLOCKING_PAGE_H_

#include <memory>
#include <string>

#include "components/security_interstitials/content/security_interstitial_page.h"
#include "url/gurl.h"

namespace content {
class BrowserContext;
class WebContents;
}  // namespace content

namespace boring {

// The full page warning shown before a site whose name copies another
// site's loads. Same page as the scam warning (see warning_page.h). The
// main button goes to the real site; "Continue anyway" is there unless
// "No way past scam warnings" is on.
class LookalikeBlockingPage
    : public security_interstitials::SecurityInterstitialPage {
 public:
  static const security_interstitials::SecurityInterstitialPage::TypeID
      kTypeForTesting;

  // `safe_url` is the real site, or empty when the address copies no one
  // site in particular (letters of other alphabets mixed to fool the eye).
  // `domain` is the copy's eTLD+1, which "Continue anyway" lets through.
  static std::unique_ptr<LookalikeBlockingPage> Create(
      content::WebContents* web_contents,
      const GURL& request_url,
      const GURL& safe_url,
      const std::string& domain);

  LookalikeBlockingPage(
      content::WebContents* web_contents,
      const GURL& request_url,
      const GURL& safe_url,
      bool no_bypass,
      std::unique_ptr<
          security_interstitials::SecurityInterstitialControllerClient>
          controller);
  ~LookalikeBlockingPage() override;

  // security_interstitials::SecurityInterstitialPage:
  std::string GetHTMLContents() override;
  void OnInterstitialClosing() override;
  void CommandReceived(const std::string& command) override;
  TypeID GetTypeForTesting() override;

 protected:
  void PopulateInterstitialStrings(base::DictValue& load_time_data) override;

 private:
  const GURL safe_url_;
  const bool no_bypass_;
};

// Remembers that the person chose to continue to this site (its eTLD+1),
// and asks whether they did. In an ordinary window this is kept in the
// profile's prefs (prefs::kLookalikeAllowedSites, local only), so the
// warning does not come back. A private window only remembers for its own
// session: waving a warning through in an ordinary window must not also wave
// it through in an incognito one.
void AllowLookalike(content::BrowserContext* context,
                    const std::string& domain);
bool IsLookalikeAllowed(content::BrowserContext* context,
                        const std::string& domain);
// Takes a remembered "Continue anyway" back, for "Forget this site".
void ForgetLookalike(content::BrowserContext* context,
                     const std::string& domain);

}  // namespace boring

#endif  // COMPONENTS_BORING_SCAM_LOOKALIKE_BLOCKING_PAGE_H_
