// Copyright 2026 boring. BSD style license.

#include "chrome/browser/ui/views/toolbar/boring_accounts_button.h"

#include <optional>
#include <utility>
#include <vector>

#include "base/command_line.h"
#include "base/files/file_path.h"
#include "base/files/file_util.h"
#include "base/functional/bind.h"
#include "base/numerics/safe_conversions.h"
#include "base/strings/string_number_conversions.h"
#include "base/strings/string_split.h"
#include "base/strings/string_util.h"
#include "base/strings/utf_string_conversions.h"
#include "base/task/single_thread_task_runner.h"
#include "base/task/thread_pool.h"
#include "base/time/time.h"
#include "cc/paint/paint_flags.h"
#include "chrome/app/vector_icons/vector_icons.h"
#include "chrome/browser/profiles/profile.h"
#include "chrome/browser/ui/browser_window/public/browser_window_interface.h"
#include "chrome/browser/ui/color/chrome_color_id.h"
#include "chrome/browser/ui/navigator/browser_navigator.h"
#include "chrome/browser/ui/navigator/browser_navigator_params.h"
#include "components/boring/accounts/accounts_store.h"
#include "components/prefs/pref_service.h"
#include "ui/accessibility/ax_action_data.h"
#include "ui/accessibility/ax_enums.mojom.h"
#include "ui/base/metadata/metadata_impl_macros.h"
#include "ui/base/models/image_model.h"
#include "ui/base/page_transition_types.h"
#include "ui/base/window_open_disposition.h"
#include "ui/color/color_id.h"
#include "ui/color/color_provider.h"
#include "ui/gfx/canvas.h"
#include "ui/gfx/color_utils.h"
#include "ui/gfx/font_list.h"
#include "ui/gfx/geometry/insets.h"
#include "ui/gfx/geometry/rounded_corners_f.h"
#include "ui/gfx/image/canvas_image_source.h"
#include "ui/gfx/image/image_skia.h"
#include "ui/views/accessibility/view_accessibility.h"
#include "ui/views/animation/ink_drop.h"
#include "ui/views/background.h"
#include "ui/views/border.h"
#include "ui/views/bubble/bubble_border.h"
#include "ui/views/bubble/bubble_dialog_delegate_view.h"
#include "ui/views/controls/button/image_button.h"
#include "ui/views/controls/button/label_button.h"
#include "ui/views/controls/highlight_path_generator.h"
#include "ui/views/controls/image_view.h"
#include "ui/views/controls/label.h"
#include "ui/views/controls/separator.h"
#include "ui/views/layout/box_layout.h"
#include "ui/views/style/typography.h"
#include "ui/views/view.h"
#include "ui/views/view_utils.h"
#include "url/gurl.h"

#if BUILDFLAG(IS_WIN)
#include "ui/views/win/hwnd_util.h"
#endif

