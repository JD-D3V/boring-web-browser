// Copyright 2026 boring. BSD style license.

#include "chrome/browser/ui/views/boring/boring_earlier_popup.h"

#include <algorithm>
#include <utility>

#include "base/functional/bind.h"
#include "base/strings/string_number_conversions.h"
#include "base/task/single_thread_task_runner.h"
#include "base/time/time.h"
#include "chrome/app/chrome_command_ids.h"
#include "chrome/app/vector_icons/vector_icons.h"
#include "chrome/browser/profiles/profile.h"
#include "chrome/browser/ui/browser_commands.h"
#include "chrome/browser/ui/browser_window/public/browser_window_interface.h"
#include "chrome/browser/ui/color/chrome_color_id.h"
#include "chrome/browser/ui/views/side_panel/boring_shelf/shelf_data.h"
#include "chrome/browser/ui/views/side_panel/boring_shelf/shelf_row.h"
#include "components/url_formatter/elide_url.h"
#include "ui/base/mojom/dialog_button.mojom.h"
#include "ui/gfx/font.h"
#include "ui/gfx/font_list.h"
#include "ui/views/border.h"
#include "ui/views/controls/button/label_button.h"
#include "ui/views/controls/label.h"
#include "ui/views/controls/separator.h"
#include "ui/views/layout/box_layout.h"
#include "ui/views/view.h"
#include "url/origin.h"

namespace {

// Screen C08: the card is 340 wide with 6 around it.
constexpr int kWidth = 340;
constexpr int kMargin = 6;
// The newest rows shown; "Show all" has the rest.
constexpr size_t kMaxRows = 5;
// Screen C08 draws its rows 34 high with a 12px gap (the Shelf's are 32, 10).
constexpr int kRowHeight = 34;
constexpr int kRowGap = 12;

void SetFont(views::Label* label, int size, gfx::Font::Weight weight) {
  const gfx::FontList base = label->font_list();
  label->SetFontList(
      base.DeriveWithSizeDelta(size - base.GetFontSize())
          .DeriveWithWeight(weight));
}

views::Label* AddLabel(views::View* parent,
                       const std::u16string& text,
                       int size,
                       gfx::Font::Weight weight,
                       ui::ColorId color,
                       const gfx::Insets& insets) {
  auto* label = parent->AddChildView(std::make_unique<views::Label>(text));
  label->SetEnabledColor(color);
  label->SetHorizontalAlignment(gfx::ALIGN_LEFT);
  label->SetBorder(views::CreateEmptyBorder(insets));
  SetFont(label, size, weight);
  return label;
}

// A text button with the weight it is drawn in: LabelButton has no public
// font setting, but its label is ours to restyle in a subclass. Only the
// weight changes, never the size (LabelButton checks the size).
class TextButton : public views::LabelButton {
 public:
  TextButton(PressedCallback callback,
             const std::u16string& text,
             gfx::Font::Weight weight)
      : views::LabelButton(std::move(callback), text) {
    label()->SetFontList(label()->font_list().DeriveWithWeight(weight));
  }
};

std::unique_ptr<views::LabelButton> MakeTextButton(
    views::Button::PressedCallback callback,
    const std::u16string& text,
    ui::ColorId color,
    gfx::Font::Weight weight) {
  auto button =
      std::make_unique<TextButton>(std::move(callback), text, weight);
  button->SetEnabledTextColors(color);
  button->SetHorizontalAlignment(gfx::ALIGN_LEFT);
  // 32 high as drawn, as wide as its whole text: a width fixed here, before
  // the button is in a widget, was measured too narrow and cut the label
  // ("Show...", "Clear earlier...").
  button->SetMinSize(gfx::Size(0, 32));
  button->SetMaxSize(gfx::Size(0, 32));
  button->SetElideBehavior(gfx::NO_ELIDE);
  return button;
}

}  // namespace

