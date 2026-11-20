// Copyright 2026 boring. BSD style license.

#include "chrome/browser/autocomplete/boring_bar_provider.h"

#include <string_view>

#include "base/i18n/case_conversion.h"
#include "base/memory/scoped_refptr.h"
#include "base/strings/string_split.h"
#include "base/strings/string_util.h"
#include "base/strings/utf_string_conversions.h"
#include "chrome/browser/profiles/profile.h"
#include "chrome/browser/themes/theme_service.h"
#include "chrome/browser/themes/theme_service_factory.h"
#include "components/omnibox/browser/actions/tab_switch_action.h"
#include "components/omnibox/browser/autocomplete_input.h"
#include "components/omnibox/browser/autocomplete_match.h"
#include "components/omnibox/browser/autocomplete_match_classification.h"
#include "components/omnibox/browser/autocomplete_provider_client.h"
#include "components/omnibox/browser/tab_matcher.h"
#include "components/prefs/pref_service.h"
#include "third_party/metrics_proto/omnibox_event.pb.h"
#include "third_party/omnibox_proto/groups.pb.h"
#include "ui/native_theme/native_theme.h"
#include "url/gurl.h"

namespace {

// A Do row. `id` is what boring_bar_run.cc runs; `glyph` names the row's
// icon (boring_bar_<glyph>.svg beside the results page's other icons).
struct DoRow {
  const char* id;
  const char16_t* title;
  const char16_t* keywords;
  const char* glyph;
  // Only dark and light may become the row Enter takes (bar.md, Q2).
  bool may_be_default;
};

// Every row runs a command the main menu already has (bar.md, Q1). The
// dark and light rows are filled in at match time: only the one that is
// not the current mode is offered.
constexpr DoRow kDoRows[] = {
    {"newtab", u"New tab", u"new tab", "plus", false},
    {"newwindow", u"New window", u"new window", "win", false},
    {"incognito", u"New Incognito window", u"incognito private", "priv",
     false},
    {"history", u"Show history", u"history", "clock", false},
    {"downloads", u"Show downloads", u"downloads", "down", false},
    {"print", u"Print this page", u"print", "print", false},
    {"find", u"Find on this page", u"find", "find", false},
    {"zoomin", u"Zoom in", u"zoom bigger", "zoom", false},
    {"zoomout", u"Zoom out", u"zoom smaller", "zoom", false},
    {"zoomreset", u"Reset zoom", u"zoom", "zoom", false},
    // These two open a page or a dialog that asks first, and never take
    // Enter on their own.
    {"delete", u"Delete browsing data", u"delete clear data cookies", "trash",
     false},
    {"forget", u"Forget this session", u"forget session", "erase", false},
};

constexpr DoRow kDarkRow = {"dark", u"Turn on dark mode",
                            u"dark light mode night theme", "moon", true};
constexpr DoRow kLightRow = {"light", u"Turn on light mode",
                             u"dark light mode night theme", "moon", true};

// Settings pages: screen C10's sections and its Appearance rows. The paths
// are checked against the Settings routes by tools/tests/test_bar_tables.py.
struct SettingsRow {
  const char16_t* title;
  const char16_t* keywords;
  const char* url;
};

constexpr SettingsRow kSettingsRows[] = {
    {u"Appearance: light or dark", u"appearance dark light mode theme",
     "chrome://settings/appearance"},
    {u"Appearance: look", u"look colour color soft slate dusk",
     "chrome://settings/appearance"},
    {u"Appearance: tabs on top or side", u"tabs side vertical",
     "chrome://settings/appearance"},
    {u"Appearance: bookmarks bar", u"bookmarks bar",
     "chrome://settings/appearance"},
    {u"Appearance: toolbar buttons", u"toolbar buttons",
     "chrome://settings/appearance"},
    {u"Protection", u"protection blocking ads scam trackers",
     "chrome://settings/protection"},
    {u"Search engine", u"search engine duckduckgo",
     "chrome://settings/search"},
    {u"Privacy", u"privacy cookies permissions", "chrome://settings/privacy"},
    {u"Passwords", u"passwords", "chrome://password-manager"},
    {u"Downloads", u"downloads folder", "chrome://settings/downloads"},
    {u"Languages", u"languages spelling", "chrome://settings/languages"},
    {u"About Boring Browser", u"about version update",
     "chrome://settings/help"},
};

constexpr int kDoDefaultRelevance = 1350;
constexpr int kDoRelevance = 700;
constexpr int kOpenTabRelevance = 800;
constexpr int kSettingsRelevance = 650;
constexpr size_t kMaxOpenTabRows = 3;
constexpr size_t kMinInputLength = 2;
constexpr size_t kMinDefaultKeywordLength = 3;

std::vector<std::u16string> Words(std::u16string_view text) {
  return base::SplitString(base::i18n::ToLower(text), u" \t.,:/-_",
                           base::TRIM_WHITESPACE, base::SPLIT_WANT_NONEMPTY);
}

// True when every typed word starts one of the row's words. The same rule
// for every kind of row, so what shows up is easy to predict.
bool Matches(const std::vector<std::u16string>& typed,
             const std::vector<std::u16string>& row) {
  for (const std::u16string& word : typed) {
    bool found = false;
    for (const std::u16string& candidate : row) {
      if (candidate.starts_with(word)) {
        found = true;
        break;
      }
    }
    if (!found) {
      return false;
    }
  }
  return true;
}

// True when a typed word is a whole keyword of three letters or more.
bool TypesWholeKeyword(const std::vector<std::u16string>& typed,
                       const std::vector<std::u16string>& keywords) {
  for (const std::u16string& word : typed) {
    if (word.size() >= kMinDefaultKeywordLength &&
        std::ranges::find(keywords, word) != keywords.end()) {
      return true;
    }
  }
  return false;
}

std::vector<std::u16string> RowWords(const char16_t* title,
                                     const char16_t* keywords) {
  std::vector<std::u16string> words = Words(title);
  for (std::u16string& word : Words(keywords)) {
    words.push_back(std::move(word));
  }
  return words;
}

// Plain text, no highlighting: the classifications only say "no style".
void SetPlainText(AutocompleteMatch& match,
                  std::u16string contents,
                  std::u16string description) {
  match.contents = std::move(contents);
  match.contents_class = {ACMatchClassification(0, ACMatchClassification::NONE)};
  match.description = std::move(description);
  match.description_class = {
      ACMatchClassification(0, ACMatchClassification::NONE)};
}

bool IsDarkNow(Profile* profile) {
  const ThemeService* themes = ThemeServiceFactory::GetForProfile(profile);
  const ThemeService::BrowserColorScheme scheme =
      themes ? themes->GetBrowserColorScheme()
             : ThemeService::BrowserColorScheme::kSystem;
  if (scheme != ThemeService::BrowserColorScheme::kSystem) {
    return scheme == ThemeService::BrowserColorScheme::kDark;
  }
  return ui::NativeTheme::GetInstanceForNativeUi()->preferred_color_scheme() ==
         ui::NativeTheme::PreferredColorScheme::kDark;
}

// The Look pref (components/boring/core/boring_prefs.h kAppearanceLook).
constexpr char kLookPref[] = "boring.appearance.look";

bool IsDusk(Profile* profile) {
  const PrefService* prefs = profile->GetPrefs();
  return prefs->FindPreference(kLookPref) &&
         prefs->GetString(kLookPref) == "dusk";
}

}  // namespace

