// Copyright 2026 boring. BSD style license.

#ifndef COMPONENTS_BORING_SCAM_SCAM_CONTROLLER_CLIENT_H_
#define COMPONENTS_BORING_SCAM_SCAM_CONTROLLER_CLIENT_H_

#include "components/security_interstitials/content/security_interstitial_controller_client.h"
#include "url/gurl.h"

class PrefService;

namespace content {
class WebContents;
}

namespace boring {

// Handles the two choices on the scam warning page.
class ScamControllerClient
    : public security_interstitials::SecurityInterstitialControllerClient {
 public:
  ScamControllerClient(content::WebContents* web_contents,
                       const GURL& request_url,
                       PrefService* prefs);
  ~ScamControllerClient() override;

  // security_interstitials::ControllerClient:
  void Proceed() override;

 private:
  const GURL request_url_;
};

}  // namespace boring

#endif  // COMPONENTS_BORING_SCAM_SCAM_CONTROLLER_CLIENT_H_
