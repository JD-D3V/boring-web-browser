// Copyright 2026 boring. BSD style license.

#include "components/boring/passport/passport_words.h"

#include <algorithm>
#include <string>
#include <utility>

namespace boring::passport {

namespace {

// Digits only, so a plain widening copy is exact.
std::u16string Number(long long n) {
  const std::string digits = std::to_string(n);
  return std::u16string(digits.begin(), digits.end());
}

std::u16string CountOf(uint32_t n, const char16_t* one, const char16_t* many) {
  return Number(n) + u" " + (n == 1 ? one : many);
}

}  // namespace

Chip DecideChip(const ChipInputs& in) {
  if (!in.eligible) {
    return Chip::kNone;
  }
  if (in.blocked_page) {
    return Chip::kBlocked;
  }
  if (in.scam_listed) {
    return Chip::kScamList;
  }
  if (in.chromium_text) {
    return Chip::kNone;
  }
  // The neutral state (the browser's own icon) until every answer is in, so
  // "Known site" never shows on history alone before the look-alike answer.
  // A warning this tab already gave for this site stays while a newer page
  // of it is answered, so a page that loads itself again and again cannot
  // keep the warning away. Never Known, never over the person's mark.
  if (in.pending) {
    return in.held_warning && !in.marked_known ? Chip::kNewToYou
                                               : Chip::kNone;
  }
  if (in.marked_known || (in.days_before_today >= 2 && !in.lookalike)) {
    return in.scam_list_failed ? Chip::kNone : Chip::kKnown;
  }
  if (in.days_before_today == 1 && !in.lookalike) {
    return Chip::kNone;
  }
  return Chip::kNewToYou;
}

Chip DecideLayout(const ChipInputs& in) {
  ChipInputs without_text = in;
  without_text.chromium_text = false;
  // The pop-up lists facts, so it waits for them even where the chip holds
  // a warning it already gave.
  without_text.held_warning = false;
  const Chip layout = DecideChip(without_text);
  // "A site you know" over a connection that is not plainly secure would
  // soften the browser's own warning: page info opens instead.
  if (layout == Chip::kKnown && in.chromium_text) {
    return Chip::kNone;
  }
  return layout;
}

bool VisitIsVisible(uint32_t transition) {
  const uint32_t core = transition & kTransitionCoreMask;
  return (transition & kTransitionChainEnd) != 0 &&
         core != kTransitionAutoSubframe && core != kTransitionManualSubframe &&
         core != kTransitionKeywordGenerated;
}

bool PersonStartedVisit(uint32_t transition) {
  if (transition & (kTransitionClientRedirect | kTransitionForwardBack)) {
    return false;
  }
  switch (transition & kTransitionCoreMask) {
    case kTransitionTyped:
    case kTransitionAutoBookmark:
    case kTransitionKeyword:
    case kTransitionKeywordGenerated:
    case kTransitionGenerated:
    case kTransitionAutoToplevel:
      return true;
    default:
      return false;
  }
}

int CountKnownDays(const std::vector<SiteVisit>& visits,
                   int64_t today,
                   int64_t first_shown) {
  std::vector<int64_t> days;
  for (const SiteVisit& visit : visits) {
    if (visit.day >= today || !VisitIsVisible(visit.transition)) {
      continue;
    }
    if (visit.time < first_shown || PersonStartedVisit(visit.transition)) {
      days.push_back(visit.day);
    }
  }
  std::sort(days.begin(), days.end());
  return static_cast<int>(std::unique(days.begin(), days.end()) -
                          days.begin());
}

std::u16string ChipText(Chip chip) {
  switch (chip) {
    case Chip::kKnown:
      return u"Known site";
    case Chip::kNewToYou:
      return u"New to you";
    case Chip::kBlocked:
      return u"Blocked";
    case Chip::kScamList:
      return u"Scam list";
    case Chip::kNone:
      break;
  }
  return std::u16string();
}

std::u16string Verdict(Chip layout) {
  switch (layout) {
    case Chip::kKnown:
      return u"A site you know";
    case Chip::kNewToYou:
      return u"New to you. Take a moment.";
    case Chip::kScamList:
      return u"This site is on the scam list.";
    case Chip::kBlocked:
    case Chip::kNone:
      break;
  }
  return std::u16string();
}

std::vector<Fact> FactsFor(Chip layout, const FactInputs& in) {
  std::vector<Fact> facts;
  switch (layout) {
    case Chip::kKnown:
      // A look-alike the person marked as known keeps its true facts.
      facts.push_back(Fact::kVisits);
      if (in.lookalike) {
        facts.push_back(Fact::kTwin);
      }
      facts.push_back(Fact::kConnection);
      if (in.saved_password) {
        facts.push_back(Fact::kPassword);
      }
      break;
    case Chip::kNewToYou:
    case Chip::kScamList:
      if (layout == Chip::kScamList) {
        facts.push_back(Fact::kScamList);
      }
      facts.push_back(Fact::kVisits);
      if (in.lookalike) {
        facts.push_back(Fact::kTwin);
      }
      // A known shop asking for a card is normal; here it is a warning.
      if (in.asks_card) {
        facts.push_back(Fact::kCard);
      }
      // A scam site has a private connection too, so the positive line
      // would read as reassurance. Only the warning is said.
      if (!in.connection_private) {
        facts.push_back(Fact::kConnection);
      }
      if (layout == Chip::kNewToYou && in.saved_password) {
        facts.push_back(Fact::kPassword);
      }
      break;
    case Chip::kBlocked:
    case Chip::kNone:
      break;
  }
  return facts;
}

std::u16string VisitsFact(int visits_before,
                          int total,
                          int first_visit_year,
                          bool first_visit_today,
                          int this_year,
                          const std::u16string& month_name) {
  if (visits_before <= 0) {
    return u"This is the first time you have visited this site.";
  }
  // This page counts too, so there are always two or more here.
  const int n = std::max({total, visits_before + 1, 2});
  std::u16string text = u"You have visited this site " + Number(n) + u" times ";
  if (first_visit_today) {
    return text + u"today.";
  }
  text += u"since " + month_name;
  if (first_visit_year < this_year) {
    text += u" " + Number(first_visit_year);
  }
  return text + u".";
}

std::u16string TwinFact(const std::u16string& domain, bool used_site) {
  return u"It looks like " + domain +
         (used_site ? u", a site you use, but it is not the same."
                    : u", but it is not the same.");
}

std::u16string CardFact() {
  return u"This page asks for card details.";
}

std::u16string ScamListFact() {
  return u"This site is on the scam list.";
}

std::u16string ConnectionFact(bool connection_private) {
  return connection_private ? u"The connection is private."
                            : u"The connection is not private.";
}

std::u16string PasswordFact() {
  return u"You have a saved password here.";
}

std::u16string FooterText(uint32_t ads,
                          uint32_t trackers,
                          uint32_t cookie_banners,
                          uint32_t scripts,
                          uint32_t popups) {
  const std::pair<uint32_t, std::pair<const char16_t*, const char16_t*>>
      kinds[] = {{ads, {u"ad", u"ads"}},
                 {trackers, {u"tracker", u"trackers"}},
                 {cookie_banners, {u"cookie banner", u"cookie banners"}},
                 {scripts, {u"script", u"scripts"}},
                 {popups, {u"pop-up", u"pop-ups"}}};
  std::vector<std::u16string> parts;
  for (const auto& [n, words] : kinds) {
    if (n) {
      parts.push_back(CountOf(n, words.first, words.second));
    }
  }
  if (parts.empty()) {
    return u"Nothing blocked on this page.";
  }
  std::u16string text = u"Blocked on this page: ";
  for (size_t i = 0; i < parts.size(); ++i) {
    if (i > 0) {
      text += (i + 1 == parts.size()) ? u" and " : u", ";
    }
    text += parts[i];
  }
  return text + u".";
}

std::vector<std::u16string> ButtonsFor(Chip layout) {
  switch (layout) {
    case Chip::kKnown:
      return {kSiteSettings, kForgetThisSite};
    case Chip::kNewToYou:
      return {kLeaveThisSite, kIKnowThisSite};
    case Chip::kScamList:
      // Not "I know this site": the mark never argues with the list.
      return {kLeaveThisSite};
    case Chip::kBlocked:
    case Chip::kNone:
      break;
  }
  return {};
}

}  // namespace boring::passport
