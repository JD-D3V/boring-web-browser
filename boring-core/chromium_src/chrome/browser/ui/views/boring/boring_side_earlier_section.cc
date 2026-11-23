// Copyright 2026 boring. BSD style license.

#include "chrome/browser/ui/views/boring/boring_side_earlier_section.h"

#include <algorithm>
#include <map>
#include <memory>
#include <utility>

#include "base/functional/bind.h"
#include "base/no_destructor.h"
#include "base/task/single_thread_task_runner.h"
#include "chrome/app/chrome_command_ids.h"
#include "chrome/app/vector_icons/vector_icons.h"
#include "chrome/browser/profiles/profile.h"
#include "chrome/browser/ui/browser_commands.h"
#include "chrome/browser/ui/browser_window/public/browser_window_interface.h"
#include "chrome/browser/ui/color/chrome_color_id.h"
#include "chrome/browser/ui/layout_constants.h"
#include "chrome/browser/ui/views/boring/boring_earlier_popup.h"
#include "chrome/browser/ui/views/side_panel/boring_shelf/shelf_data.h"
#include "chrome/browser/ui/views/side_panel/boring_shelf/shelf_row.h"
#include "components/boring/core/boring_prefs.h"
#include "components/prefs/pref_service.h"
#include "ui/accessibility/ax_enums.mojom.h"
#include "ui/base/metadata/metadata_impl_macros.h"
#include "ui/views/accessibility/view_accessibility.h"
#include "ui/views/border.h"
#include "ui/views/controls/button/label_button.h"
#include "ui/views/controls/label.h"
#include "ui/views/controls/scroll_view.h"
#include "ui/views/layout/box_layout.h"
#include "ui/views/layout/box_layout_view.h"
#include "ui/views/view_class_properties.h"

namespace {

// Screen C09: 18 px between sections, 2 px between rows.
constexpr int kGapAbove = 10;
constexpr int kRowGap = 2;

// The section of each window, so the Earlier commands can find it.
std::map<BrowserWindowInterface*, BoringSideEarlierSection*>& Sections() {
  static base::NoDestructor<
      std::map<BrowserWindowInterface*, BoringSideEarlierSection*>>
      sections;
  return *sections;
}

BoringSideEarlierSection* SectionFor(BrowserWindowInterface* browser) {
  auto it = Sections().find(browser);
  return it == Sections().end() ? nullptr : it->second;
}

}  // namespace

BoringSideEarlierSection::BoringSideEarlierSection(
    BrowserWindowInterface* browser,
    tabs::VerticalTabStripStateController* controller)
    : browser_(browser), controller_(controller) {
  SetLayoutManager(std::make_unique<views::BoxLayout>(
                       views::BoxLayout::Orientation::kVertical,
                       gfx::Insets(), kRowGap))
      ->set_cross_axis_alignment(views::BoxLayout::CrossAxisAlignment::kStretch);
  const int side =
      GetLayoutConstant(LayoutConstant::kVerticalTabStripHorizontalPadding);
  SetProperty(views::kMarginsKey, gfx::Insets::TLBR(kGapAbove, side, 0, side));
  GetViewAccessibility().SetRole(ax::mojom::Role::kGroup);
  GetViewAccessibility().SetName(u"Earlier tabs");
  SetVisible(false);

  // Only a normal window of a regular profile has Earlier tabs; the service
  // is null for a private or guest profile.
  if (browser_->GetType() == BrowserWindowInterface::TYPE_NORMAL) {
    service_ =
        boring::earlier::EarlierTabsService::Get(browser_->GetProfile());
  }
  if (!service_) {
    return;
  }
  service_->AddObserver(this);
  Sections()[browser_] = this;
  pref_registrar_.Init(browser_->GetProfile()->GetPrefs());
  pref_registrar_.Add(
      boring::prefs::kEarlierEnabled,
      base::BindRepeating(&BoringSideEarlierSection::ScheduleRebuild,
                          base::Unretained(this)));
  if (controller_) {
    collapse_subscription_ =
        controller_->RegisterOnCollapseChanged(base::BindRepeating(
            &BoringSideEarlierSection::OnCollapseChanged,
            base::Unretained(this)));
  }
  Rebuild();
}