BoringBarProvider::BoringBarProvider(AutocompleteProviderClient* client,
                                     Profile* profile)
    : AutocompleteProvider(AutocompleteProvider::Type::kBoringBar),
      client_(client),
      profile_(profile) {}

BoringBarProvider::~BoringBarProvider() = default;

void BoringBarProvider::Start(const AutocompleteInput& input,
                              bool minimal_changes) {
  matches_.clear();
  done_ = true;
  // Typed text only: not on focus, not in a keyword mode, and not for the
  // classifier (paste and go, drops), which asks for synchronous results
  // only and must keep treating text as a search or an address.
  if (input.IsZeroSuggest() || input.in_keyword_mode() ||
      input.omit_asynchronous_matches()) {
    return;
  }
  // The Bar only: the New Tab page's own search box cannot run a Do row.
  if (input.current_page_classification() ==
      metrics::OmniboxEventProto::NTP_REALBOX) {
    return;
  }
  // Typing chrome:// or file:// addresses stays the address bar's own.
  if (input.type() == metrics::OmniboxInputType::URL &&
      input.parts().scheme.is_nonempty() && input.scheme() != u"http" &&
      input.scheme() != u"https") {
    return;
  }
  const std::vector<std::u16string> words = Words(input.text());
  if (base::TrimWhitespace(input.text(), base::TRIM_ALL).size() <
          kMinInputLength ||
      words.empty()) {
    return;
  }
  AddDoRows(words);
  AddOpenTabRows(input, words);
  AddSettingsRows(words);
}

