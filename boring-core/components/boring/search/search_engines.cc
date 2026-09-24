// Copyright 2026 boring. BSD style license.

#include "components/boring/search/search_engines.h"

namespace boring {

// Out of line so every caller shares one copy, and so this target has
// an object file of its own. GetSearchEngines and SetDefaultSearchEngine
// are deliberately not defined here, see the header.
SearchEngine::SearchEngine() = default;
SearchEngine::SearchEngine(const SearchEngine&) = default;
SearchEngine& SearchEngine::operator=(const SearchEngine&) = default;
SearchEngine::SearchEngine(SearchEngine&&) noexcept = default;
SearchEngine& SearchEngine::operator=(SearchEngine&&) noexcept = default;
SearchEngine::~SearchEngine() = default;

}  // namespace boring
