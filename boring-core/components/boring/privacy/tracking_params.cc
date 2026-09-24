// Copyright (c) 2023 The Brave Authors. All rights reserved.
// This Source Code Form is subject to the terms of the Mozilla Public
// License, v. 2.0. If a copy of the MPL was not distributed with this file,
// You can obtain one at https://mozilla.org/MPL/2.0/.
//
// Adapted for Boring Browser, 2026, from brave-core
// components/query_filter/utils.cc (commit d4354a2e5e24), keeping its
// lists and its rules for when to strip. This file stays under the
// MPL-2.0; the rest of the browser's own code is MIT.

#include "components/boring/privacy/tracking_params.h"

#include <string>
#include <string_view>
#include <vector>

#include "base/containers/fixed_flat_map.h"
#include "base/containers/fixed_flat_set.h"
#include "base/strings/string_split.h"
#include "base/strings/string_util.h"
#include "net/base/registry_controlled_domains/registry_controlled_domain.h"

namespace boring {

namespace {

// Parameters that exist only to follow a person from one site to the
// next: click identifiers, email campaign identifiers and the like.
// Campaign labels such as utm_source are left alone, as Brave does:
// they name a campaign, not a person.
constexpr auto kTrackers =
    base::MakeFixedFlatSet<std::string_view>(base::sorted_unique,
                                             {
                                                 "__hsfp",
                                                 "__hssc",
                                                 "__hstc",
                                                 "__s",
                                                 "_bhlid",
                                                 "_branch_match_id",
                                                 "_branch_referrer",
                                                 "_gl",
                                                 "_hsenc",
                                                 "_kx",
                                                 "_openstat",
                                                 "at_recipient_id",
                                                 "at_recipient_list",
                                                 "bbeml",
                                                 "bsft_clkid",
                                                 "bsft_uid",
                                                 "dclid",
                                                 "et_rid",
                                                 "fb_action_ids",
                                                 "fb_comment_id",
                                                 "fbclid",
                                                 "gclid",
                                                 "guce_referrer",
                                                 "guce_referrer_sig",
                                                 "hsCtaTracking",
                                                 "irclickid",
                                                 "mc_eid",
                                                 "ml_subscriber",
                                                 "ml_subscriber_hash",
                                                 "msclkid",
                                                 "mtm_cid",
                                                 "oft_c",
                                                 "oft_ck",
                                                 "oft_d",
                                                 "oft_id",
                                                 "oft_ids",
                                                 "oft_k",
                                                 "oft_lk",
                                                 "oft_sk",
                                                 "oly_anon_id",
                                                 "oly_enc_id",
                                                 "pk_cid",
                                                 "rb_clickid",
                                                 "s_cid",
                                                 "sc_customer",
                                                 "sc_eh",
                                                 "sc_uid",
                                                 "sfmc_activityid",
                                                 "sfmc_id",
                                                 "sms_click",
                                                 "sms_source",
                                                 "sms_uph",
                                                 "srsltid",
                                                 "ss_email_id",
                                                 "syclid",
                                                 "ttclid",
                                                 "twclid",
                                                 "unicorn_click_id",
                                                 "vero_conv",
                                                 "vero_id",
                                                 "vgo_ee",
                                                 "wbraid",
                                                 "wickedid",
                                                 "yclid",
                                                 "ymclid",
                                                 "ysclid",
                                             });

// Removed only when the address does not contain the text given, so an
// unsubscribe link that needs its identifier keeps it.
constexpr auto kConditionalTrackers =
    base::MakeFixedFlatMap<std::string_view, std::string_view>({
        {"ck_subscriber_id", "/unsubscribe"},
        {"h_sid", "/email/"},
        {"h_slt", "/email/"},
        {"mkt_tok", "nsubscribe"},
    });

// mkt_tok also has to survive on email web views.
constexpr std::string_view kMktTokAlsoKeptOn = "emailWebview";

struct Scoped {
  std::string_view param;
  std::string_view domains[2];
};

// Removed only on these sites and their subdomains.
constexpr Scoped kScopedTrackers[] = {
    {"igsh", {"instagram.com", ""}},
    {"igshid", {"instagram.com", ""}},
    {"ref_src", {"twitter.com", "x.com"}},
    {"ref_url", {"twitter.com", "x.com"}},
    {"si", {"youtube.com", "youtu.be"}},
};

// Addresses never changed. Exact host match.
constexpr auto kExemptHosts =
    base::MakeFixedFlatSet<std::string_view>(base::sorted_unique,
                                             {
                                                 "urldefense.com",
                                             });

bool IsScopedTracker(std::string_view key, const GURL& url) {
  for (const Scoped& scoped : kScopedTrackers) {
    if (scoped.param != key) {
      continue;
    }
    for (std::string_view domain : scoped.domains) {
      if (!domain.empty() && url.DomainIs(domain)) {
        return true;
      }
    }
  }
  return false;
}

bool IsTracker(std::string_view key, const GURL& url) {
  if (kTrackers.contains(key) || IsScopedTracker(key, url)) {
    return true;
  }
  const auto conditional = kConditionalTrackers.find(key);
  if (conditional == kConditionalTrackers.end()) {
    return false;
  }
  const std::string& spec = url.spec();
  if (spec.find(conditional->second) != std::string::npos) {
    return false;
  }
  return !(key == "mkt_tok" &&
           spec.find(kMktTokAlsoKeptOn) != std::string::npos);
}

}  // namespace

std::optional<GURL> StripTrackingParams(const GURL& url) {
  if (!url.SchemeIsHTTPOrHTTPS() || !url.has_query() ||
      kExemptHosts.contains(url.host())) {
    return std::nullopt;
  }
  // Split on ampersands and rejoin what is left untouched, rather than
  // parsing and re-encoding, so nothing else about the address changes.
  std::vector<std::string_view> kept;
  bool removed = false;
  for (std::string_view pair : base::SplitStringPiece(
           url.query(), "&", base::KEEP_WHITESPACE, base::SPLIT_WANT_ALL)) {
    const std::vector<std::string_view> pieces = base::SplitStringPiece(
        pair, "=", base::KEEP_WHITESPACE, base::SPLIT_WANT_NONEMPTY);
    if (pieces.size() >= 2 && IsTracker(pieces[0], url)) {
      removed = true;
    } else {
      kept.push_back(pair);
    }
  }
  if (!removed) {
    return std::nullopt;
  }
  GURL::Replacements replacements;
  const std::string query = base::JoinString(kept, "&");
  if (query.empty()) {
    replacements.ClearQuery();
  } else {
    replacements.SetQueryStr(query);
  }
  return url.ReplaceComponents(replacements);
}

bool IsSameSite(const GURL& a, const GURL& b) {
  return net::registry_controlled_domains::SameDomainOrHost(
      a, b, net::registry_controlled_domains::INCLUDE_PRIVATE_REGISTRIES);
}

}  // namespace boring
