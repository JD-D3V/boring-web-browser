// Copyright 2026 boring. BSD style license.

#ifndef COMPONENTS_BORING_SEARCH_SEARCH_ENGINES_H_
#define COMPONENTS_BORING_SEARCH_SEARCH_ENGINES_H_

#include <string>
#include <vector>

namespace content {
class BrowserContext;
}

namespace boring {

// One search engine the browser actually has: a prepopulated one or one
// a person added. Nothing here is invented by us; every field comes
// from the browser's own TemplateURLService.
struct SearchEngine {
  SearchEngine();
  SearchEngine(const SearchEngine&);
  SearchEngine& operator=(const SearchEngine&);
  SearchEngine(SearchEngine&&) noexcept;
  SearchEngine& operator=(SearchEngine&&) noexcept;
  ~SearchEngine();

  // Stable across restarts: the engine's sync guid, or its keyword when
  // it has no guid. Never a position in a list, which changes whenever
  // an engine is added or removed.
  std::string id;
  std::string name;
  std::string keyword;
  // The search address template, with {searchTerms} where the words go.
  std::string url;
  // The browser's own default search provider, the one the address bar
  // uses.
  bool is_default = false;
  // Whether this engine is allowed to become the default. False when
  // policy fixes the default, or the engine cannot be one.
  bool can_be_default = false;
};

// These two are declared here, where our own code can use them, and
// defined in chrome/browser/boring/search_engines_bridge.cc, which is
// built as part of chrome/browser. The search engine list lives in
// TemplateURLService, which is only reachable through a factory in
// chrome/browser; components/boring cannot depend on chrome/browser,
// because chrome/browser already depends on us. Splitting the
// declaration from the definition keeps that one-way dependency and
// still resolves when chrome is linked. There is no global here, so no
// static initializer is added.

// Every engine the browser has, in the browser's own order. Empty if
// the service is not available yet, in which case ask again later
// rather than showing a made up list.
std::vector<SearchEngine> GetSearchEngines(content::BrowserContext* context);

// Makes `id` the browser's default search provider, so the address bar
// follows too. Returns false if the engine is gone, cannot be a default
// or the default is managed.
bool SetDefaultSearchEngine(content::BrowserContext* context,
                            const std::string& id);

}  // namespace boring

#endif  // COMPONENTS_BORING_SEARCH_SEARCH_ENGINES_H_
