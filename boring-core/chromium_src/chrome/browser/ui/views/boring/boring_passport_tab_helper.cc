// Copyright 2026 boring. BSD style license.

#include "chrome/browser/ui/views/boring/boring_passport_tab_helper.h"

#include <algorithm>
#include <utility>

#include "base/functional/bind.h"
#include "base/values.h"
#include "chrome/browser/history/history_service_factory.h"
#include "chrome/browser/lookalikes/lookalike_url_service.h"
#include "chrome/browser/lookalikes/lookalike_url_service_factory.h"
#include "chrome/browser/password_manager/factories/profile_password_store_factory.h"
#include "chrome/browser/profiles/profile.h"
#include "components/autofill/content/browser/content_autofill_client.h"
#include "components/autofill/core/browser/autofill_field.h"
#include "components/autofill/core/browser/autofill_type.h"
#include "components/autofill/core/browser/field_types.h"
#include "components/autofill/core/browser/form_structure.h"
#include "components/boring/core/boring_prefs.h"
#include "components/boring/scam/lookalike_blocking_page.h"
#include "components/boring/scam/lookalike_brands.h"
#include "components/boring/scam/scam_blocking_page.h"
#include "components/boring/scam/scam_service.h"
#include "components/history/core/browser/history_service.h"
#include "components/history/core/browser/history_types.h"
#include "components/keyed_service/core/service_access_type.h"
#include "components/lookalikes/core/lookalike_url_util.h"
#include "components/password_manager/core/browser/password_form.h"
#include "components/password_manager/core/browser/password_form_digest.h"
#include "components/password_manager/core/browser/password_store/password_store_interface.h"
#include "components/password_manager/core/browser/password_store/stored_credential.h"
#include "components/prefs/pref_service.h"
#include "components/prefs/scoped_user_pref_update.h"
#include "components/security_interstitials/content/security_interstitial_page.h"
#include "components/security_interstitials/content/security_interstitial_tab_helper.h"
#include "components/url_formatter/url_formatter.h"
#include "content/public/browser/invalidate_type.h"
#include "content/public/browser/navigation_entry.h"
#include "content/public/browser/navigation_controller.h"
#include "content/public/browser/page.h"
#include "content/public/browser/render_frame_host.h"
#include "content/public/browser/web_contents.h"
#include "content/public/common/page_type.h"
#include "net/base/registry_controlled_domains/registry_controlled_domain.h"
#include "net/base/url_util.h"
#include "url/gurl.h"
#include "url/origin.h"

namespace {

Profile* ProfileOf(content::WebContents* contents) {
  return Profile::FromBrowserContext(contents->GetBrowserContext());
}

// The page's origin and its www twin (same scheme and port): history keeps
// them apart, a person does not.
std::vector<url::Origin> OriginsOf(const GURL& url) {
  const url::Origin origin = url::Origin::Create(url);
  const std::string host(url.host());
  std::string twin = host.starts_with("www.") ? host.substr(4) : "www." + host;
  GURL::Replacements swap;
  swap.SetHostStr(twin);
  const GURL twin_url = url.ReplaceComponents(swap);
  std::vector<url::Origin> out = {origin};
  if (twin_url.is_valid() && !twin.empty()) {
    out.push_back(url::Origin::Create(twin_url));
  }
  return out;
}

// The same early outs as the look-alike warning (lookalike_navigation_
// throttle.cc FindLookalike): nothing to say about a name that is not on
// the public web, a safe ending, or one of the 10,000 most visited sites.
bool LookalikeCandidate(const GURL& url) {
  const std::string host(url.host());
  if (lookalikes::GetETLDPlusOne(host).empty() || lookalikes::IsSafeTLD(host)) {
    return false;
  }
  const std::string domain =
      net::registry_controlled_domains::GetDomainAndRegistry(
          host, net::registry_controlled_domains::INCLUDE_PRIVATE_REGISTRIES);
  return !url_formatter::IsDomainAndRegistryATopDomain(
      domain.empty() ? lookalikes::GetETLDPlusOne(host) : domain);
}

bool IsSiteEngagementMatch(lookalikes::LookalikeUrlMatchType type) {
  using Type = lookalikes::LookalikeUrlMatchType;
  return type == Type::kSkeletonMatchSiteEngagement ||
         type == Type::kEditDistanceSiteEngagement ||
         type == Type::kCharacterSwapSiteEngagement ||
         type == Type::kComboSquattingSiteEngagement;
}

}  // namespace

