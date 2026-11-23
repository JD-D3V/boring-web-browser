// Copyright 2026 boring. BSD style license.

#include "chrome/browser/ui/views/boring/boring_passport_tab_helper.h"

#include <algorithm>
#include <utility>

#include "base/functional/bind.h"
#include "base/functional/callback.h"
#include "base/location.h"
#include "base/values.h"
#include "chrome/browser/content_settings/host_content_settings_map_factory.h"
#include "chrome/browser/history/history_service_factory.h"
#include "chrome/browser/lookalikes/lookalike_url_service.h"
#include "chrome/browser/lookalikes/lookalike_url_service_factory.h"
#include "chrome/browser/password_manager/factories/profile_password_store_factory.h"
#include "chrome/browser/profiles/profile.h"
#include "chrome/browser/ui/views/boring/boring_passport_bubble.h"
#include "chrome/common/chrome_isolated_world_ids.h"
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
#include "components/content_settings/core/browser/host_content_settings_map.h"
#include "components/content_settings/core/common/content_settings.h"
#include "components/content_settings/core/common/content_settings_types.h"
#include "components/history/core/browser/history_database.h"
#include "components/history/core/browser/history_db_task.h"
#include "components/history/core/browser/history_service.h"
#include "components/history/core/browser/history_types.h"
#include "components/history/core/browser/url_row.h"
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
  // Only within one registrable domain: www.netlify.app's twin would be the
  // public suffix itself, and its visits are not the tenant's.
  using net::registry_controlled_domains::GetDomainAndRegistry;
  using net::registry_controlled_domains::INCLUDE_PRIVATE_REGISTRIES;
  const std::string domain =
      GetDomainAndRegistry(host, INCLUDE_PRIVATE_REGISTRIES);
  if (twin_url.is_valid() && !twin.empty() && !domain.empty() &&
      domain == GetDomainAndRegistry(twin, INCLUDE_PRIVATE_REGISTRIES)) {
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

// The one question the card fact asks a page's frame when autofill does not
// parse forms. Fixed text, run in an isolated world (never the page's own),
// and its only answer is true or false: no value, no other attribute.
constexpr char16_t kAsksCardScript[] =
    u"!!document.querySelector('input[autocomplete*=\"cc-number\" i],"
    u"input[autocomplete*=\"cc-csc\" i]')";

int64_t Micros(base::Time time) {
  return time.ToDeltaSinceWindowsEpoch().InMicroseconds();
}

// Bounds on what one page's question reads, so a site with a very long
// history costs a bounded amount. The address field's own suggestions read
// the same rows (urls by prefix, most typed first).
constexpr size_t kMaxUrlsPerSite = 1000;
constexpr size_t kMaxVisitsPerSite = 20000;

using SiteVisits = std::vector<boring::passport::SiteVisit>;

// Known site's days need each visit's type (who started it), which no
// per-site history query hands out. Runs on the history thread through
// HistoryService::ScheduleDBTask, cancelable through the helper's tracker,
// and reads only: the origin's addresses, then their visits before
// `cutoff`. One list per origin, in the order given.
class SiteVisitsTask : public history::HistoryDBTask {
 public:
  using Callback = base::OnceCallback<void(std::vector<SiteVisits>)>;

  SiteVisitsTask(std::vector<url::Origin> origins,
                 base::Time cutoff,
                 Callback callback)
      : origins_(std::move(origins)),
        cutoff_(cutoff),
        callback_(std::move(callback)) {}
  SiteVisitsTask(const SiteVisitsTask&) = delete;
  SiteVisitsTask& operator=(const SiteVisitsTask&) = delete;
  ~SiteVisitsTask() override = default;

  bool RunOnDBThread(history::HistoryBackend* backend,
                     history::HistoryDatabase* db) override {
    for (const url::Origin& origin : origins_) {
      SiteVisits& out = sites_.emplace_back();
      if (!db) {
        continue;
      }
      history::URLRows rows;
      db->AutocompleteForPrefix(origin.GetURL().spec(), kMaxUrlsPerSite,
                                /*typed_only=*/false, &rows);
      for (const history::URLRow& row : rows) {
        if (!origin.IsSameOriginWith(row.url())) {
          continue;
        }
        history::VisitVector visits;
        if (!db->GetNon404VisitsForURL(row.id(), &visits)) {
          continue;
        }
        for (const history::VisitRow& visit : visits) {
          if (visit.visit_time >= cutoff_ || out.size() >= kMaxVisitsPerSite) {
            continue;
          }
          out.push_back({Micros(visit.visit_time),
                         Micros(visit.visit_time.LocalMidnight()),
                         static_cast<uint32_t>(visit.transition)});
        }
      }
    }
    return true;
  }

  void DoneRunOnMainThread() override {
    std::move(callback_).Run(std::move(sites_));
  }

 private:
  const std::vector<url::Origin> origins_;
  const base::Time cutoff_;
  Callback callback_;
  std::vector<SiteVisits> sites_;
};

// The person blocked JavaScript for this address: the card question is not
// asked there, not even in an isolated world.
bool JavaScriptBlocked(Profile* profile, const GURL& url) {
  HostContentSettingsMap* settings =
      HostContentSettingsMapFactory::GetForProfile(profile);
  return !settings ||
         settings->GetContentSetting(url, url,
                                     ContentSettingsType::JAVASCRIPT) ==
             CONTENT_SETTING_BLOCK;
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
  // Made after the page loaded (the chip asks late): ask what is there now.
  AskPageForCardFields();
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
  // The exact host the pop-up shows (or its www twin), never the whole
  // registrable domain: a mark on one tenant is not a mark on the others.
  const base::ListValue& marks =
      ProfileOf(web_contents())->GetPrefs()->GetList(
          boring::prefs::kPassportKnownSites);
  for (const url::Origin& origin :
       OriginsOf(web_contents()->GetLastCommittedURL())) {
    if (!origin.host().empty() &&
        std::ranges::contains(marks, base::Value(origin.host()))) {
      return true;
    }
  }
  return false;
}

void BoringPassportTabHelper::SetMarkedKnown(bool known) {
  const GURL url = web_contents()->GetLastCommittedURL();
  const std::string site = url::Origin::Create(url).host();
  if (site.empty()) {
    return;
  }
  // Only the chip and the Passport read this list. It never reaches the
  // scam list, the look-alike allow list or any blocking.
  ScopedListPrefUpdate update(ProfileOf(web_contents())->GetPrefs(),
                              boring::prefs::kPassportKnownSites);
  for (const url::Origin& origin : OriginsOf(url)) {
    update->EraseValue(base::Value(origin.host()));
  }
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
  in.days_before_today = same_page ? facts_.days_before_today : 0;
  in.lookalike = same_page && facts_.lookalike;
  in.pending = !same_page || facts_.pending > 0 ||
               scam->status() == boring::ScamService::Status::kLoading;
  // A list that failed to load says nothing about this site: Known site
  // waits for it as for a pending answer; New to you does not (S-D6).
  in.scam_list_failed =
      scam->status() == boring::ScamService::Status::kFailed;
  // A New to you this tab already settled on for this site (or its www
  // twin) stays while the answers for a newer page are pending (S-D4).
  for (const url::Origin& origin : OriginsOf(url)) {
    in.held_warning |= warned_origins_.contains(origin.Serialize());
  }
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
      CardFactFound();
      return;
    }
  }
}