void BoringBarProvider::AddDoRows(const std::vector<std::u16string>& words) {
  auto add = [&](const DoRow& row) {
    const std::vector<std::u16string> keywords = Words(row.keywords);
    if (!Matches(words, RowWords(row.title, row.keywords))) {
      return;
    }
    const bool is_default =
        row.may_be_default && TypesWholeKeyword(words, keywords);
    // Not kPedal: a pedal row must carry a takeover action, and this row is
    // run by boring_bar_run.cc instead.
    AutocompleteMatch match(this,
                            is_default ? kDoDefaultRelevance : kDoRelevance,
                            /*deletable=*/false,
                            omnibox::AutocompleteMatchType::kNavsuggest);
    // Never opened: boring_bar_run.cc runs the row by its id instead. The
    // address only keeps rows apart when results are deduplicated.
    match.destination_url =
        GURL(std::string("chrome://boring-bar/do/") + row.id);
    match.fill_into_edit = row.title;
    match.allowed_to_be_default_match = is_default;
    match.suggestion_group_id = omnibox::GROUP_BORING_DO;
    // The popup draws "Enter" beside the selected Do row itself.
    SetPlainText(match, row.title, std::u16string());
    match.RecordAdditionalInfo(kDoKey, row.id);
    match.RecordAdditionalInfo(kIconKey, row.glyph);
    matches_.push_back(std::move(match));
  };
  // Dusk is always dark, so neither row would change anything there.
  if (!IsDusk(profile_)) {
    add(IsDarkNow(profile_) ? kLightRow : kDarkRow);
  }
  for (const DoRow& row : kDoRows) {
    add(row);
  }
}

void BoringBarProvider::AddSettingsRows(
    const std::vector<std::u16string>& words) {
  for (const SettingsRow& row : kSettingsRows) {
    if (!Matches(words, RowWords(row.title, row.keywords))) {
      continue;
    }
    AutocompleteMatch match(this, kSettingsRelevance, /*deletable=*/false,
                            omnibox::AutocompleteMatchType::kNavsuggest);
    match.destination_url = GURL(row.url);
    match.fill_into_edit = base::UTF8ToUTF16(row.url);
    match.allowed_to_be_default_match = false;
    match.suggestion_group_id = omnibox::GROUP_BORING_SETTINGS;
    SetPlainText(match, row.title, u"Open");
    match.RecordAdditionalInfo(kIconKey, "sliders");
    matches_.push_back(std::move(match));
  }
}

void BoringBarProvider::AddOpenTabRows(
    const AutocompleteInput& input,
    const std::vector<std::u16string>& words) {
  size_t added = 0;
  // The active tab is left out, and an Incognito window sees only its own
  // tabs: TabMatcher does both.
  for (const TabMatcher::TabWrapper& tab :
       client_->GetTabMatcher().GetOpenTabs(&input)) {
    if (added == kMaxOpenTabRows) {
      break;
    }
    if (!tab.url.is_valid() || !tab.url.SchemeIsHTTPOrHTTPS()) {
      continue;
    }
    // The title is the page's own text. It is only ever shown as plain
    // text under "Open tabs" and can never run anything: the row's only
    // action is switching to that tab.
    std::vector<std::u16string> row_words = Words(tab.title);
    for (std::u16string& part : Words(base::UTF8ToUTF16(tab.url.host()))) {
      if (part != u"www") {
        row_words.push_back(std::move(part));
      }
    }
    if (!Matches(words, row_words)) {
      continue;
    }
    AutocompleteMatch match(this, kOpenTabRelevance, /*deletable=*/false,
                            omnibox::AutocompleteMatchType::kOpenTab);
    match.destination_url = tab.url;
    match.fill_into_edit = base::UTF8ToUTF16(tab.url.spec());
    match.allowed_to_be_default_match = false;
    match.suggestion_group_id = omnibox::GROUP_BORING_OPEN_TABS;
    SetPlainText(match,
                 tab.title.empty() ? base::UTF8ToUTF16(tab.url.host())
                                   : tab.title,
                 u"Switch to tab");
    // Already marked, so AutocompleteResult adds no second switch button;
    // Enter on the row switches to the tab.
    match.has_tab_match = true;
    match.takeover_action = base::MakeRefCounted<TabSwitchAction>(tab.url);
    match.RecordAdditionalInfo(kIconKey, "tab");
    matches_.push_back(std::move(match));
    ++added;
  }
}
