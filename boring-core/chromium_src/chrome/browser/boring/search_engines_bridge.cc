// Copyright 2026 boring. BSD style license.

// The chrome/browser half of components/boring/search/search_engines.h.
// It is built as part of chrome/browser (see that target's sources in
// chrome/browser/BUILD.gn), so it may use TemplateURLServiceFactory,
// which components/boring may not: chrome/browser already depends on
// components/boring, and a dependency the other way would be a cycle.
// Nothing here runs before main; there is no global.

#include "components/boring/search/search_engines.h"

#include <string>
#include <vector>

#include "base/strings/utf_string_conversions.h"
#include "chrome/browser/profiles/profile.h"
#include "chrome/browser/search_engines/template_url_service_factory.h"
#include "components/search_engines/default_search_manager.h"
#include "components/search_engines/search_terms_data.h"
#include "components/search_engines/template_url.h"
#include "components/search_engines/template_url_data.h"
#include "components/search_engines/template_url_service.h"
#include "components/search_engines/template_url_starter_pack_data.h"
#include "content/public/browser/browser_context.h"
#include "url/gurl.h"

namespace boring {

namespace {

TemplateURLService* GetService(content::BrowserContext* context) {
  Profile* profile = Profile::FromBrowserContext(context);
  if (!profile) {
    return nullptr;
  }
  // Incognito and guest profiles are redirected to their original
  // profile by the factory, so a private window lists the same engines
  // as the window it came from.
  return TemplateURLServiceFactory::GetForProfile(profile);
}

// An engine someone can actually search with from a page of ours: a
// real search engine, still in use, with a place to put the words.
// ungoogled-chromium's "No Search" is left out too. Its address is
// http://{searchTerms}, so the words become the address: it is how
// settings turns search off, not an engine to search with.
// Extension-controlled entries, the @history / @bookmarks / @tabs
// starter pack keywords and site-search keywords that another engine
// already shadows are left out; none of them belongs in a list of
// engines to search with.
bool IsUsableSearchEngine(const TemplateURLService* service,
                          const TemplateURL* engine) {
  if (!engine || engine->type() != TemplateURL::NORMAL) {
    return false;
  }
  if (engine->starter_pack_id() !=
      template_url_starter_pack_data::StarterPackId::kNone) {
    return false;
  }
  if (engine->url().find("{searchTerms}") == std::string::npos) {
    return false;
  }
  const GURL example(engine->url_ref().ReplaceSearchTerms(
      TemplateURLRef::SearchTermsArgs(u"boring"),
      service->search_terms_data()));
  if (!example.is_valid() || !example.SchemeIsHTTPOrHTTPS() ||
      example.host() == "boring") {
    return false;
  }
  if (service->HiddenFromLists(engine)) {
    return false;
  }
  // The browser's own two lists: the engines it offers as defaults
  // (prepopulated, plus whatever policy set), and the ones a person
  // turned on or added themselves.
  return service->ShowInDefaultList(engine) ||
         service->ShowInActivesList(engine);
}

// Stable between restarts. Prepopulated and synced engines carry a
// guid; anything without one is identified by its keyword, which is
// unique among the engines the browser shows.
std::string IdFor(const TemplateURL* engine) {
  if (!engine->sync_guid().empty()) {
    return engine->sync_guid();
  }
  return base::UTF16ToUTF8(engine->keyword());
}

// Whether the browser will accept a new default from us at all. Policy
// can fix the default outright, and a recommended-by-policy default
// takes a path inside the service that insists the change came from a
// search engine choice screen, which this is not. Settings still offers
// that case its own way.
bool CanChangeDefault(const TemplateURLService* service) {
  if (service->is_default_search_managed()) {
    return false;
  }
  const DefaultSearchManager::Source source =
      service->default_search_provider_source();
  return source == DefaultSearchManager::FROM_USER ||
         source == DefaultSearchManager::FROM_FALLBACK;
}

TemplateURL* FindById(TemplateURLService* service, const std::string& id) {
  if (id.empty()) {
    return nullptr;
  }
  for (TemplateURL* engine : service->GetTemplateURLs()) {
    if (IsUsableSearchEngine(service, engine) && IdFor(engine) == id) {
      return engine;
    }
  }
  return nullptr;
}

}  // namespace

std::vector<SearchEngine> GetSearchEngines(content::BrowserContext* context) {
  std::vector<SearchEngine> engines;
  TemplateURLService* service = GetService(context);
  if (!service) {
    return engines;
  }
  // Loading is what fills the list from the profile. Asking for it here
  // is how the first new tab of a session ends up with the real list
  // rather than a short one; until it finishes, the caller gets what
  // there is and asks again.
  service->Load();

  const TemplateURL* default_engine = service->GetDefaultSearchProvider();
  const bool changeable = CanChangeDefault(service);
  for (TemplateURL* engine : service->GetTemplateURLs()) {
    if (!IsUsableSearchEngine(service, engine)) {
      continue;
    }
    SearchEngine out;
    out.id = IdFor(engine);
    out.name = base::UTF16ToUTF8(engine->short_name());
    out.keyword = base::UTF16ToUTF8(engine->keyword());
    out.url = engine->url();
    out.is_default = engine == default_engine;
    // The same answer SetDefaultSearchEngine would give, so the page
    // never offers an action that would be refused.
    out.can_be_default =
        changeable && !out.is_default && service->CanMakeDefault(engine);
    engines.push_back(std::move(out));
  }
  return engines;
}

bool SetDefaultSearchEngine(content::BrowserContext* context,
                            const std::string& id) {
  // A private window must not change what the ordinary profile searches
  // with: its prefs are thrown away, but this one is not, because the
  // factory redirects to the original profile.
  if (!context || context->IsOffTheRecord()) {
    return false;
  }
  TemplateURLService* service = GetService(context);
  if (!service || !CanChangeDefault(service)) {
    return false;
  }
  TemplateURL* engine = FindById(service, id);
  if (!engine || !service->CanMakeDefault(engine)) {
    return false;
  }
  // Left at the default ChoiceMadeLocation::kOther on purpose: this is
  // not a search engine choice screen, so it must not be recorded as
  // one.
  service->SetUserSelectedDefaultSearchProvider(engine);
  return true;
}

}  // namespace boring
