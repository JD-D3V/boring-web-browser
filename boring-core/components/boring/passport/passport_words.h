// Copyright 2026 boring. BSD style license.

#ifndef COMPONENTS_BORING_PASSPORT_PASSPORT_WORDS_H_
#define COMPONENTS_BORING_PASSPORT_PASSPORT_WORDS_H_

// The Passport's decisions and words: which chip the address field shows,
// which facts the pop-up lists and how each is said. Plain standard C++
// with no Chromium headers, so tools/tests/test_passport_words.py can build
// this file alone and check every case. The browser side gathers the facts
// (boring_passport_tab_helper.cc) and draws them (boring_passport_bubble.cc).

#include <cstdint>
#include <string>
#include <vector>

namespace boring::passport {

// Test commands answer only when the browser was started with this switch.
inline constexpr char kPassportTestSwitch[] = "boring-passport-test";

enum class Chip { kNone, kKnown, kNewToYou, kBlocked, kScamList };

struct ChipInputs {
  // An http or https page with a public name (not localhost, an IP address
  // or an intranet name), and the address field is not being edited.
  bool eligible = false;
  // The tab shows our scam or look-alike warning.
  bool blocked_page = false;
  // The page's host is on the scam list (shown after "Continue anyway").
  bool scam_listed = false;
  // The field already says "Not secure" or "Dangerous" in its own words, or
  // the security level is anything but SECURE (a mixed form, mixed content,
  // a certificate or policy state): Chromium's own indicator stays.
  bool chromium_text = false;
  // An answer Known site rests on (history, site engagement, the scam list)
  // is still on its way: neither soft chip shows until all are in.
  bool pending = false;
  // The scam list failed to load, so it cannot vouch for anything: Known
  // site gives way to no chip (as while pending). New to you still shows.
  bool scam_list_failed = false;
  // The person pressed "I know this site" for this site.
  bool marked_known = false;
  // On how many different earlier days (local calendar days, before today)
  // history has a visit to this site. One day is too little to call it
  // known and too much to call it new: no chip.
  int days_before_today = 0;
  // The name looks like a site the person uses, or a well known one.
  bool lookalike = false;
  // This tab already showed "New to you" for this site, and the answers for
  // a newer page of the same site are still on their way: the warning
  // stays meanwhile. Known site and Blocked are never held over this way.
  bool held_warning = false;
};

// The chip to draw, first match wins: nothing, Blocked, Scam list, nothing
// where the field has words of its own, while answers are pending a held
// New to you (unless marked) or else nothing, Known site (the mark, or
// two or more earlier days that count, CountKnownDays; nothing instead
// while the scam list has failed), nothing for exactly one earlier day,
// New to you. The mark beats the look-alike rule, never Blocked or the scam
// list.
Chip DecideChip(const ChipInputs& in);

// The Passport layout pressing the field's icon opens. The same as the
// chip, except where the field has words of its own: the Passport still
// opens there, but never as Known site (a known site on a connection the
// browser does not call secure gets the page info bubble). kNone and
// kBlocked open the page info bubble as before.
Chip DecideLayout(const ChipInputs& in);

// Known site's days. Page transitions as ui::PageTransition numbers
// (ui/base/page_transition_types.h); this file has no Chromium headers.
inline constexpr uint32_t kTransitionCoreMask = 0xFF;
inline constexpr uint32_t kTransitionTyped = 1;
inline constexpr uint32_t kTransitionAutoBookmark = 2;
inline constexpr uint32_t kTransitionAutoSubframe = 3;
inline constexpr uint32_t kTransitionManualSubframe = 4;
inline constexpr uint32_t kTransitionGenerated = 5;
inline constexpr uint32_t kTransitionAutoToplevel = 6;
inline constexpr uint32_t kTransitionKeyword = 9;
inline constexpr uint32_t kTransitionKeywordGenerated = 10;
inline constexpr uint32_t kTransitionForwardBack = 0x01000000;
inline constexpr uint32_t kTransitionChainEnd = 0x20000000;
inline constexpr uint32_t kTransitionClientRedirect = 0x40000000;

// One visit history holds for the site. Times are on one clock of the
// caller's (microseconds); `day` is the visit's local midnight on it.
struct SiteVisit {
  int64_t time = 0;
  int64_t day = 0;
  uint32_t transition = 0;
};

// A visit history shows (the end of a redirect chain, in the main frame,
// not a search results page the keyword made): the visits a day is made of.
bool VisitIsVisible(uint32_t transition);

// A visit the person plainly started: typed, a bookmark or a new tab page
// tile, a keyword or a generated address, or opened from outside. Never a
// link or anything else a page can start, never a client redirect, and
// never back or forward (a page can go back to a typed entry itself).
bool PersonStartedVisit(uint32_t transition);

// The earlier days that count toward Known site: different local days
// before `today` with a visible visit that is either one the person
// started, or made before `first_shown`, when this tab first showed the
// site. A page that sits in a tab and loads itself again after midnight, or
// bounces through another site and back, never vouches for itself.
int CountKnownDays(const std::vector<SiteVisit>& visits,
                   int64_t today,
                   int64_t first_shown);

std::u16string ChipText(Chip chip);
std::u16string Verdict(Chip layout);

enum class Fact { kScamList, kVisits, kTwin, kCard, kConnection, kPassword };

struct FactInputs {
  bool lookalike = false;
  bool asks_card = false;
  bool connection_private = false;
  bool saved_password = false;
};

// The rows a layout lists, in order. Rows that do not apply are left out.
// Absence is never said: no "does not ask for card details".
std::vector<Fact> FactsFor(Chip layout, const FactInputs& in);

// The first-visit or visit-count row. `visits_before` counts this site's
// visits before this page; `total` is the count history holds now.
// `month_name` is the first visit's month in the browser's language.
std::u16string VisitsFact(int visits_before,
                          int total,
                          int first_visit_year,
                          bool first_visit_today,
                          int this_year,
                          const std::u16string& month_name);

// `used_site`: the match is a site the person uses (site engagement), not
// a well known brand.
std::u16string TwinFact(const std::u16string& domain, bool used_site);
std::u16string CardFact();
std::u16string ScamListFact();
std::u16string ConnectionFact(bool connection_private);
std::u16string PasswordFact();

// "Blocked on this page: 3 trackers and 1 pop-up." or, all zero,
// "Nothing blocked on this page."
std::u16string FooterText(uint32_t ads,
                          uint32_t trackers,
                          uint32_t cookie_banners,
                          uint32_t scripts,
                          uint32_t popups);

// The buttons, left to right, before any question is asked.
std::vector<std::u16string> ButtonsFor(Chip layout);

inline constexpr char16_t kSiteSettings[] = u"Site settings";
inline constexpr char16_t kForgetThisSite[] = u"Forget this site";
inline constexpr char16_t kLeaveThisSite[] = u"Leave this site";
inline constexpr char16_t kIKnowThisSite[] = u"I know this site";
inline constexpr char16_t kForgetQuestion[] =
    u"Forget this site? You will be signed out of it.";
inline constexpr char16_t kForget[] = u"Forget";
inline constexpr char16_t kCancel[] = u"Cancel";
inline constexpr char16_t kPassportName[] = u"Site passport";

}  // namespace boring::passport

#endif  // COMPONENTS_BORING_PASSPORT_PASSPORT_WORDS_H_