void BoringPassportTabHelper::DidFinishLoad(
    content::RenderFrameHost* render_frame_host,
    const GURL& validated_url) {
  if (&render_frame_host->GetPage() == &web_contents()->GetPrimaryPage()) {
    AskFrameForCardFields(render_frame_host);
  }
}

bool BoringPassportTabHelper::AutofillParsesForms() const {
  // BrowserAutofillManager::ShouldParseForms() uses the same two settings.
  autofill::ContentAutofillClient* client =
      autofill::ContentAutofillClient::FromWebContents(web_contents());
  return client &&
         (client->IsAutofillEnabled() || client->IsPasswordManagerEnabled());
}

void BoringPassportTabHelper::AskPageForCardFields() {
  if (facts_.asks_card || AutofillParsesForms()) {
    return;
  }
  web_contents()->GetPrimaryPage().GetMainDocument().ForEachRenderFrameHost(
      [this](content::RenderFrameHost* frame) {
        AskFrameForCardFields(frame);
      });
}

void BoringPassportTabHelper::AskFrameForCardFields(
    content::RenderFrameHost* frame) {
  if (facts_.asks_card || AutofillParsesForms() || !frame->IsRenderFrameLive() ||
      !frame->GetLastCommittedURL().SchemeIsHTTPOrHTTPS()) {
    return;
  }
  // Where the person blocked JavaScript (for this frame's site or the
  // page's), the page is not asked at all, not even in an isolated world
  // (S-D7). The card row is then left out, as with autofill's own parse.
  Profile* profile = ProfileOf(web_contents());
  if (JavaScriptBlocked(profile, frame->GetLastCommittedURL()) ||
      JavaScriptBlocked(profile, web_contents()->GetLastCommittedURL())) {
    return;
  }
  // The answer comes from a renderer, so it is untrusted: it can only add
  // the cautionary row (sticky for this page), never take a warning away
  // or change the chip. Nothing of it is kept or logged but that one bit.
  frame->ExecuteJavaScriptInIsolatedWorld(
      kAsksCardScript,
      base::BindOnce(
          [](base::WeakPtr<BoringPassportTabHelper> self, int generation,
             base::Value result) {
            if (!self || generation != self->generation_ ||
                self->facts_.asks_card || !result.is_bool() ||
                !result.GetBool()) {
              return;
            }
            self->facts_.asks_card = true;
            self->CardFactFound();
          },
          weak_factory_.GetWeakPtr(), generation_),
      ISOLATED_WORLD_ID_CHROME_INTERNAL);
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
  // This tab shows the site from this entry's time on, if not earlier.
  const base::Time shown =
      facts_.cutoff.is_null() ? base::Time::Now() : facts_.cutoff;
  for (const url::Origin& origin : OriginsOf(url)) {
    auto [it, added] = first_seen_.try_emplace(origin.Serialize(), shown);
    if (!added && shown < it->second) {
      it->second = shown;
    }
  }
  facts_.first_shown = FirstShown(url);
  facts_.scam_listed = boring::ScamService::GetInstance()->IsListed(url);
  Profile* profile = ProfileOf(web_contents());
  const int generation = generation_;

  // History. In a private window this reads the normal profile's history,
  // which is what "you have visited" means; nothing is written.
  if (history::HistoryService* history = HistoryServiceFactory::GetForProfile(
          profile, ServiceAccessType::EXPLICIT_ACCESS)) {
    // Known site's days: earlier days with a visit the person started, or
    // one from before this tab first showed the site (ledger 58). Visits a
    // page made itself while it sat in this tab never count.
    ++facts_.pending;
    history->ScheduleDBTask(
        FROM_HERE,
        std::make_unique<SiteVisitsTask>(
            OriginsOf(url), facts_.cutoff,
            base::BindOnce(&BoringPassportTabHelper::OnKnownDays,
                           weak_factory_.GetWeakPtr(), generation)),
        &tracker_);
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
  NoteSettled();
}

base::Time BoringPassportTabHelper::FirstShown(const GURL& url) const {
  const std::vector<url::Origin> origins = OriginsOf(url);
  base::Time first = base::Time::Max();
  for (const url::Origin& origin : origins) {
    auto it = first_seen_.find(origin.Serialize());
    if (it != first_seen_.end()) {
      first = std::min(first, it->second);
    }
  }
  // The back list's entries keep their times across a session restore,
  // which this helper's memory does not.
  content::NavigationController& controller = web_contents()->GetController();
  for (int i = 0; i < controller.GetEntryCount(); ++i) {
    content::NavigationEntry* entry = controller.GetEntryAtIndex(i);
    if (!entry || entry->GetTimestamp().is_null()) {
      continue;
    }
    const GURL& entry_url = entry->GetURL();
    if (std::ranges::any_of(origins, [&](const url::Origin& origin) {
          return origin.IsSameOriginWith(entry_url);
        })) {
      first = std::min(first, entry->GetTimestamp());
    }
  }
  return first.is_max() ? base::Time::Now() : first;
}

void BoringPassportTabHelper::OnKnownDays(int generation,
                                          std::vector<SiteVisits> sites) {
  if (generation != generation_) {
    return;
  }
  const int64_t today = Micros(base::Time::Now().LocalMidnight());
  const int64_t first_shown = Micros(facts_.first_shown);
  int days = 0;
  // The most of either twin, never the sum: the same day on both is one day.
  for (const SiteVisits& visits : sites) {
    days = std::max(
        days, boring::passport::CountKnownDays(visits, today, first_shown));
  }
  facts_.days_before_today = days;
  Answered(generation);
}

void BoringPassportTabHelper::NoteSettled() {
  if (facts_.pending > 0 || !facts_.url.is_valid()) {
    return;
  }
  // The answer as the chip would give it with nothing pending, the field's
  // own words aside: only a settled New to you is held for later pages.
  boring::passport::ChipInputs settled;
  settled.eligible = true;
  settled.scam_listed = facts_.scam_listed;
  settled.marked_known = MarkedKnown();
  settled.days_before_today = facts_.days_before_today;
  settled.lookalike = facts_.lookalike;
  const std::string key = url::Origin::Create(facts_.url).Serialize();
  if (boring::passport::DecideChip(settled) ==
      boring::passport::Chip::kNewToYou) {
    warned_origins_.insert(key);
  } else {
    warned_origins_.erase(key);
  }
}

void BoringPassportTabHelper::CardFactFound() {
  Changed();
  // A Passport already open for this tab was built before the answer: it
  // gains the row now rather than at its next opening (S-D3).
  BoringPassportBubble::FactsChangedFor(web_contents());
}

void BoringPassportTabHelper::SetFirstSeenForTesting(const GURL& url,
                                                     base::Time time) {
  for (const url::Origin& origin : OriginsOf(url)) {
    first_seen_[origin.Serialize()] = time;
  }
  StartQueries();
  Changed();
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
  NoteSettled();
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
  out.Set("firstShownDaysAgo",
          facts_.first_shown.is_null()
              ? -1
              : static_cast<int>(
                    (base::Time::Now() - facts_.first_shown).InDays()));
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