// static
BoringPassportTabHelper* BoringPassportTabHelper::GetOrCreate(
    content::WebContents* contents) {
  if (!contents) {
    return nullptr;
  }
  CreateForWebContents(contents);
  return FromWebContents(contents);
}

BoringPassportTabHelper::BoringPassportTabHelper(content::WebContents* contents)
    : content::WebContentsObserver(contents),
      content::WebContentsUserData<BoringPassportTabHelper>(*contents) {
  // A mark made in any tab of this profile shows here at once.
  marks_.Init(ProfileOf(contents)->GetPrefs());
  marks_.Add(boring::prefs::kPassportKnownSites,
             base::BindRepeating(&BoringPassportTabHelper::Changed,
                                 base::Unretained(this)));
  // Frames that already exist are observed too; later ones are picked up as
  // they appear. No client (a tab without autofill) means no card row.
  if (autofill::ContentAutofillClient* client =
          autofill::ContentAutofillClient::FromWebContents(contents)) {
    autofill_managers_.Observe(
        client, autofill::ScopedAutofillManagersObservation::
                    InitializationPolicy::kObservePreexistingManagers);
  }
  StartQueries();
}

BoringPassportTabHelper::~BoringPassportTabHelper() = default;

bool BoringPassportTabHelper::Eligible() const {
  content::NavigationEntry* entry =
      web_contents()->GetController().GetLastCommittedEntry();
  const GURL url = web_contents()->GetLastCommittedURL();
  // While another address is loading the field shows that one: Chromium's
  // own icon, never facts about a page that is on its way out.
  if (!entry || web_contents()->GetVisibleURL() != url ||
      !url.SchemeIsHTTPOrHTTPS() || !url.has_host()) {
    return false;
  }
  // Error pages and Chromium's own interstitials keep Chromium's icon; our
  // scam and look-alike warnings carry the Blocked chip.
  if (entry->GetPageType() != content::PAGE_TYPE_NORMAL && !BlockedPage()) {
    return false;
  }
  const std::string host(url.host());
  return !net::HostStringIsLocalhost(host) && !url.HostIsIPAddress() &&
         !net::IsHostnameNonUnique(host);
}

bool BoringPassportTabHelper::BlockedPage() const {
  auto* helper =
      security_interstitials::SecurityInterstitialTabHelper::FromWebContents(
          web_contents());
  if (!helper || !helper->IsDisplayingInterstitial()) {
    return false;
  }
  security_interstitials::SecurityInterstitialPage* page =
      helper->GetBlockingPageForCurrentlyCommittedNavigationForTesting();
  if (!page) {
    return false;
  }
  const auto type = page->GetTypeForTesting();
  return type == boring::ScamBlockingPage::kTypeForTesting ||
         type == boring::LookalikeBlockingPage::kTypeForTesting;
}

bool BoringPassportTabHelper::MarkedKnown() const {
  const GURL url = web_contents()->GetLastCommittedURL();
  const std::string site = boring::GetBlockingSite(url);
  if (site.empty()) {
    return false;
  }
  const base::ListValue& marks =
      ProfileOf(web_contents())->GetPrefs()->GetList(
          boring::prefs::kPassportKnownSites);
  return std::ranges::contains(marks, base::Value(site));
}

void BoringPassportTabHelper::SetMarkedKnown(bool known) {
  const std::string site =
      boring::GetBlockingSite(web_contents()->GetLastCommittedURL());
  if (site.empty()) {
    return;
  }
  // Only the chip and the Passport read this list. It never reaches the
  // scam list, the look-alike allow list or any blocking.
  ScopedListPrefUpdate update(ProfileOf(web_contents())->GetPrefs(),
                              boring::prefs::kPassportKnownSites);
  update->EraseValue(base::Value(site));
  if (known) {
    update->Append(site);
  }
}

boring::passport::ChipInputs BoringPassportTabHelper::Inputs(
    bool editing_or_empty,
    bool chromium_text) const {
  boring::passport::ChipInputs in;
  in.eligible = !editing_or_empty && Eligible();
  if (!in.eligible) {
    return in;
  }
  const GURL url = web_contents()->GetLastCommittedURL();
  boring::ScamService* scam = boring::ScamService::GetInstance();
  in.blocked_page = BlockedPage();
  in.scam_listed = scam->IsListed(url);
  in.chromium_text = chromium_text;
  in.marked_known = MarkedKnown();
  const bool same_page = FactsAreFor(url);
  in.visited_before_today = same_page && facts_.days_before_today > 0;
  in.lookalike = same_page && facts_.lookalike;
  in.pending = !same_page || facts_.pending > 0 ||
               scam->status() == boring::ScamService::Status::kLoading;
  return in;
}

