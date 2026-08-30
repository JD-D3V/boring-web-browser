// Copyright 2026 boring. BSD style license.

#include "components/boring/scam/scam_controller_client.h"

#include <memory>

#include "components/boring/scam/scam_service.h"
#include "components/security_interstitials/core/metrics_helper.h"
#include "ui/base/l10n/l10n_util.h"

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
          l10n_util::GetLocaleOverride().empty()
              ? "en-US"
              : l10n_util::GetLocaleOverride(),
          GURL("about:blank"),
          /*settings_page_helper=*/nullptr),
      request_url_(request_url) {}

ScamControllerClient::~ScamControllerClient() = default;

void ScamControllerClient::Proceed() {
  ScamService::GetInstance()->AllowHostForSession(request_url_.host());
  Reload();
}

}  // namespace boring
