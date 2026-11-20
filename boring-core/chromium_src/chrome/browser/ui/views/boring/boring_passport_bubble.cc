// Copyright 2026 boring. BSD style license.

#include "chrome/browser/ui/views/boring/boring_passport_bubble.h"

#include <algorithm>
#include <utility>

#include "base/command_line.h"
#include "base/functional/bind.h"
#include "base/memory/ptr_util.h"
#include "base/no_destructor.h"
#include "base/strings/utf_string_conversions.h"
#include "base/task/sequenced_task_runner.h"
#include "chrome/app/vector_icons/vector_icons.h"
#include "chrome/browser/history/history_service_factory.h"
#include "chrome/browser/lookalikes/safety_tip_ui_helper.h"
#include "chrome/browser/profiles/profile.h"
#include "chrome/browser/ui/browser_window/public/browser_window_interface.h"
#include "chrome/browser/ui/browser_window/public/global_browser_collection.h"
#include "chrome/browser/ui/color/chrome_color_id.h"
#include "chrome/browser/ui/views/boring/boring_forget.h"
#include "chrome/browser/ui/views/boring/boring_passport_chip.h"
#include "chrome/browser/ui/views/boring/boring_passport_tab_helper.h"
#include "chrome/browser/ui/views/frame/browser_view.h"
#include "chrome/browser/ui/views/location_bar/location_bar_view.h"
#include "chrome/browser/ui/views/location_bar/location_icon_view.h"
#include "chrome/browser/ui/views/page_info/page_info_bubble_view_base.h"
#include "components/blocked_content/popup_blocker_tab_helper.h"
#include "components/boring/adblock/blocked_counts.h"
#include "components/boring/core/boring_prefs.h"
#include "components/boring/passport/passport_test.h"
#include "components/history/core/browser/history_service.h"
#include "components/keyed_service/core/service_access_type.h"
#include "components/omnibox/browser/location_bar_model.h"
#include "components/prefs/pref_service.h"
#include "components/security_state/core/security_state.h"
#include "components/site_engagement/content/site_engagement_service.h"
#include "components/url_formatter/elide_url.h"
#include "components/url_formatter/url_formatter.h"
#include "content/public/browser/navigation_controller.h"
#include "content/public/browser/web_contents.h"
#include "ui/base/models/image_model.h"
#include "ui/base/mojom/dialog_button.mojom.h"
#include "ui/base/page_transition_types.h"
#include "ui/base/ui_base_types.h"
#include "ui/base/window_open_disposition.h"
#include "ui/color/color_provider.h"
#include "ui/events/event.h"
#include "ui/events/keycodes/keyboard_codes.h"
#include "ui/gfx/font.h"
#include "ui/gfx/font_list.h"
#include "ui/gfx/text_constants.h"
#include "ui/views/accessibility/view_accessibility.h"
#include "ui/views/background.h"
#include "ui/views/border.h"
#include "ui/views/bubble/bubble_border.h"
#include "ui/views/bubble/bubble_dialog_delegate_view.h"
#include "ui/views/controls/button/md_text_button.h"
#include "ui/views/controls/image_view.h"
#include "ui/views/controls/label.h"
#include "ui/views/layout/box_layout.h"
#include "ui/views/view.h"
#include "url/gurl.h"

