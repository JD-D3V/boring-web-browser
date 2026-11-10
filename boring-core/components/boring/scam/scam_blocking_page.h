// Copyright 2026 boring. BSD style license.

#ifndef COMPONENTS_BORING_SCAM_SCAM_BLOCKING_PAGE_H_
#define COMPONENTS_BORING_SCAM_SCAM_BLOCKING_PAGE_H_

#include <memory>
#include <string>

#include "components/security_interstitials/content/security_interstitial_page.h"

namespace content {
class WebContents;
}

namespace boring {

// The full page warning wall shown before a known scam or phishing site
// loads. Plain language, one safe way out, and a small continue link
// that "No way past scam warnings" removes.
//
// The same wall is shown for a site Quad9 refused to look up (see
// Quad9BlockThrottle), with its own words and never a continue link.
class ScamBlockingPage
    : public security_interstitials::SecurityInterstitialPage {
 public:
  static const security_interstitials::SecurityInterstitialPage::TypeID
      kTypeForTesting;

  static std::unique_ptr<ScamBlockingPage> Create(
      content::WebContents* web_contents,
      const GURL& request_url);
  static std::unique_ptr<ScamBlockingPage> CreateForQuad9Block(
      content::WebContents* web_contents,
      const GURL& request_url);

  ScamBlockingPage(
      content::WebContents* web_contents,
      const GURL& request_url,
      bool no_bypass,
      std::unique_ptr<
          security_interstitials::SecurityInterstitialControllerClient>
          controller,
      bool quad9_block = false);
  ~ScamBlockingPage() override;

  // security_interstitials::SecurityInterstitialPage:
  std::string GetHTMLContents() override;
  void OnInterstitialClosing() override;
  void CommandReceived(const std::string& command) override;
  TypeID GetTypeForTesting() override;

 protected:
  void PopulateInterstitialStrings(base::DictValue& load_time_data) override;

 private:
  const bool no_bypass_;
  const bool quad9_block_;
};

}  // namespace boring

#endif  // COMPONENTS_BORING_SCAM_SCAM_BLOCKING_PAGE_H_