BoringEarlierPopup::BoringEarlierPopup(views::View* anchor,
                                       BrowserWindowInterface* browser,
                                       base::OnceClosure closed)
    : browser_(browser),
      service_(boring::earlier::EarlierTabsService::Get(browser->GetProfile())),
      closed_(std::move(closed)) {
  delegate_ = std::make_unique<views::BubbleDialogDelegate>(
      anchor, views::BubbleBorder::TOP_RIGHT);
  delegate_->SetAccessibleTitle(u"Earlier tabs");
  delegate_->SetShowTitle(false);
  delegate_->SetButtons(static_cast<int>(ui::mojom::DialogButton::kNone));
  delegate_->SetEnableArrowKeyTraversal(true);
  delegate_->set_margins(gfx::Insets(kMargin));
  delegate_->set_fixed_width(kWidth);

  auto contents = std::make_unique<views::View>();
  contents->SetLayoutManager(std::make_unique<views::BoxLayout>(
      views::BoxLayout::Orientation::kVertical));
  contents_ = contents.get();
  delegate_->SetContentsView(std::move(contents));
  if (service_) {
    service_->AddObserver(this);
  }
  Rebuild();
}

BoringEarlierPopup::~BoringEarlierPopup() {
  if (service_) {
    service_->RemoveObserver(this);
  }
  widget_.reset();
}

void BoringEarlierPopup::Show() {
  widget_ = views::BubbleDialogDelegate::CreateBubble(
      delegate_.get(),
      base::BindOnce(&BoringEarlierPopup::OnCloseRequested,
                     weak_factory_.GetWeakPtr()));
  widget_->Show();
}

void BoringEarlierPopup::Close() {
  if (widget_) {
    widget_->CloseWithReason(views::Widget::ClosedReason::kUnspecified);
  }
}

void BoringEarlierPopup::OnCloseRequested(views::Widget::ClosedReason reason) {
  // Escape, a click elsewhere or a choice. Posted, so the owner may delete
  // this from the task.
  if (closed_) {
    base::SingleThreadTaskRunner::GetCurrentDefault()->PostTask(
        FROM_HERE, std::move(closed_));
  }
}

void BoringEarlierPopup::OnEarlierTabsChanged() {
  ScheduleRebuild();
}

void BoringEarlierPopup::ScheduleRebuild() {
  // Never inside the press that asked for it: that press belongs to a button
  // the rebuild removes.
  if (rebuild_pending_) {
    return;
  }
  rebuild_pending_ = true;
  base::SingleThreadTaskRunner::GetCurrentDefault()->PostTask(
      FROM_HERE, base::BindOnce(
                     [](base::WeakPtr<BoringEarlierPopup> self) {
                       if (self) {
                         self->rebuild_pending_ = false;
                         self->Rebuild();
                       }
                     },
                     weak_factory_.GetWeakPtr()));
}