namespace {

using boring::passport::Chip;
using boring::passport::Fact;

constexpr int kWidth = 384;
constexpr int kIconSize = 16;

std::unique_ptr<BoringPassportBubble>& Current() {
  static base::NoDestructor<std::unique_ptr<BoringPassportBubble>> bubble;
  return *bubble;
}

gfx::FontList Font(int size, gfx::Font::Weight weight) {
  const gfx::FontList& base = views::Label::GetDefaultFontList();
  return base.DeriveWithSizeDelta(size - base.GetFontSize())
      .DeriveWithWeight(weight);
}

std::unique_ptr<views::Label> MakeLabel(const std::u16string& text,
                                        int size,
                                        gfx::Font::Weight weight,
                                        ui::ColorId color) {
  auto label = std::make_unique<views::Label>(text);
  label->SetFontList(Font(size, weight));
  label->SetEnabledColor(color);
  label->SetHorizontalAlignment(gfx::ALIGN_LEFT);
  return label;
}

const gfx::VectorIcon& IconFor(Fact fact) {
  switch (fact) {
    case Fact::kScamList:
      return kBoringProtectionIcon;
    case Fact::kVisits:
      return kBoringEyeIcon;
    case Fact::kTwin:
      return kBoringTwinIcon;
    case Fact::kCard:
      return kBoringCardIcon;
    case Fact::kConnection:
      return kBoringLockIcon;
    case Fact::kPassword:
      return kBoringKeyIcon;
  }
  return kBoringEyeIcon;
}

const char* IconName(Fact fact) {
  switch (fact) {
    case Fact::kScamList:
      return "shieldPlain";
    case Fact::kVisits:
      return "eye";
    case Fact::kTwin:
      return "twin";
    case Fact::kCard:
      return "card";
    case Fact::kConnection:
      return "lock";
    case Fact::kPassword:
      return "key";
  }
  return "";
}

// The verdict's tone, and its name for the test hook.
std::pair<ui::ColorId, const char*> VerdictTone(Chip layout) {
  if (layout == Chip::kKnown) {
    return {kColorBoringOk, "ok"};
  }
  if (layout == Chip::kNewToYou) {
    return {kColorBoringPassportWarnText, "warn"};
  }
  return {kColorBoringPassportBad, "bad"};
}

// Our words are English (inline literals, like the rest of the Passport),
// so the month is too.
std::u16string MonthName(int month) {
  static constexpr const char16_t* kMonths[] = {
      u"January", u"February", u"March",     u"April",
      u"May",     u"June",     u"July",      u"August",
      u"September", u"October", u"November", u"December"};
  return month >= 1 && month <= 12 ? kMonths[month - 1] : u"";
}

bool ConnectionPrivate(content::WebContents* contents) {
  BrowserWindowInterface* window =
      GlobalBrowserCollection::GetInstance()->FindBrowserWithTab(contents);
  BrowserView* view =
      window ? BrowserView::GetBrowserViewForBrowser(window) : nullptr;
  LocationBarView* bar = view ? view->GetLocationBarView() : nullptr;
  if (!bar || !bar->GetLocationBarModel()) {
    return false;
  }
  const security_state::SecurityLevel level =
      bar->GetLocationBarModel()->GetSecurityLevel();
  return level == security_state::SECURE;
}

}  // namespace

BoringPassportBubble::BoringPassportBubble(LocationIconView* icon,
                                           content::WebContents* contents,
                                           Chip layout)
    : contents_(contents->GetWeakPtr()), layout_(layout) {
  icon_.SetView(icon);
  url_ = contents->GetLastCommittedURL();
  verdict_ = boring::passport::Verdict(layout);
  // The committed origin's host, the way page info and the omnibox show it
  // (IDN spoof checks included). Never the page's title or any page text.
  host_ = url_formatter::FormatUrlForSecurityDisplay(
      url_, url_formatter::SchemeDisplay::OMIT_HTTP_AND_HTTPS);

  BoringPassportTabHelper* helper =
      BoringPassportTabHelper::GetOrCreate(contents);
  const BoringPassportTabHelper::Facts& facts = helper->facts();
  const bool same_page = helper->FactsAreFor(url_);
  boring::passport::FactInputs in;
  in.lookalike = same_page && facts.lookalike;
  in.asks_card = same_page && facts.asks_card;
  in.connection_private = ConnectionPrivate(contents);
  in.saved_password = same_page && facts.saved_password;
  for (Fact fact : boring::passport::FactsFor(layout, in)) {
    Row row{std::u16string(), IconName(fact), "ink2"};
    switch (fact) {
      case Fact::kScamList:
        row.text = boring::passport::ScamListFact();
        row.color = "bad";
        break;
      case Fact::kVisits: {
        base::Time::Exploded first = {};
        base::Time::Exploded now = {};
        base::Time::Now().LocalExplode(&now);
        if (!facts.first_visit.is_null()) {
          facts.first_visit.LocalExplode(&first);
        }
        const bool today = facts.first_visit.is_null() ||
                           facts.first_visit >= base::Time::Now().LocalMidnight();
        row.text = boring::passport::VisitsFact(
            same_page ? facts.visits_before : 0,
            same_page ? facts.visits_total : 0, first.year, today, now.year,
            facts.first_visit.is_null()
                ? std::u16string()
                : MonthName(first.month));
        break;
      }
      case Fact::kTwin:
        // From the person's own site engagement or our brand list, shown
        // with the same IDN rules as the omnibox.
        row.text = boring::passport::TwinFact(
            url_formatter::IDNToUnicode(facts.lookalike_of),
            facts.lookalike_used_site);
        row.color = "warnDot";
        break;
      case Fact::kCard:
        row.text = boring::passport::CardFact();
        row.color = "warnDot";
        break;
      case Fact::kConnection:
        row.text = boring::passport::ConnectionFact(in.connection_private);
        row.color = in.connection_private ? "ink2" : "warnDot";
        break;
      case Fact::kPassword:
        row.text = boring::passport::PasswordFact();
        break;
    }
    rows_.push_back(std::move(row));
  }

  const boring::BlockedTotals totals = boring::BlockedCounts::Get(url_);
  auto* popups =
      blocked_content::PopupBlockerTabHelper::FromWebContents(contents);
  footer_ = boring::passport::FooterText(
      totals.of(boring::BlockedKind::kAds),
      totals.of(boring::BlockedKind::kTrackers),
      totals.of(boring::BlockedKind::kCookieBanners),
      totals.of(boring::BlockedKind::kScripts),
      popups ? static_cast<uint32_t>(popups->GetBlockedPopupsCount()) : 0);
}