namespace {

using boring::accounts::Account;
using boring::accounts::Provider;

// Sizes from the compiled design (Window.dc.html, the avatar and the "Your
// accounts" pop-up).
constexpr int kPanelWidth = 360;
constexpr int kPanelCorner = 12;
constexpr int kButtonCircle = 24;
constexpr int kButtonInitialSize = 12;
constexpr int kGlyphSize = 18;
constexpr int kRowCircle = 32;
constexpr int kRowInitialSize = 13;
constexpr int kLinkButton = 30;
constexpr int kLinkIcon = 15;
constexpr int kSmallCorner = 7;
constexpr int kAddButtonHeight = 32;

constexpr char kTestSwitch[] = "boring-accounts-test";
constexpr char kTestReport[] = "boring-accounts-test.txt";
// Other has no page of its own to open: Settings asks for the addresses.
constexpr char kAddOtherUrl[] = "chrome://settings/accounts?add=other";

// Circles by position: the first account in the accent, then the tab group
// colours, the drawn teal first, the rest in Chromium's order. No colour is
// stored, so moving an account moves its colour with its place.
constexpr ui::ColorId kGroupCircles[] = {
    kColorTabGroupTabStripFrameActiveCyan,
    kColorTabGroupTabStripFrameActiveBlue,
    kColorTabGroupTabStripFrameActiveRed,
    kColorTabGroupTabStripFrameActiveYellow,
    kColorTabGroupTabStripFrameActiveGreen,
    kColorTabGroupTabStripFrameActivePink,
    kColorTabGroupTabStripFrameActivePurple,
    kColorTabGroupTabStripFrameActiveOrange,
};

gfx::FontList Font(int size, gfx::Font::Weight weight) {
  const gfx::FontList base;
  return base.DeriveWithSizeDelta(size - base.GetFontSize())
      .DeriveWithWeight(weight);
}

// A filled circle with one letter in the middle.
class InitialSource : public gfx::CanvasImageSource {
 public:
  InitialSource(std::u16string initial,
                SkColor fill,
                SkColor ink,
                int diameter,
                int font_size)
      : gfx::CanvasImageSource(gfx::Size(diameter, diameter)),
        initial_(std::move(initial)),
        fill_(fill),
        ink_(ink),
        font_size_(font_size) {}

  void Draw(gfx::Canvas* canvas) override {
    const float radius = size().width() / 2.0f;
    cc::PaintFlags flags;
    flags.setAntiAlias(true);
    flags.setStyle(cc::PaintFlags::kFill_Style);
    flags.setColor(fill_);
    canvas->DrawCircle(gfx::PointF(radius, radius), radius, flags);
    canvas->DrawStringRectWithFlags(
        initial_, Font(font_size_, gfx::Font::Weight::SEMIBOLD), ink_,
        gfx::Rect(size()), gfx::Canvas::TEXT_ALIGN_CENTER);
  }

