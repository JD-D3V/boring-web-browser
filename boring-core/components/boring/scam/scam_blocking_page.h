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
// that Senior Safe Mode removes.
class ScamBlockingPage : public security_interstitials::SecurityInterstitialPage {
 public:
  static const security_interstitials::SecurityInterstitialPage::TypeID
      kTypeForTesting;

  static std::unique_ptr<ScamBlockingPage> Create(
      content::WebContents* web_contents,
      const GURL& request_url);

  ScamBlockingPage(
      content::WebContents* web_contents,
      const GURL& request_url,
      bool senior_safe_mode,
      std::unique_ptr<
          security_interstitials::SecurityInterstitialControllerClient>
          controller);
  ~ScamBlockingPage() override;

  // security_interstitials::SecurityInterstitialPage:
  std::string GetHTMLContents() override;
  void OnInterstitialClosing() override;
  void CommandReceived(const std::string& command) override;
  TypeID GetTypeForTesting() override;

 protected:
  void PopulateInterstitialStrings(base::DictValue& load_time_data) override;

 private:
  const bool senior_safe_mode_;
};

}  // namespace boring

#endif  // COMPONENTS_BORING_SCAM_SCAM_BLOCKING_PAGE_H_