bool BoringPassportTabHelper::FactsAreFor(const GURL& url) const {
  return facts_.url.is_valid() &&
         url::Origin::Create(facts_.url).IsSameOriginWith(url);
}

void BoringPassportTabHelper::PrimaryPageChanged(content::Page& page) {
  StartQueries();
  Changed();
}

void BoringPassportTabHelper::OnFieldTypesDetermined(
    autofill::AutofillManager& manager,
    autofill::FormGlobalId form,
    FieldTypeSource source,
    bool small_forms_were_parsed) {
  if (facts_.asks_card) {
    return;  // Sticky for this page.
  }
  const autofill::FormStructure* structure = manager.FindCachedFormById(form);
  if (!structure) {
    return;
  }
  for (const auto& field : structure->fields()) {
    const autofill::FieldTypeSet types = field->Type().GetTypes();
    if (types.contains(autofill::CREDIT_CARD_NUMBER) ||
        types.contains(autofill::CREDIT_CARD_VERIFICATION_CODE)) {
      facts_.asks_card = true;
      Changed();
      return;
    }
  }
}

void BoringPassportTabHelper::StartQueries() {
  tracker_.TryCancelAll();
  consumer_weak_factory_.InvalidateWeakPtrs();
  ++generation_;
  facts_ = Facts();
  content::NavigationEntry* entry =
      web_contents()->GetController().GetLastCommittedEntry();
  const GURL url = web_contents()->GetLastCommittedURL();
  if (!entry || !url.SchemeIsHTTPOrHTTPS() || !url.has_host()) {
    return;
  }
  facts_.url = url;
  facts_.cutoff = entry->GetTimestamp();
  facts_.scam_listed = boring::ScamService::GetInstance()->IsListed(url);
  Profile* profile = ProfileOf(web_contents());
  const int generation = generation_;

  // History. In a private window this reads the normal profile's history,
  // which is what "you have visited" means; nothing is written.
  if (history::HistoryService* history = HistoryServiceFactory::GetForProfile(
          profile, ServiceAccessType::EXPLICIT_ACCESS)) {
    const base::Time midnight = base::Time::Now().LocalMidnight();
    for (const url::Origin& origin : OriginsOf(url)) {
      ++facts_.pending;
      history->GetDailyVisitsToOrigin(
          origin, base::Time(), facts_.cutoff,
          history::VisitQuery404sPolicy::kExclude404s,
          base::BindOnce(
              [](base::WeakPtr<BoringPassportTabHelper> self, int generation,
                 history::DailyVisitsResult result) {
                if (self && generation == self->generation_) {
                  if (result.success) {
                    self->facts_.visits_before += result.total_visits;
                  }
                  self->Answered(generation);
                }
              },
              weak_factory_.GetWeakPtr(), generation),
          &tracker_);
      ++facts_.pending;
      history->GetDailyVisitsToOrigin(
          origin, base::Time(), std::min(midnight, facts_.cutoff),
          history::VisitQuery404sPolicy::kExclude404s,
          base::BindOnce(
              [](base::WeakPtr<BoringPassportTabHelper> self, int generation,
                 history::DailyVisitsResult result) {
                if (self && generation == self->generation_) {
                  if (result.success) {
                    self->facts_.days_before_today += result.days_with_visits;
                  }
                  self->Answered(generation);
                }
              },
              weak_factory_.GetWeakPtr(), generation),
          &tracker_);
      ++facts_.pending;
      history->GetVisibleVisitCountToHost(
          origin.GetURL(),
          base::BindOnce(
              [](base::WeakPtr<BoringPassportTabHelper> self, int generation,
                 history::VisibleVisitCountToHostResult result) {
                if (self && generation == self->generation_) {
                  if (result.success) {
                    self->facts_.visits_total += result.count;
                    if (!result.first_visit.is_null() &&
                        (self->facts_.first_visit.is_null() ||
                         result.first_visit < self->facts_.first_visit)) {
                      self->facts_.first_visit = result.first_visit;
                    }
                  }
                  self->Answered(generation);
                }
              },
              weak_factory_.GetWeakPtr(), generation),
          &tracker_);
    }
  }

  // Looks like a site you use: the matched name comes from this profile's
  // own site engagement, never from the page.
  if (LookalikeCandidate(url)) {
    if (LookalikeUrlService* service =
            LookalikeUrlServiceFactory::GetForProfile(profile)) {
      if (service->EngagedSitesNeedUpdating()) {
        ++facts_.pending;
        service->ForceUpdateEngagedSites(base::BindOnce(
            [](base::WeakPtr<BoringPassportTabHelper> self, int generation,
               const std::vector<lookalikes::DomainInfo>& sites) {
              if (self) {
                self->OnEngagedSites(generation, sites);
                self->Answered(generation);
              }
            },
            weak_factory_.GetWeakPtr(), generation));
      } else {
        OnEngagedSites(generation, service->GetLatestEngagedSites());
      }
    }
    // A well known brand (lookalike_brands.h): only seen here after
    // "Continue anyway" on the look-alike warning.
    if (!facts_.lookalike) {
      const std::string domain =
          net::registry_controlled_domains::GetDomainAndRegistry(
              url.host(),
              net::registry_controlled_domains::INCLUDE_PRIVATE_REGISTRIES);
      const std::string brand = boring::FindLookalikeBrand(domain);
      if (!brand.empty()) {
        facts_.lookalike = true;
        facts_.lookalike_of = brand;
      }
    }
  }

  // Is there a saved password for this exact origin? Only the count of
  // exact, not-blocked entries is kept; the results are dropped at once.
  if (scoped_refptr<password_manager::PasswordStoreInterface> store =
          ProfilePasswordStoreFactory::GetForProfile(
              profile, ServiceAccessType::EXPLICIT_ACCESS)) {
    ++facts_.pending;
    const GURL origin_url = url::Origin::Create(url).GetURL();
    store->GetLogins(
        password_manager::PasswordFormDigest(
            password_manager::PasswordForm::Scheme::kHtml, origin_url.spec(),
            origin_url),
        consumer_weak_factory_.GetWeakPtr());
  }
}