 private:
  const std::u16string initial_;
  const SkColor fill_;
  const SkColor ink_;
  const int font_size_;
};

// The account's initial in its circle, painted from the window's colours,
// so it follows the Look, the accent and light or dark.
ui::ImageModel InitialImage(std::u16string initial,
                            size_t index,
                            int diameter,
                            int font_size) {
  return ui::ImageModel::FromImageGenerator(
      base::BindRepeating(
          [](const std::u16string& initial, size_t index, int diameter,
             int font_size, const ui::ColorProvider* colors) {
            SkColor fill;
            SkColor ink;
            if (index == 0) {
              // The accent, with the text colour the palette made readable
              // on it, whatever accent was picked.
              fill = colors->GetColor(ui::kColorSysPrimary);
              ink = colors->GetColor(ui::kColorSysOnPrimary);
            } else {
              fill = colors->GetColor(
                  kGroupCircles[(index - 1) % std::size(kGroupCircles)]);
              ink = color_utils::GetColorWithMaxContrast(fill);
            }
            return gfx::CanvasImageSource::MakeImageSkia<InitialSource>(
                initial, fill, ink, diameter, font_size);
          },
          std::move(initial), index, diameter, font_size),
      gfx::Size(diameter, diameter));
}

views::Label* AddLabel(views::View* parent,
                       const std::u16string& text,
                       int size,
                       gfx::Font::Weight weight,
                       bool secondary) {
  auto* label = parent->AddChildView(std::make_unique<views::Label>(text));
  label->SetFontList(Font(size, weight));
  label->SetHorizontalAlignment(gfx::ALIGN_LEFT);
  label->SetEnabledColor(secondary ? ui::kColorLabelForegroundSecondary
                                   : ui::kColorLabelForeground);
  return label;
}

void AddRule(views::View* parent) {
  auto* rule = parent->AddChildView(std::make_unique<views::Separator>());
  rule->SetColorId(ui::kColorBubbleBorder);
}

// A 30px square with a 1px ring and a 15px glyph: Mail, Calendar, Files.
void AddLinkButton(views::View* parent,
                   views::Button::PressedCallback callback,
                   const gfx::VectorIcon& icon,
                   const std::u16string& name) {
  auto* button = parent->AddChildView(
      std::make_unique<views::ImageButton>(std::move(callback)));
  button->SetImageModel(
      views::Button::STATE_NORMAL,
      ui::ImageModel::FromVectorIcon(icon, ui::kColorLabelForegroundSecondary,
                                     kLinkIcon));
  button->SetImageHorizontalAlignment(views::ImageButton::ALIGN_CENTER);
  button->SetImageVerticalAlignment(views::ImageButton::ALIGN_MIDDLE);
  button->SetPreferredSize(gfx::Size(kLinkButton, kLinkButton));
  button->SetBorder(
      views::CreateRoundedRectBorder(1, kSmallCorner, ui::kColorBubbleBorder));
  button->SetTooltipText(name);
  button->GetViewAccessibility().SetName(name);
  views::InkDrop::Get(button)->SetMode(views::InkDropHost::InkDropMode::ON);
  views::InstallRoundRectHighlightPathGenerator(button, gfx::Insets(),
                                                kSmallCorner);
}

// One of the six Add buttons: 32px high, a third of the row each.
views::LabelButton* AddProviderButton(views::View* parent,
                                      views::Button::PressedCallback callback,
                                      const std::u16string& name) {
  auto* button = parent->AddChildView(
      std::make_unique<views::LabelButton>(std::move(callback), name));
  button->SetHorizontalAlignment(gfx::ALIGN_CENTER);
  // 13px in weight 500, as drawn.
  button->SetLabelStyle(views::style::STYLE_BODY_3_MEDIUM);
  button->SetPreferredSize(gfx::Size(1, kAddButtonHeight));
  button->SetBorder(
      views::CreateRoundedRectBorder(1, kSmallCorner, kColorBoringEdge));
  button->GetViewAccessibility().SetName(u"Add " + name + u" account");
  views::InkDrop::Get(button)->SetMode(views::InkDropHost::InkDropMode::ON);
  button->SetHasInkDropActionOnClick(true);
  views::InstallRoundRectHighlightPathGenerator(button, gfx::Insets(),
                                                kSmallCorner);
  return button;
}

// What the test hook reports: every label and button the panel holds, as
// it is, so a smoke reads the real panel rather than the list behind it.
void Describe(views::View* view, std::string* out) {
  if (auto* button = views::Button::AsButton(view)) {
    *out += "button\t" +
            base::UTF16ToUTF8(button->GetViewAccessibility().GetCachedName()) +
            "\t" + (button->GetEnabled() ? "on" : "off") + "\n";
    return;
  }
  if (auto* label = views::AsViewClass<views::Label>(view)) {
    *out += "label\t" + base::UTF16ToUTF8(label->GetText()) + "\n";
    return;
  }
  for (views::View* child : view->children()) {
    if (child->GetVisible()) {
      Describe(child, out);
    }
  }
}

}  // namespace

BoringAccountsButton::BoringAccountsButton(BrowserWindowInterface* browser)
    : ToolbarButton(base::BindRepeating(&BoringAccountsButton::OnPressed,
                                        base::Unretained(this))),
      browser_(browser) {
  SetTooltipText(u"Your accounts");
  GetViewAccessibility().SetName(u"Your accounts");
  GetViewAccessibility().SetHasPopup(ax::mojom::HasPopup::kDialog);
  GetViewAccessibility().SetIsCollapsed();

  // The initial follows the list wherever it is changed: the panel,
  // Settings, the new tab page, another window.
  pref_change_registrar_.Init(browser_->GetProfile()->GetPrefs());
  pref_change_registrar_.Add(
      boring::accounts::kAccountsPref,
      base::BindRepeating(
          [](BoringAccountsButton* self) {
            self->PaintInitial();
            // An open panel would show a list that has changed.
            self->ClosePanel();
          },
          base::Unretained(this)));
  PaintInitial();

  // boring: test hook. --boring-accounts-test=<step>,<step>... runs the
  // steps a second apart, a few seconds after the first window is up, once
  // per run: "open" and "close" the panel, "add=<provider>" presses that Add
  // button ("add=other" too), "mail=<n>", "calendar=<n>" and "files=<n>"
  // press that link on row n (from 1), "report" writes what the button and
  // the panel show to boring-accounts-test.txt in the profile folder. With
  // the switch the panel opens without taking the keyboard and stays open
  // when the window loses it, as the shield's panel does for its test.
  // Like the other boring test hooks it ships, and does nothing without
  // the switch.
  static bool test_steps_posted = false;
  const base::CommandLine& command_line =
      *base::CommandLine::ForCurrentProcess();
  if (!test_steps_posted && command_line.HasSwitch(kTestSwitch)) {
    test_steps_posted = true;
    base::SingleThreadTaskRunner::GetCurrentDefault()->PostDelayedTask(
        FROM_HERE,
        base::BindOnce(&BoringAccountsButton::RunTestSteps,
                       weak_factory_.GetWeakPtr(),
                       command_line.GetSwitchValueASCII(kTestSwitch)),
        base::Seconds(4));
  }
}