BoringPassportBubble::~BoringPassportBubble() = default;

// static
bool BoringPassportBubble::Show(LocationIconView* icon) {
  LocationBarView* bar = PassportChip::BarFor(icon);
  content::WebContents* contents = bar ? bar->GetWebContents() : nullptr;
  const Chip layout = PassportChip::LayoutFor(icon);
  if (!contents ||
      (layout != Chip::kKnown && layout != Chip::kNewToYou &&
       layout != Chip::kScamList)) {
    return false;
  }
  if (Current()) {
    Current()->Close();
    return true;
  }
  Current() = base::WrapUnique(new BoringPassportBubble(icon, contents, layout));
  BoringPassportBubble* bubble = Current().get();

  bubble->delegate_ = std::make_unique<views::BubbleDialogDelegate>(
      icon, views::BubbleBorder::TOP_LEFT);
  bubble->delegate_->SetTitle(std::u16string(boring::passport::kPassportName));
  bubble->delegate_->SetShowTitle(false);
  bubble->delegate_->SetAccessibleWindowRole(ax::mojom::Role::kDialog);
  bubble->delegate_->SetButtons(
      static_cast<int>(ui::mojom::DialogButton::kNone));
  bubble->delegate_->set_margins(gfx::Insets());
  bubble->delegate_->set_fixed_width(kWidth);
  bubble->delegate_->set_corner_radius(12);
  if (base::CommandLine::ForCurrentProcess()->HasSwitch(
          boring::passport::kPassportTestSwitch)) {
    // A test window never has the keyboard; see the shield panel.
    bubble->delegate_->set_close_on_deactivate(false);
  }
  bubble->delegate_->SetContentsView(bubble->MakeContents());
  bubble->widget_ = views::BubbleDialogDelegate::CreateBubble(
      bubble->delegate_.get(),
      base::BindOnce(&BoringPassportBubble::OnCloseRequested,
                     bubble->weak_factory_.GetWeakPtr()));
  bubble->motion_.Open(bubble->widget_.get());
  bubble->widget_->Show();
  icon->Update(/*suppress_animations=*/true);
  return true;
}

// static
bool BoringPassportBubble::IsShowingFor(const LocationIconView* icon) {
  return Current() && Current()->icon_.view() == icon;
}

// static
BoringPassportBubble* BoringPassportBubble::GetShowing() {
  return Current().get();
}