void BoringEarlierPopup::Rebuild() {
  contents_->RemoveAllChildViews();
  const size_t total = service_ ? service_->count() : 0;

  AddLabel(contents_, u"Earlier tabs", 14, gfx::Font::Weight::SEMIBOLD,
           kColorBoringShelfText, gfx::Insets::TLBR(10, 10, 0, 10));
  auto* about = AddLabel(
      contents_,
      u"Tabs you have not used for a day move here. They are kept for 30 "
      u"days.",
      13, gfx::Font::Weight::NORMAL, kColorBoringShelfHeading,
      gfx::Insets::TLBR(2, 10, 6, 10));
  about->SetMultiLine(true);

  if (service_) {
    const base::Time now = base::Time::Now();
    boring::earlier::EarlierBucket current_bucket =
        boring::earlier::EarlierBucket::kYesterday;
    bool first = true;
    size_t shown = 0;
    for (const boring::earlier::EarlierEntry& entry : service_->entries()) {
      if (shown++ >= kMaxRows) {
        break;
      }
      const auto bucket = boring::earlier::BucketFor(now, entry.last_used);
      if (first || bucket != current_bucket) {
        AddLabel(contents_, boring::earlier::BucketName(bucket), 12,
                 gfx::Font::Weight::SEMIBOLD, kColorBoringShelfHeading,
                 gfx::Insets::TLBR(10, 10, 4, 10));
        current_bucket = bucket;
        first = false;
      }
      contents_->AddChildView(std::make_unique<boring::shelf::ShelfRow>(
          base::BindRepeating(&BoringEarlierPopup::OnRow,
                              base::Unretained(this), entry.id),
          kBoringDocIcon, boring::shelf::ShelfTitle(entry.title, entry.url),
          // The site only, like the Shelf's rows: a full path would push
          // the title out and show query tokens.
          url_formatter::FormatOriginForSecurityDisplay(
              url::Origin::Create(entry.url),
              url_formatter::SchemeDisplay::OMIT_HTTP_AND_HTTPS),
          kRowHeight, kRowGap));
    }
  }

  // The footer: a line, then Show all and Clear, or the question.
  auto* line = contents_->AddChildView(std::make_unique<views::Separator>());
  line->SetColorId(kColorBoringShelfEdge);
  line->SetBorder(views::CreateEmptyBorder(gfx::Insets::TLBR(6, 0, 0, 0)));
  auto* footer = contents_->AddChildView(std::make_unique<views::View>());
  auto* box = footer->SetLayoutManager(std::make_unique<views::BoxLayout>(
      views::BoxLayout::Orientation::kHorizontal, gfx::Insets::VH(0, 4), 8));
  box->set_cross_axis_alignment(views::BoxLayout::CrossAxisAlignment::kCenter);
  if (confirming_) {
    auto* ask = AddLabel(
        footer,
        u"Clear " + base::NumberToString16(total) +
            (total == 1 ? u" tab" : u" tabs") +
            u" from Earlier? The pages stay in your history.",
        12, gfx::Font::Weight::NORMAL, kColorBoringShelfText,
        gfx::Insets::VH(4, 0));
    ask->SetMultiLine(true);
    box->SetFlexForView(ask, 1);
    footer->AddChildView(MakeTextButton(
        base::BindRepeating(&BoringEarlierPopup::OnClear,
                            base::Unretained(this)),
        u"Clear", kColorBoringShelfText, gfx::Font::Weight::MEDIUM));
    footer->AddChildView(MakeTextButton(
        base::BindRepeating(&BoringEarlierPopup::OnCancelClear,
                            base::Unretained(this)),
        u"Cancel", kColorBoringShelfHeading, gfx::Font::Weight::NORMAL));
  } else {
    footer->AddChildView(MakeTextButton(
        base::BindRepeating(&BoringEarlierPopup::OnShowAll,
                            base::Unretained(this)),
        boring::shelf::ShowAllText(total), kColorBoringShelfText,
        gfx::Font::Weight::MEDIUM));
    auto* spacer = footer->AddChildView(std::make_unique<views::View>());
    box->SetFlexForView(spacer, 1);
    footer->AddChildView(MakeTextButton(
        base::BindRepeating(&BoringEarlierPopup::OnAskClear,
                            base::Unretained(this)),
        u"Clear earlier tabs", kColorBoringShelfHeading,
        gfx::Font::Weight::NORMAL));
  }
  contents_->InvalidateLayout();
  if (widget_) {
    delegate_->SizeToContents();
  }
}

void BoringEarlierPopup::OnRow(const std::string& id) {
  if (service_) {
    service_->Reopen(id, browser_);
  }
  Close();
}

void BoringEarlierPopup::OnShowAll() {
  // The Shelf, with Earlier open to every entry.
  chrome::ExecuteCommand(browser_, IDC_BORING_EARLIER_SHOW_ALL);
  Close();
}

void BoringEarlierPopup::OnAskClear() {
  confirming_ = true;
  ScheduleRebuild();
}

void BoringEarlierPopup::OnCancelClear() {
  confirming_ = false;
  ScheduleRebuild();
}

void BoringEarlierPopup::OnClear() {
  if (service_) {
    service_->ClearAll();
  }
  confirming_ = false;
  Close();
}