BoringAccountsButton::~BoringAccountsButton() {
  // The panel is anchored to this view, so it goes first.
  panel_motion_.Detach();
  panel_.reset();
}

void BoringAccountsButton::OnThemeChanged() {
  ToolbarButton::OnThemeChanged();
  PaintInitial();
}

bool BoringAccountsButton::HandleAccessibleAction(
    const ui::AXActionData& action_data) {
  // The button says it opens a dialog, so UI Automation offers Expand and
  // Collapse for it; View answers neither.
  if (action_data.action == ax::mojom::Action::kExpand) {
    if (!panel_) {
      ShowPanel();
    }
    return true;
  }
  if (action_data.action == ax::mojom::Action::kCollapse) {
    ClosePanel();
    return true;
  }
  return ToolbarButton::HandleAccessibleAction(action_data);
}

void BoringAccountsButton::PaintInitial() {
  const std::vector<Account> accounts = boring::accounts::GetAccounts(
      *browser_->GetProfile()->GetPrefs());
  if (accounts.empty()) {
    SetImageModel(views::Button::STATE_NORMAL,
                  ui::ImageModel::FromVectorIcon(
                      kBoringAccountIcon, kColorToolbarButtonIcon, kGlyphSize));
    return;
  }
  SetImageModel(views::Button::STATE_NORMAL,
                InitialImage(boring::accounts::Initial(accounts[0]), 0,
                             kButtonCircle, kButtonInitialSize));
}

void BoringAccountsButton::OnPressed(const ui::Event& event) {
  // Pressing the button again puts the panel away.
  if (panel_) {
    ClosePanel();
    return;
  }
  ShowPanel();
}

bool BoringAccountsButton::IsPanelShowing() const {
  return panel_ && !panel_motion_.closing();
}