std::unique_ptr<views::View> BoringPassportBubble::MakeContents() {
  auto contents = std::make_unique<views::View>();
  contents->SetLayoutManager(std::make_unique<views::BoxLayout>(
      views::BoxLayout::Orientation::kVertical));

  // Head: the verdict in its tone, then the host.
  auto* head = contents->AddChildView(std::make_unique<views::View>());
  head->SetLayoutManager(std::make_unique<views::BoxLayout>(
      views::BoxLayout::Orientation::kVertical, gfx::Insets::TLBR(16, 18, 14, 18),
      4));
  head->AddChildView(MakeLabel(verdict_, 12, gfx::Font::Weight::SEMIBOLD,
                               VerdictTone(layout_).first));
  auto* host = head->AddChildView(MakeLabel(host_, 16, gfx::Font::Weight::SEMIBOLD,
                                            kColorOmniboxText));
  // Keep the registrable end visible on a long name.
  host->SetElideBehavior(gfx::ELIDE_HEAD);

  // Facts: one row each, a line on top of each.
  auto* facts = contents->AddChildView(std::make_unique<views::View>());
  facts->SetLayoutManager(std::make_unique<views::BoxLayout>(
      views::BoxLayout::Orientation::kVertical, gfx::Insets::VH(0, 8)));
  for (const Row& row : rows_) {
    auto* line = facts->AddChildView(std::make_unique<views::View>());
    line->SetBorder(views::CreateSolidSidedBorder(
        gfx::Insets::TLBR(1, 0, 0, 0), kColorBoringPassportLine));
    auto* layout = line->SetLayoutManager(std::make_unique<views::BoxLayout>(
        views::BoxLayout::Orientation::kHorizontal, gfx::Insets::TLBR(9, 10, 9, 10),
        12));
    layout->set_cross_axis_alignment(
        views::BoxLayout::CrossAxisAlignment::kStart);
    const ui::ColorId color = row.color == "bad" ? kColorBoringPassportBad
                              : row.color == "warnDot"
                                  ? kColorBoringPassportWarnDot
                                  : ui::kColorLabelForegroundSecondary;
    Fact fact = Fact::kVisits;
    for (Fact f : {Fact::kScamList, Fact::kVisits, Fact::kTwin, Fact::kCard,
                   Fact::kConnection, Fact::kPassword}) {
      if (row.icon == IconName(f)) {
        fact = f;
      }
    }
    auto* image = line->AddChildView(std::make_unique<views::ImageView>(
        ui::ImageModel::FromVectorIcon(IconFor(fact), color, kIconSize)));
    image->SetBorder(views::CreateEmptyBorder(gfx::Insets::TLBR(1, 0, 0, 0)));
    auto* text = line->AddChildView(
        MakeLabel(row.text, 14, gfx::Font::Weight::NORMAL, kColorOmniboxText));
    text->SetMultiLine(true);
    layout->SetFlexForView(text, 1);
  }

  // Buttons, or the Forget question in their place.
  button_row_ = contents->AddChildView(std::make_unique<views::View>());
  button_row_->SetLayoutManager(std::make_unique<views::BoxLayout>(
      views::BoxLayout::Orientation::kHorizontal, gfx::Insets::TLBR(14, 18, 16, 18),
      8));
  ShowButtons();

  // Footer: what was blocked on this page.
  auto* footer = contents->AddChildView(MakeLabel(
      footer_, 12, gfx::Font::Weight::NORMAL, ui::kColorLabelForegroundSecondary));
  footer->SetMultiLine(true);
  footer->SetBorder(views::CreatePaddedBorder(
      views::CreateSolidSidedBorder(gfx::Insets::TLBR(1, 0, 0, 0),
                                          kColorBoringPassportLine),
      gfx::Insets::TLBR(11, 18, 10, 18)));
  footer->SetBackground(
      views::CreateRoundedRectBackground(kColorBoringPassportFooter,
                                         gfx::RoundedCornersF(0, 0, 12, 12)));
  return contents;
}