void BoringPassportTabHelper::OnEngagedSites(
    int generation,
    const std::vector<lookalikes::DomainInfo>& sites) {
  if (generation != generation_) {
    return;
  }
  std::string matched;
  lookalikes::LookalikeUrlMatchType type =
      lookalikes::LookalikeUrlMatchType::kNone;
  if (lookalikes::GetMatchingDomain(
          lookalikes::GetDomainInfo(facts_.url), sites,
          base::BindRepeating([](const std::string&) { return false; }),
          /*config_proto=*/nullptr, &matched, &type) &&
      IsSiteEngagementMatch(type)) {
    facts_.lookalike = true;
    facts_.lookalike_of = lookalikes::GetETLDPlusOne(matched);
    facts_.lookalike_used_site = true;
  }
}

void BoringPassportTabHelper::OnGetPasswordStoreResultsOrErrorFrom(
    password_manager::PasswordStoreInterface* store,
    base::expected<std::vector<password_manager::StoredCredential>,
                   password_manager::PasswordStoreBackendError>
        results_or_error) {
  bool found = false;
  if (results_or_error.has_value()) {
    for (const password_manager::StoredCredential& credential :
         results_or_error.value()) {
      if (!credential.blocked_by_user && credential.match_type.has_value() &&
          *credential.match_type == affiliations::MatchType::kExact) {
        found = true;
        break;
      }
    }
  }
  facts_.saved_password = found;
  Answered(generation_);
}

void BoringPassportTabHelper::Answered(int generation) {
  if (generation != generation_) {
    return;
  }
  facts_.pending = std::max(0, facts_.pending - 1);
  Changed();
}

void BoringPassportTabHelper::Changed() {
  web_contents()->NotifyNavigationStateChanged(content::INVALIDATE_TYPE_URL);
}

base::DictValue BoringPassportTabHelper::StateForTesting() const {
  base::DictValue out;
  out.Set("url", facts_.url.spec());
  out.Set("pending", facts_.pending);
  out.Set("visitsBefore", facts_.visits_before);
  out.Set("visitsTotal", facts_.visits_total);
  out.Set("daysBeforeToday", facts_.days_before_today);
  out.Set("firstVisitDaysAgo",
          facts_.first_visit.is_null()
              ? -1
              : static_cast<int>(
                    (base::Time::Now() - facts_.first_visit).InDays()));
  out.Set("lookalike", facts_.lookalike);
  out.Set("lookalikeOf", facts_.lookalike_of);
  out.Set("lookalikeUsedSite", facts_.lookalike_used_site);
  out.Set("asksCard", facts_.asks_card);
  out.Set("scamListed", facts_.scam_listed);
  out.Set("savedPassword", facts_.saved_password);
  out.Set("eligible", Eligible());
  out.Set("blockedPage", BlockedPage());
  out.Set("markedKnown", MarkedKnown());
  return out;
}

WEB_CONTENTS_USER_DATA_KEY_IMPL(BoringPassportTabHelper);