BoringSideEarlierSection::~BoringSideEarlierSection() {
  auto it = Sections().find(browser_);
  if (it != Sections().end() && it->second == this) {
    Sections().erase(it);
  }
  if (service_) {
    service_->RemoveObserver(this);
  }
}

// static
bool BoringSideEarlierSection::RevealFor(BrowserWindowInterface* browser) {
  BoringSideEarlierSection* section = SectionFor(browser);
  if (!section || !section->service_ || section->service_->count() == 0) {
    return false;
  }
  section->Reveal(/*focus=*/true);
  return true;
}

// static
bool BoringSideEarlierSection::ShowAllFor(BrowserWindowInterface* browser) {
  BoringSideEarlierSection* section = SectionFor(browser);
  if (!section || !section->service_) {
    return false;
  }
  section->ShowAll();
  return true;
}

void BoringSideEarlierSection::OnEarlierTabsChanged() {
  ScheduleRebuild();
}

void BoringSideEarlierSection::AddedToWidget() {
  views::View::AddedToWidget();
  ScheduleRebuild();
}

void BoringSideEarlierSection::OnCollapseChanged(
    tabs::VerticalTabStripCollapseState state) {
  // Narrowed to icons, the section goes; widened, it comes back closed up.
  if (state != tabs::VerticalTabStripCollapseState::kExpanded) {
    expanded_ = false;
  }
  ScheduleRebuild();
}

bool BoringSideEarlierSection::IsWide() const {
  return !controller_ || controller_->GetCollapseState() ==
                             tabs::VerticalTabStripCollapseState::kExpanded;
}

void BoringSideEarlierSection::ScheduleRebuild() {
  if (rebuild_pending_) {
    return;
  }
  rebuild_pending_ = true;
  // After the current task: a press on a row removes the row, so the rows
  // are never rebuilt inside their own click.
  base::SingleThreadTaskRunner::GetCurrentDefault()->PostTask(
      FROM_HERE, base::BindOnce(
                     [](base::WeakPtr<BoringSideEarlierSection> section) {
                       if (section) {
                         section->Rebuild();
                       }
                     },
                     weak_factory_.GetWeakPtr()));
}

void BoringSideEarlierSection::Rebuild() {
  rebuild_pending_ = false;
  first_row_ = nullptr;
  RemoveAllChildViews();
  if (!service_) {
    SetVisible(false);
    return;
  }
  const boring::shelf::EarlierState state =
      boring::shelf::GetEarlierState(browser_->GetProfile());
  // Only while Earlier tabs is on and holds at least one tab.
  if (!state.enabled || state.total == 0 || state.newest.empty()) {
    expanded_ = false;
    focus_pending_ = false;
    SetVisible(false);
    return;
  }
  if (!IsWide()) {
    SetVisible(false);
    return;
  }

  AddChildView(std::make_unique<boring::shelf::ShelfSectionHeading>(
      u"Earlier", u"kept 30 days", /*regular=*/true));

  const size_t shown =
      expanded_ ? state.newest.size()
                : std::min(kNewestRows, state.newest.size());
  views::View* rows = this;
  if (expanded_) {
    // Opened out: every row the list keeps, scrolling inside a box so the
    // open tabs keep their room.
    auto scroll = std::make_unique<views::ScrollView>();
    scroll->SetBackgroundColor(std::nullopt);
    scroll->SetDrawOverflowIndicator(false);
    scroll->SetHorizontalScrollBarMode(
        views::ScrollView::ScrollBarMode::kDisabled);
    scroll->ClipHeightTo(
        0, kMaxVisibleRows * (boring::shelf::ShelfRow::kHeight + kRowGap));
    auto column = std::make_unique<views::BoxLayoutView>();
    column->SetOrientation(views::BoxLayout::Orientation::kVertical);
    column->SetBetweenChildSpacing(kRowGap);
    column->SetCrossAxisAlignment(views::BoxLayout::CrossAxisAlignment::kStretch);
    rows = scroll->SetContents(std::move(column));
    AddChildView(std::move(scroll));
  }
  for (size_t i = 0; i < shown; ++i) {
    const boring::shelf::ShelfItem& item = state.newest[i];
    views::View* row = rows->AddChildView(
        std::make_unique<boring::shelf::ShelfRow>(
            base::BindRepeating(&BoringSideEarlierSection::OnRow,
                                base::Unretained(this), item.id),
            item.icon ? *item.icon : kBoringDocIcon, item.title, item.meta));
    if (!first_row_) {
      first_row_ = row;
    }
  }
  if (!expanded_ && state.total > shown) {
    // The same command as the pop-up's "Show all": with side tabs it opens
    // this section out (BoringSideEarlierSection::ShowAllFor).
    AddChildView(std::make_unique<boring::shelf::ShelfRow>(
        base::BindRepeating(
            [](BrowserWindowInterface* browser) {
              chrome::ExecuteCommand(browser, IDC_BORING_EARLIER_SHOW_ALL);
            },
            base::Unretained(browser_.get())),
        kBoringClockIcon, boring::shelf::ShowAllText(state.total),
        std::u16string()));
  }
  if (expanded_) {
    AddClearFooter(state.total);
  } else {
    confirming_ = false;
  }
  SetVisible(true);
  PreferredSizeChanged();

  if (focus_pending_ && first_row_ && GetWidget()) {
    focus_pending_ = false;
    first_row_->RequestFocus();
  }
}