void BoringPassportBubble::ShowButtons() {
  asking_ = false;
  button_row_->RemoveAllChildViews();
  const std::vector<std::u16string> labels =
      boring::passport::ButtonsFor(layout_);
  for (const std::u16string& label : labels) {
    auto* button = button_row_->AddChildView(std::make_unique<views::MdTextButton>(
        base::BindRepeating(&BoringPassportBubble::Press,
                            base::Unretained(this), label),
        label));
    button->SetPreferredSize(
        gfx::Size(button->GetPreferredSize().width(), 36));
    button->SetCornerRadius(8);
    if (label == boring::passport::kLeaveThisSite) {
      // The one solid button: the way out.
      button->SetStyle(ui::ButtonStyle::kProminent);
      button->SetBgColorIdOverride(kColorBoringPassportSolid);
      button->SetEnabledTextColors(kColorBoringPassportSolidText);
    } else if (label == boring::passport::kForgetThisSite) {
      button->SetStyle(ui::ButtonStyle::kText);
      button->SetEnabledTextColors(ui::kColorLabelForegroundSecondary);
    }
    if (label != boring::passport::kForgetThisSite) {
      static_cast<views::BoxLayout*>(button_row_->GetLayoutManager())
          ->SetFlexForView(button, 1);
    }
  }
  if (widget_) {
    widget_->GetRootView()->DeprecatedLayoutImmediately();
    delegate_->SizeToContents();
  }
}

void BoringPassportBubble::ShowQuestion() {
  asking_ = true;
  button_row_->RemoveAllChildViews();
  auto* question = button_row_->AddChildView(
      MakeLabel(boring::passport::kForgetQuestion, 14, gfx::Font::Weight::NORMAL,
                kColorOmniboxText));
  question->SetMultiLine(true);
  static_cast<views::BoxLayout*>(button_row_->GetLayoutManager())
      ->SetFlexForView(question, 1);
  for (const char16_t* label :
       {boring::passport::kCancel, boring::passport::kForget}) {
    auto* button = button_row_->AddChildView(std::make_unique<views::MdTextButton>(
        base::BindRepeating(&BoringPassportBubble::Press,
                            base::Unretained(this), std::u16string(label)),
        label));
    if (std::u16string(label) == boring::passport::kForget) {
      button->SetStyle(ui::ButtonStyle::kProminent);
    }
  }
  widget_->GetRootView()->DeprecatedLayoutImmediately();
  delegate_->SizeToContents();
}

void BoringPassportBubble::Press(const std::u16string& label) {
  content::WebContents* contents = contents_.get();
  // The page under the Passport must still be the one it was opened for.
  if (!contents || contents->GetLastCommittedURL() != url_) {
    Close();
    return;
  }
  BoringPassportTabHelper* helper =
      BoringPassportTabHelper::GetOrCreate(contents);
  if (label == boring::passport::kLeaveThisSite) {
    Close();
    // Replaces the page with the new tab page; nothing is stored.
    LeaveSiteFromSafetyTip(contents, GURL());
  } else if (label == boring::passport::kIKnowThisSite &&
             layout_ == Chip::kNewToYou) {
    helper->SetMarkedKnown(true);
    Close();
  } else if (label == boring::passport::kSiteSettings) {
    LocationBarView* bar =
        PassportChip::BarFor(static_cast<LocationIconView*>(icon_.view()));
    Close();
    // Chromium's page info from the same chip: permissions, cookies, the
    // connection and the link to this site's settings (Q3).
    if (bar) {
      bar->ShowPageInfoDialog();
    }
  } else if (label == boring::passport::kForgetThisSite) {
    ShowQuestion();
  } else if (label == boring::passport::kCancel && asking_) {
    ShowButtons();
  } else if (label == boring::passport::kForget && asking_) {
    const std::string site = boring::GetBlockingSite(url_);
    const GURL url = url_;
    helper->SetMarkedKnown(false);
    Close();
    // What the shield's Forget does, unchanged; history is kept (Q6).
    boring::ForgetSite(
        Profile::FromBrowserContext(contents->GetBrowserContext()), site, url,
        contents->GetWeakPtr());
  }
}

void BoringPassportBubble::Close() {
  if (widget_ && !motion_.closing()) {
    widget_->CloseWithReason(views::Widget::ClosedReason::kUnspecified);
  }
}

void BoringPassportBubble::OnCloseRequested(
    views::Widget::ClosedReason reason) {
  motion_.Close(base::BindOnce(&BoringPassportBubble::OnClosed,
                               weak_factory_.GetWeakPtr()));
}

void BoringPassportBubble::OnClosed() {
  views::View* icon = icon_.view();
  motion_.Detach();
  button_row_ = nullptr;
  widget_.reset();
  delegate_.reset();
  // Last: this deletes `this`.
  std::unique_ptr<BoringPassportBubble> self = std::move(Current());
  if (icon) {
    static_cast<LocationIconView*>(icon)->Update(/*suppress_animations=*/true);
  }
}