void BoringAccountsButton::ShowPanel() {
  if (panel_) {
    return;
  }
  const std::vector<Account> accounts = boring::accounts::GetAccounts(
      *browser_->GetProfile()->GetPrefs());
  const bool full = accounts.size() >= boring::accounts::kMaxAccounts;

  panel_delegate_ = std::make_unique<views::BubbleDialogDelegate>(
      this, views::BubbleBorder::TOP_RIGHT);
  // The dialog's name for a screen reader; the heading inside shows it.
  panel_delegate_->SetTitle(u"Your accounts");
  panel_delegate_->SetShowTitle(false);
  panel_delegate_->SetShowCloseButton(false);
  panel_delegate_->SetButtons(static_cast<int>(ui::mojom::DialogButton::kNone));
  panel_delegate_->set_margins(gfx::Insets());
  panel_delegate_->set_corner_radius(kPanelCorner);
  panel_delegate_->set_fixed_width(kPanelWidth);
  panel_delegate_->set_highlight_button_when_shown(true);
  const bool for_test =
      base::CommandLine::ForCurrentProcess()->HasSwitch(kTestSwitch);
  if (for_test) {
    panel_delegate_->set_close_on_deactivate(false);
  }

  auto contents = std::make_unique<views::View>();
  contents->SetLayoutManager(std::make_unique<views::BoxLayout>(
      views::BoxLayout::Orientation::kVertical));

  // Header.
  auto* header = contents->AddChildView(std::make_unique<views::View>());
  header->SetLayoutManager(std::make_unique<views::BoxLayout>(
      views::BoxLayout::Orientation::kVertical,
      gfx::Insets::TLBR(16, 18, 10, 18), 2));
  AddLabel(header, u"Your accounts", 14, gfx::Font::Weight::SEMIBOLD, false);
  AddLabel(header,
           u"The mail and other accounts you are signed in to. One click to "
           u"each.",
           13, gfx::Font::Weight::NORMAL, true)
      ->SetMultiLine(true);

  // One row per account.
  auto* rows = contents->AddChildView(std::make_unique<views::View>());
  rows->SetLayoutManager(std::make_unique<views::BoxLayout>(
      views::BoxLayout::Orientation::kVertical, gfx::Insets::VH(0, 8)));
  for (size_t i = 0; i < accounts.size(); ++i) {
    const Account& account = accounts[i];
    AddRule(rows);
    auto* row = rows->AddChildView(std::make_unique<views::View>());
    auto* layout = row->SetLayoutManager(std::make_unique<views::BoxLayout>(
        views::BoxLayout::Orientation::kHorizontal, gfx::Insets(10), 12));
    layout->set_cross_axis_alignment(
        views::BoxLayout::CrossAxisAlignment::kCenter);
    row->AddChildView(std::make_unique<views::ImageView>(
        InitialImage(boring::accounts::Initial(account), i, kRowCircle,
                     kRowInitialSize)));
    auto* text = row->AddChildView(std::make_unique<views::View>());
    text->SetLayoutManager(std::make_unique<views::BoxLayout>(
        views::BoxLayout::Orientation::kVertical));
    // The name is the person's own text: shown as plain text, cut short
    // with an ellipsis rather than pushing the buttons out.
    AddLabel(text, base::UTF8ToUTF16(account.name), 13,
             gfx::Font::Weight::MEDIUM, false)
        ->SetElideBehavior(gfx::ELIDE_TAIL);
    AddLabel(text, boring::accounts::ProviderLine(account), 12,
             gfx::Font::Weight::NORMAL, true)
        ->SetElideBehavior(gfx::ELIDE_TAIL);
    layout->SetFlexForView(text, 1, /*use_min_size=*/true);
    const auto bind = [&](Link link) {
      return base::BindRepeating(&BoringAccountsButton::OnOpenLink,
                                 base::Unretained(this), account.id, link);
    };
    AddLinkButton(row, bind(Link::kMail), kBoringMailIcon, u"Mail");
    if (account.links.calendar.is_valid()) {
      AddLinkButton(row, bind(Link::kCalendar), kBoringCalIcon, u"Calendar");
    }
    if (account.links.files.is_valid()) {
      AddLinkButton(row, bind(Link::kFiles), kBoringFolderIcon, u"Files");
    }
  }

  // Add an account: the five companies and Other, three to a row.
  AddRule(contents.get());
  auto* add = contents->AddChildView(std::make_unique<views::View>());
  add->SetLayoutManager(std::make_unique<views::BoxLayout>(
      views::BoxLayout::Orientation::kVertical,
      gfx::Insets::TLBR(12, 18, 14, 18), 8));
  AddLabel(add, u"Add an account", 12, gfx::Font::Weight::SEMIBOLD, true);
  std::vector<std::pair<std::u16string, views::Button::PressedCallback>>
      providers;
  for (const auto& known : boring::accounts::KnownProviders()) {
    providers.emplace_back(
        base::UTF8ToUTF16(known.name),
        base::BindRepeating(&BoringAccountsButton::OnAddKnown,
                            base::Unretained(this), known.provider));
  }
  providers.emplace_back(
      u"Other", base::BindRepeating(&BoringAccountsButton::OnAddOther,
                                    base::Unretained(this)));
  auto* grid = add->AddChildView(std::make_unique<views::View>());
  grid->SetLayoutManager(std::make_unique<views::BoxLayout>(
      views::BoxLayout::Orientation::kVertical, gfx::Insets(), 6));
  views::View* grid_row = nullptr;
  for (size_t i = 0; i < providers.size(); ++i) {
    if (i % 3 == 0) {
      grid_row = grid->AddChildView(std::make_unique<views::View>());
      auto* row_layout =
          grid_row->SetLayoutManager(std::make_unique<views::BoxLayout>(
              views::BoxLayout::Orientation::kHorizontal, gfx::Insets(), 6));
      row_layout->SetDefaultFlex(1);
    }
    AddProviderButton(grid_row, std::move(providers[i].second),
                      providers[i].first)
        ->SetEnabled(!full);
  }
  if (full) {
    AddLabel(add,
             u"You have 12 accounts. Remove one in Settings to add another.",
             12, gfx::Font::Weight::NORMAL, true)
        ->SetMultiLine(true);
  }

  // The footer band, in the page colour, with the panel's bottom corners.
  AddRule(contents.get());
  auto* footer = contents->AddChildView(std::make_unique<views::View>());
  footer->SetLayoutManager(std::make_unique<views::BoxLayout>(
      views::BoxLayout::Orientation::kVertical, gfx::Insets::VH(10, 18)));
  footer->SetBackground(views::CreateRoundedRectBackground(
      kColorNewTabPageBackground,
      gfx::RoundedCornersF(0, 0, kPanelCorner, kPanelCorner)));
  AddLabel(footer,
           u"You sign in on each company's own page. Boring Browser never "
           u"sees your password and sends nothing to us.",
           12, gfx::Font::Weight::NORMAL, true)
      ->SetMultiLine(true);

  panel_delegate_->SetContentsView(std::move(contents));
  panel_ = views::BubbleDialogDelegate::CreateBubble(
      panel_delegate_.get(),
      base::BindOnce(&BoringAccountsButton::OnPanelCloseRequested,
                     weak_factory_.GetWeakPtr()));
  panel_motion_.Open(panel_.get());
  GetViewAccessibility().SetIsExpanded();
  if (for_test) {
    panel_->ShowInactive();
  } else {
    panel_->Show();
  }
}