void BoringSideEarlierSection::Reveal(bool focus) {
  focus_pending_ = focus;
  if (controller_ && controller_->IsCollapsed()) {
    // Widen the strip; the section comes back when it is wide again.
    controller_->RequestCollapse(false);
  }
  ScheduleRebuild();
}

void BoringSideEarlierSection::ShowAll() {
  expanded_ = true;
  Reveal(/*focus=*/true);
}

void BoringSideEarlierSection::OnRow(const std::string& id) {
  // The tab comes back at the end of this window's strip and leaves the list;
  // the service tells every section, which then rebuilds.
  if (service_) {
    service_->Reopen(id, browser_);
  }
}

void BoringSideEarlierSection::AddClearFooter(size_t total) {
  // Screen C08's footer control, at the end of the opened-out list.
  if (!confirming_) {
    AddChildView(BoringEarlierTextButton(
        base::BindRepeating(&BoringSideEarlierSection::OnAskClear,
                            base::Unretained(this)),
        u"Clear earlier tabs", kColorBoringShelfHeading, /*strong=*/false));
    return;
  }
  auto* ask = AddChildView(
      std::make_unique<views::Label>(BoringEarlierClearQuestion(total)));
  ask->SetEnabledColor(kColorBoringShelfText);
  ask->SetHorizontalAlignment(gfx::ALIGN_LEFT);
  ask->SetMultiLine(true);
  ask->SetBorder(views::CreateEmptyBorder(gfx::Insets::VH(4, 8)));
  auto* buttons = AddChildView(std::make_unique<views::BoxLayoutView>());
  buttons->SetOrientation(views::BoxLayout::Orientation::kHorizontal);
  buttons->SetBetweenChildSpacing(8);
  buttons->AddChildView(BoringEarlierTextButton(
      base::BindRepeating(&BoringSideEarlierSection::OnClear,
                          base::Unretained(this)),
      u"Clear", kColorBoringShelfText, /*strong=*/true));
  buttons->AddChildView(BoringEarlierTextButton(
      base::BindRepeating(&BoringSideEarlierSection::OnCancelClear,
                          base::Unretained(this)),
      u"Cancel", kColorBoringShelfHeading, /*strong=*/false));
}

void BoringSideEarlierSection::OnAskClear() {
  confirming_ = true;
  ScheduleRebuild();
}

void BoringSideEarlierSection::OnCancelClear() {
  confirming_ = false;
  ScheduleRebuild();
}

void BoringSideEarlierSection::OnClear() {
  confirming_ = false;
  expanded_ = false;
  // The service tells every section, which then rebuilds (and hides, empty).
  BoringEarlierClearAll(service_);
  ScheduleRebuild();
}

BEGIN_METADATA(BoringSideEarlierSection)
END_METADATA