base::DictValue BoringPassportBubble::StateForTesting() const {
  base::DictValue out;
  out.Set("open", true);
  out.Set("name", std::u16string(boring::passport::kPassportName));
  out.Set("verdict", verdict_);
  out.Set("verdictTone", VerdictTone(layout_).second);
  out.Set("host", host_);
  base::ListValue facts;
  for (const Row& row : rows_) {
    facts.Append(base::DictValue()
                     .Set("text", row.text)
                     .Set("icon", row.icon)
                     .Set("color", row.color));
  }
  out.Set("facts", std::move(facts));
  base::ListValue buttons;
  if (asking_) {
    buttons.Append(boring::passport::kCancel);
    buttons.Append(boring::passport::kForget);
    out.Set("question", boring::passport::kForgetQuestion);
  } else {
    for (const std::u16string& label : boring::passport::ButtonsFor(layout_)) {
      buttons.Append(label);
    }
  }
  out.Set("buttons", std::move(buttons));
  out.Set("footer", footer_);
  if (widget_) {
    const gfx::Rect bounds = widget_->GetWindowBoundsInScreen();
    out.Set("width", bounds.width());
  }
  return out;
}

bool BoringPassportBubble::PressForTesting(const std::u16string& label) {
  if (asking_) {
    if (label != boring::passport::kCancel && label != boring::passport::kForget) {
      return false;
    }
  } else {
    const auto labels = boring::passport::ButtonsFor(layout_);
    if (std::find(labels.begin(), labels.end(), label) == labels.end()) {
      return false;
    }
  }
  Press(label);
  return true;
}