void BoringAccountsButton::ClosePanel() {
  if (panel_ && !panel_motion_.closing()) {
    panel_->CloseWithReason(views::Widget::ClosedReason::kUnspecified);
  }
}

void BoringAccountsButton::OnPanelCloseRequested(
    views::Widget::ClosedReason reason) {
  // Escape, a click elsewhere or a choice: play out first, then go.
  panel_motion_.Close(base::BindOnce(&BoringAccountsButton::OnPanelClosed,
                                     weak_factory_.GetWeakPtr()));
}

void BoringAccountsButton::OnPanelClosed() {
  panel_motion_.Detach();
  panel_.reset();
  panel_delegate_.reset();
  GetViewAccessibility().SetIsCollapsed();
}

void BoringAccountsButton::OnOpenLink(const std::string& id, Link link) {
  ClosePanel();
  // The address comes from the store, checked again as it is read.
  std::optional<Account> account = boring::accounts::FindAccount(
      *browser_->GetProfile()->GetPrefs(), id);
  if (!account) {
    return;
  }
  const GURL& url = link == Link::kMail       ? account->links.mail
                    : link == Link::kCalendar ? account->links.calendar
                                              : account->links.files;
  if (url.is_valid()) {
    OpenInNewTab(url);
  }
}

void BoringAccountsButton::OnAddKnown(Provider provider) {
  ClosePanel();
  if (boring::accounts::AddKnown(browser_->GetProfile()->GetPrefs(),
                                 provider)) {
    // The company's own sign-in page. The person signs in there, or not.
    OpenInNewTab(boring::accounts::KnownLinks(provider).sign_in);
  }
}

