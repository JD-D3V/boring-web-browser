// Copyright 2026 boring. BSD style license.

#include "components/boring/scam/scam_controller_client.h"

#include <memory>

#include "components/boring/scam/scam_service.h"
#include "components/security_interstitials/content/settings_page_helper.h"
#include "components/security_interstitials/core/metrics_helper.h"
#include "content/public/browser/browser_context.h"
#include "content/public/browser/web_contents.h"

namespace boring {

namespace {

std::unique_ptr<security_interstitials::MetricsHelper> MakeMetricsHelper(
    const GURL& url) {
  security_interstitials::MetricsHelper::ReportDetails details;
  details.metric_prefix = "boring_scam";
  return std::make_unique<security_interstitials::MetricsHelper>(url, details,
                                                                 nullptr);
}

}  // namespace

ScamControllerClient::ScamControllerClient(content::WebContents* web_contents,
                                           const GURL& request_url,
                                           PrefService* prefs)
    : security_interstitials::SecurityInterstitialControllerClient(
          web_contents,
          MakeMetricsHelper(request_url),
          prefs,
          "en-US",
          GURL("about:blank"),
          /*settings_page_helper=*/nullptr),
      request_url_(request_url),
      context_(web_contents ? web_contents->GetBrowserContext() : nullptr) {}

ScamControllerClient::~ScamControllerClient() = default;

void ScamControllerClient::Proceed() {
  ScamService::GetInstance()->AllowHostForSession(
      context_, std::string(request_url_.host()));
  Reload();
}

}  // namespace boring