// The new tab page's half: components/boring/passport/passport_test.h.
namespace boring::passport {

namespace {

base::WeakPtr<content::WebContents>& TestTab() {
  static base::NoDestructor<base::WeakPtr<content::WebContents>> tab;
  return *tab;
}

LocationBarView* BarForPage(content::WebContents* page) {
  if (!page) {
    return nullptr;
  }
  BrowserWindowInterface* window =
      GlobalBrowserCollection::GetInstance()->FindBrowserWithTab(page);
  BrowserView* view =
      window ? BrowserView::GetBrowserViewForBrowser(window) : nullptr;
  return view ? view->GetLocationBarView() : nullptr;
}

std::string ColorName(std::optional<SkColor> color, const ui::ColorProvider* p) {
  if (!color || !p) {
    return "";
  }
  const std::pair<ui::ColorId, const char*> names[] = {
      {kColorBoringPassportWarnText, "warn"},
      {kColorBoringPassportBad, "bad"},
      {kColorOmniboxText, "ink"}};
  for (const auto& [id, name] : names) {
    if (p->GetColor(id) == *color) {
      return name;
    }
  }
  return "other";
}

}  // namespace

base::Value RunPassportTestCommand(content::WebContents* page,
                                   const base::ListValue& args) {
  if (!base::CommandLine::ForCurrentProcess()->HasSwitch(kPassportTestSwitch) ||
      args.empty() || !args[0].is_string()) {
    return base::Value();
  }
  const std::string& command = args[0].GetString();
  const std::string arg =
      args.size() > 1 && args[1].is_string() ? args[1].GetString() : "";
  LocationBarView* bar = BarForPage(page);
  content::WebContents* active = bar ? bar->GetWebContents() : nullptr;
  LocationIconView* icon = bar ? bar->location_icon_view() : nullptr;
  BoringPassportBubble* bubble = BoringPassportBubble::GetShowing();
  base::DictValue out;

  if (command == "openTab" && page && !arg.empty()) {
    content::WebContents* tab = page->OpenURL(
        content::OpenURLParams(GURL(arg), content::Referrer(),
                               WindowOpenDisposition::NEW_FOREGROUND_TAB,
                               ui::PAGE_TRANSITION_TYPED,
                               /*is_renderer_initiated=*/false),
        /*navigation_handle_callback=*/{});
    TestTab() = tab ? tab->GetWeakPtr() : base::WeakPtr<content::WebContents>();
    out.Set("opened", !!tab);
  } else if (command == "navigate" && active && !arg.empty()) {
    active->GetController().LoadURL(GURL(arg), content::Referrer(),
                                    ui::PAGE_TRANSITION_TYPED, std::string());
  } else if (command == "closeTab") {
    if (content::WebContents* tab = TestTab().get()) {
      tab->Close();
    }
  } else if (command == "passportState" && active) {
    out = BoringPassportTabHelper::GetOrCreate(active)->StateForTesting();
    out.Set("activeUrl", active->GetLastCommittedURL().spec());
    out.Set("canGoBack", active->GetController().CanGoBack());
    out.Set("entries", active->GetController().GetEntryCount());
  } else if (command == "chipState" && icon) {
    const Chip chip = PassportChip::ChipFor(icon);
    out.Set("chip", static_cast<int>(chip));
    out.Set("text", PassportChip::Text(icon));
    out.Set("label", std::u16string(icon->GetText()));
    out.Set("textColor",
            ColorName(PassportChip::Foreground(icon), icon->GetColorProvider()));
    out.Set("layout", static_cast<int>(PassportChip::LayoutFor(icon)));
    out.Set("a11yName",
            icon->GetViewAccessibility().GetCachedName());
    out.Set("visible", icon->GetVisible());
    out.Set("width", icon->width());
    out.Set("height", icon->height());
    out.Set("expanded", BoringPassportBubble::IsShowingFor(icon));
    out.Set("securityLevel",
            static_cast<int>(bar->GetLocationBarModel()->GetSecurityLevel()));
  } else if (command == "pressChip" && icon) {
    // What a keyboard press on the chip does.
    const ui::KeyEvent press(ui::EventType::kKeyPressed, ui::VKEY_RETURN,
                             ui::EF_NONE);
    out.Set("handled", icon->ShowBubble(press));
    out.Set("passportShowing", !!BoringPassportBubble::GetShowing());
    out.Set("pageInfoShowing", PageInfoBubbleViewBase::GetShownBubbleType() !=
                                   PageInfoBubbleViewBase::BUBBLE_NONE);
  } else if (command == "passportPopup") {
    if (bubble) {
      out = bubble->StateForTesting();
    } else {
      out.Set("open", false);
    }
    out.Set("pageInfoShowing", PageInfoBubbleViewBase::GetShownBubbleType() !=
                                   PageInfoBubbleViewBase::BUBBLE_NONE);
  } else if (command == "pressButton" && bubble && !arg.empty()) {
    out.Set("pressed", bubble->PressForTesting(base::UTF8ToUTF16(arg)));
  } else if (command == "closePopup") {
    if (bubble) {
      bubble->Close();
    }
    if (views::BubbleDialogDelegateView* info =
            PageInfoBubbleViewBase::GetPageInfoBubbleForTesting()) {
      info->GetWidget()->CloseNow();
    }
  } else if (command == "addVisit" && active && !arg.empty() &&
             args.size() > 2 && args[2].is_int()) {
    // A visit in the past, as if the person had been there.
    Profile* profile = Profile::FromBrowserContext(active->GetBrowserContext());
    if (history::HistoryService* history = HistoryServiceFactory::GetForProfile(
            profile, ServiceAccessType::EXPLICIT_ACCESS)) {
      history->AddPage(GURL(arg), base::Time::Now() - base::Days(args[2].GetInt()),
                       history::SOURCE_BROWSED);
      out.Set("added", true);
    }
  } else if (command == "engage" && active && !arg.empty() && args.size() > 2 &&
             args[2].is_int()) {
    Profile* profile = Profile::FromBrowserContext(active->GetBrowserContext());
    if (auto* engagement = site_engagement::SiteEngagementService::Get(profile)) {
      engagement->ResetBaseScoreForURL(GURL(arg), args[2].GetInt());
      out.Set("engaged", true);
    }
  } else if (command == "knownSites" && active) {
    out.Set("sites", Profile::FromBrowserContext(active->GetBrowserContext())
                         ->GetPrefs()
                         ->GetList(boring::prefs::kPassportKnownSites)
                         .Clone());
  } else {
    out.Set("error", "unknown command or nothing to act on");
  }
  return base::Value(std::move(out));
}

}  // namespace boring::passport