void BoringAccountsButton::OnAddOther() {
  ClosePanel();
  OpenInNewTab(GURL(kAddOtherUrl));
}

void BoringAccountsButton::OpenInNewTab(const GURL& url) {
  NavigateParams params(browser_, url, ui::PAGE_TRANSITION_AUTO_BOOKMARK);
  params.disposition = WindowOpenDisposition::NEW_FOREGROUND_TAB;
  Navigate(&params);
}

void BoringAccountsButton::RunTestSteps(std::string steps) {
  std::vector<std::string> list = base::SplitString(
      steps, ",", base::TRIM_WHITESPACE, base::SPLIT_WANT_NONEMPTY);
  if (list.empty()) {
    return;
  }
  const std::string step = list.front();
  list.erase(list.begin());
  if (!list.empty()) {
    base::SingleThreadTaskRunner::GetCurrentDefault()->PostDelayedTask(
        FROM_HERE,
        base::BindOnce(&BoringAccountsButton::RunTestSteps,
                       weak_factory_.GetWeakPtr(),
                       base::JoinString(list, ",")),
        base::Seconds(1));
  }

  const std::vector<std::string> parts = base::SplitString(
      step, "=", base::TRIM_WHITESPACE, base::SPLIT_WANT_ALL);
  const std::string& name = parts[0];
  const std::string value = parts.size() > 1 ? parts[1] : std::string();
  if (name == "open") {
    ShowPanel();
  } else if (name == "close") {
    ClosePanel();
  } else if (name == "report") {
    WriteTestReport();
  } else if (name == "add") {
    std::optional<Provider> provider =
        boring::accounts::ProviderFromKey(value);
    if (provider == Provider::kOther) {
      OnAddOther();
    } else if (provider) {
      OnAddKnown(*provider);
    }
  } else if (name == "mail" || name == "calendar" || name == "files") {
    int row = 0;
    const std::vector<Account> accounts = boring::accounts::GetAccounts(
        *browser_->GetProfile()->GetPrefs());
    if (base::StringToInt(value, &row) && row >= 1 &&
        static_cast<size_t>(row) <= accounts.size()) {
      OnOpenLink(accounts[row - 1].id, name == "mail"       ? Link::kMail
                                       : name == "calendar" ? Link::kCalendar
                                                            : Link::kFiles);
    }
  }
}

void BoringAccountsButton::WriteTestReport() {
  const std::vector<Account> accounts = boring::accounts::GetAccounts(
      *browser_->GetProfile()->GetPrefs());
  std::string report = "button\t" +
                       base::UTF16ToUTF8(GetViewAccessibility().GetCachedName()) +
                       "\t" +
                       (accounts.empty()
                            ? std::string("glyph")
                            : base::UTF16ToUTF8(
                                  boring::accounts::Initial(accounts[0]))) +
                       "\n";
  report += std::string("panel\t") + (IsPanelShowing() ? "1" : "0") + "\n";
  if (IsPanelShowing()) {
#if BUILDFLAG(IS_WIN)
    report += "hwnd\t" +
              base::NumberToString(
                  reinterpret_cast<uintptr_t>(views::HWNDForWidget(panel_.get()))) +
              "\n";
#endif
    report += "width\t" +
              base::NumberToString(
                  panel_->GetWindowBoundsInScreen().width()) +
              "\n";
    Describe(panel_delegate_->GetContentsView(), &report);
  }
  report += "end\n";
  base::ThreadPool::PostTask(
      FROM_HERE, {base::MayBlock()},
      base::BindOnce(
          [](const base::FilePath& path, const std::string& text) {
            base::WriteFile(path, text);
          },
          browser_->GetProfile()->GetPath().AppendASCII(kTestReport),
          std::move(report)));
}

BEGIN_METADATA(BoringAccountsButton)
END_METADATA
