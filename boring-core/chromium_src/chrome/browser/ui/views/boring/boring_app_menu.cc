// Copyright 2026 boring. BSD style license.

#include "chrome/browser/ui/views/boring/boring_app_menu.h"

#include <algorithm>
#include <memory>
#include <optional>
#include <string>
#include <string_view>
#include <vector>

#include "base/command_line.h"
#include "base/files/file_path.h"
#include "base/files/file_util.h"
#include "base/functional/bind.h"
#include "base/location.h"
#include "base/memory/raw_ptr.h"
#include "base/memory/weak_ptr.h"
#include "base/no_destructor.h"
#include "base/strings/strcat.h"
#include "base/strings/utf_string_conversions.h"
#include "base/task/single_thread_task_runner.h"
#include "base/task/thread_pool.h"
#include "base/time/time.h"
#include "cc/paint/paint_flags.h"
#include "chrome/app/chrome_command_ids.h"
#include "chrome/app/vector_icons/vector_icons.h"
#include "chrome/browser/ui/color/chrome_color_id.h"
#include "chrome/browser/ui/toolbar/app_menu_model.h"
#include "chrome/grit/generated_resources.h"
#include "ui/accessibility/ax_enums.mojom.h"
#include "ui/base/accelerators/accelerator.h"
#include "ui/base/accelerators/menu_label_accelerator_util.h"
#include "ui/base/l10n/l10n_util.h"
#include "ui/base/metadata/metadata_header_macros.h"
#include "ui/base/metadata/metadata_impl_macros.h"
#include "ui/base/models/button_menu_item_model.h"
#include "ui/base/models/image_model.h"
#include "ui/base/models/menu_model.h"
#include "ui/base/ui_base_features.h"
#include "ui/color/color_id.h"
#include "ui/color/color_provider.h"
#include "ui/events/event.h"
#include "ui/events/keycodes/keyboard_codes.h"
#include "ui/gfx/canvas.h"
#include "ui/gfx/font.h"
#include "ui/gfx/font_list.h"
#include "ui/gfx/geometry/insets.h"
#include "ui/gfx/geometry/rect.h"
#include "ui/gfx/geometry/rect_f.h"
#include "ui/gfx/geometry/size.h"
#include "ui/gfx/vector_icon_types.h"
#include "ui/views/accessibility/view_accessibility.h"
#include "ui/views/border.h"
#include "ui/views/controls/button/button.h"
#include "ui/views/controls/image_view.h"
#include "ui/views/controls/label.h"
#include "ui/views/controls/menu/menu_config.h"
#include "ui/views/controls/menu/menu_controller.h"
#include "ui/views/controls/menu/menu_item_view.h"
#include "ui/views/controls/menu/submenu_view.h"
#include "ui/views/layout/box_layout.h"
#include "ui/views/view.h"
#include "ui/views/view_class_properties.h"
#include "ui/views/view_utils.h"

namespace boring {

static_assert(kAppMenuHeadingId < 0 &&
              kAppMenuHeadingId != ui::MenuModel::kTitleId);

namespace {

// The numbers of the compiled design's menu (design/v12-compiled,
// Window.dc.html, screen C07), in DIP. tools/tests/test_app_menu_refresh.py
// reads them back, so keep one per line.
constexpr int kMenuWidth = 320;   // Menu width.
constexpr int kMenuPadding = 6;   // Menu padding: cards and rows inset.
constexpr int kCardPadding = 3;   // Card padding.
constexpr int kCardRadius = 8;    // Card border-radius.
constexpr int kRowRadius = 6;     // Row border-radius (the hover).
// Row height 30: the 13px font's 18 line and 6 above and below.
constexpr int kRowVerticalMargin = 6;
constexpr int kTileHeight = 54;   // Top button height.
constexpr int kTileRadius = 8;    // Top button border-radius.
constexpr int kTileGap = 6;       // Top buttons gap.
constexpr int kTileIconGap = 5;   // Top button gap, icon to label.
constexpr int kTileIconSize = 19;  // Top button icon.
constexpr int kTileFontSize = 12;  // 12.5 in the design; whole pixels only.
constexpr int kTileBelow = 0;      // The first heading follows at once.
constexpr int kHeadingIndent = 16;  // menu padding + heading padding 10.
constexpr int kHeadingFontSize = 12;  // 11.5 in the design; whole pixels.
// Heading padding-top 10, less the pixel the font's line box is taller
// than the design's.
constexpr int kHeadingAbove = 9;
// Heading padding-bottom 4, less the same pixel.
constexpr int kHeadingBelow = 3;
constexpr int kBarAbove = 8;          // Bar margin-top.
constexpr int kBarLinePadding = 6;    // Bar padding-top.
constexpr int kBarButtonHeight = 34;  // Settings and Exit height.
constexpr int kBarButtonRadius = 7;   // Their border-radius.
constexpr int kBarButtonPadding = 10;  // Their padding.
constexpr int kBarIconGap = 10;        // Their gap, icon to label.
constexpr int kBarIconSize = 16;  // Their icons.
constexpr int kRowFontSize = 13;  // The rows' text.
constexpr int kRowIconSize = 16;  // The rows' icons.

// A font size of the mock at the default text size. With a larger system
// text size the rows' font grows, and this grows by as much.
int ScaledFontSize(int design_size) {
  const int rows = views::MenuConfig::instance().font_list.GetFontSize();
  return std::max(design_size, design_size + rows - kRowFontSize);
}

// The menu's own top and bottom inset is the system menu's border; the
// tiles and the bar make up the rest of the mock's padding (menu-style.patch
// sets that border to 6).
int ExtraEdge() {
  const views::MenuConfig& config = views::MenuConfig::instance();
  return std::max(0, kMenuPadding -
                         config.rounded_menu_vertical_border_size.value_or(
                             kMenuPadding));
}

const gfx::VectorIcon& IconFor(int command_id) {
  const bool rounded = features::IsRoundedIconsEnabled();
  switch (command_id) {
    case IDC_NEW_TAB:
      return rounded ? kTabIcon : kNewTabRefreshOldIcon;
    case IDC_NEW_WINDOW:
      return rounded ? kNewWindowIcon : kNewWindowOldIcon;
    case IDC_NEW_INCOGNITO_WINDOW:
      return rounded ? kIncognitoIcon : kIncognitoRefreshMenuOldIcon;
    case IDC_OPTIONS:
      return rounded ? kSettingsIcon : kSettingsMenuOldIcon;
    case IDC_EXIT:
      return rounded ? kExitToAppIcon : kExitMenuOldIcon;
    default:
      return gfx::VectorIcon::EmptyIcon();
  }
}

// What a button shows: the model's label, so an Incognito or isolated
// window's first tile still says so ("New Incognito tab"). Only the third
// tile is shorter; its accessible name and tooltip carry the full name.
// Mnemonics stay those of the rows the tiles replace.
std::u16string ShownLabel(int command_id, const std::u16string& label) {
  switch (command_id) {
    case IDC_NEW_INCOGNITO_WINDOW:
      return u"&Incognito";
    default:
      return label;
  }
}

// One tile, or one button of the bottom bar.
class MenuButton : public views::Button {
  METADATA_HEADER(MenuButton, views::Button)

 public:
  MenuButton(views::MenuItemView* item,
             ui::ButtonMenuItemModel* model,
             size_t index,
             const AppMenuPress& press,
             bool bar)
      : views::Button(base::BindRepeating(press, model, index)),
        item_(item),
        bar_(bar),
        icon_(&IconFor(model->GetCommandIdAt(index))) {
    const int command_id = model->GetCommandIdAt(index);
    // The menu only moves its keyboard selection onto focusable buttons.
    SetFocusBehavior(FocusBehavior::ALWAYS);
    GetViewAccessibility().SetRole(ax::mojom::Role::kMenuItem);

    auto layout = std::make_unique<views::BoxLayout>(
        bar ? views::BoxLayout::Orientation::kHorizontal
            : views::BoxLayout::Orientation::kVertical,
        bar ? gfx::Insets::VH(0, kBarButtonPadding) : gfx::Insets(),
        bar ? kBarIconGap : kTileIconGap);
    layout->set_main_axis_alignment(
        views::BoxLayout::MainAxisAlignment::kCenter);
    layout->set_cross_axis_alignment(
        views::BoxLayout::CrossAxisAlignment::kCenter);
    SetLayoutManager(std::move(layout));

    icon_view_ = AddChildView(std::make_unique<views::ImageView>());
    icon_view_->SetCanProcessEventsWithinSubtree(false);
    icon_view_->GetViewAccessibility().SetIsIgnored(true);

    const gfx::FontList& menu_font = views::MenuConfig::instance().font_list;
    label_ = AddChildView(std::make_unique<views::Label>());
    label_->SetCanProcessEventsWithinSubtree(false);
    label_->GetViewAccessibility().SetIsIgnored(true);
    label_->SetAutoColorReadabilityEnabled(false);
    label_->SetFontList(
        bar ? menu_font.Derive(0, gfx::Font::NORMAL,
                               gfx::Font::Weight::MEDIUM)
            : menu_font.Derive(
                  ScaledFontSize(kTileFontSize) - menu_font.GetFontSize(),
                  gfx::Font::NORMAL, gfx::Font::Weight::MEDIUM));
    label_->SetMnemonicMode(views::Label::MnemonicMode::kHide);
    const std::u16string shown =
        ShownLabel(command_id, model->GetLabelAt(index));
    label_->SetText(shown);

    // Name and tooltip carry the full name and the shortcut, which the
    // tiles do not show.
    const std::u16string name = views::MenuItemView::GetAccessibleNameForMenuItem(
        model->GetLabelAt(index), std::u16string(), std::nullopt);
    std::u16string shortcut;
    ui::Accelerator accelerator;
    if (model->GetAcceleratorAt(index, &accelerator)) {
      shortcut = ui::Accelerator(accelerator.key_code(),
                                 accelerator.modifiers())
                     .GetShortcutText();
    }
    GetViewAccessibility().SetName(
        views::MenuItemView::GetAccessibleNameForMenuItem(
            model->GetLabelAt(index), shortcut, std::nullopt));
    SetTooltipText(shortcut.empty()
                       ? name
                       : l10n_util::GetStringFUTF16(IDS_APP_MENU_BLOCK_TOOLTIP,
                                                    name, shortcut));

    // Like views::MenuItemView does for its rows.
    const char16_t mnemonic = ui::GetMnemonic(shown);
    SetProperty(views::kMenuMnemonicKey, mnemonic);
    if (mnemonic && views::MenuConfig::instance().use_mnemonics) {
      GetViewAccessibility().SetKeyShortcuts(
          base::UTF16ToUTF8(std::u16string(1, mnemonic)));
    }

    if (command_id == IDC_NEW_INCOGNITO_WINDOW) {
      SetProperty(views::kElementIdentifierKey,
                  AppMenuModel::kIncognitoMenuItem);
    }
    SetEnabled(model->IsEnabledAt(index));
    UpdateColors();
  }
  MenuButton(const MenuButton&) = delete;
  MenuButton& operator=(const MenuButton&) = delete;
  ~MenuButton() override = default;

  // views::Button:
  gfx::Size CalculatePreferredSize(
      const views::SizeBounds& available_size) const override {
    // The mock's heights, taller only when a larger text size needs it.
    // Known limit: not taller in touch mode. On Windows the stock rows do
    // not grow there either (MenuConfig's touchable sizes are ChromeOS
    // only), so the bar's 34 stays under a 44 touch target.
    const gfx::Size content =
        views::Button::CalculatePreferredSize(available_size);
    return bar_ ? gfx::Size(content.width(),
                            std::max(kBarButtonHeight,
                                     content.height() + 2 * kBarIconGap))
                : gfx::Size(content.width(),
                            std::max(kTileHeight,
                                     content.height() + 2 * kTileIconGap));
  }

  void AddedToWidget() override {
    views::Button::AddedToWidget();
    // The menu decides whether to underline mnemonics just before it opens.
    label_->SetMnemonicMode(item_->ShouldShowMnemonics()
                                ? views::Label::MnemonicMode::kUnderline
                                : views::Label::MnemonicMode::kHide);
  }

  void StateChanged(ButtonState old_state) override {
    views::Button::StateChanged(old_state);
    UpdateColors();
  }

  void OnPaintBackground(gfx::Canvas* canvas) override {
    const ui::ColorProvider* colors = GetColorProvider();
    const gfx::RectF bounds(GetLocalBounds());
    const float radius = bar_ ? kBarButtonRadius : kTileRadius;
    cc::PaintFlags flags;
    flags.setAntiAlias(true);
    flags.setStyle(cc::PaintFlags::kFill_Style);
    if (IsHot()) {
      // The accent wash the card rows hover with.
      flags.setColor(colors->GetColor(ui::kColorAppMenuRowBackgroundHovered));
      canvas->DrawRoundRect(bounds, radius, flags);
    }
    if (!bar_) {
      // The top buttons are outlined, not filled: a 1px edge inside.
      gfx::RectF edge = bounds;
      edge.Inset(0.5f);
      flags.setStyle(cc::PaintFlags::kStroke_Style);
      flags.setStrokeWidth(1.0f);
      flags.setColor(colors->GetColor(kColorBoringEdge));
      canvas->DrawRoundRect(edge, radius - 0.5f, flags);
    }
  }

 private:
  bool IsHot() const {
    return GetState() == STATE_HOVERED || GetState() == STATE_PRESSED;
  }

  void UpdateColors() {
    const bool disabled = GetState() == STATE_DISABLED;
    // A hovered button's text is a hovered row's: the same ink normally,
    // the system highlight text in high contrast.
    const ui::ColorId text = disabled  ? ui::kColorMenuItemForegroundDisabled
                             : IsHot() ? ui::kColorMenuItemForegroundSelected
                                       : ui::kColorMenuItemForeground;
    // A button you hover turns its icon accent, as the rows do. The bar's
    // icons are otherwise the quieter ink, the top buttons' the ink.
    const ui::ColorId icon = disabled ? ui::kColorMenuIconDisabled
                             : IsHot() ? ui::kColorSysPrimary
                             : bar_    ? ui::kColorMenuItemForegroundSecondary
                                       : ui::kColorMenuIcon;
    label_->SetEnabledColor(text);
    icon_view_->SetImage(ui::ImageModel::FromVectorIcon(
        *icon_, icon, bar_ ? kBarIconSize : kTileIconSize));
  }

  const raw_ptr<views::MenuItemView> item_;
  const bool bar_;
  const raw_ptr<const gfx::VectorIcon> icon_;
  raw_ptr<views::ImageView> icon_view_ = nullptr;
  raw_ptr<views::Label> label_ = nullptr;
};

BEGIN_METADATA(MenuButton)
END_METADATA

// The tile row (equal tiles, side by side) or the bottom bar (a hairline,
// then the first button on the left and the rest on the right).
class ButtonRow : public views::View {
  METADATA_HEADER(ButtonRow, views::View)

 public:
  ButtonRow(views::MenuItemView* item,
            ui::ButtonMenuItemModel* model,
            const AppMenuPress& press,
            bool bar)
      : bar_(bar) {
    for (size_t i = 0; i < model->GetItemCount(); ++i) {
      AddChildView(std::make_unique<MenuButton>(item, model, i, press, bar));
    }
  }
  ButtonRow(const ButtonRow&) = delete;
  ButtonRow& operator=(const ButtonRow&) = delete;
  ~ButtonRow() override = default;

  // views::View:
  gfx::Size CalculatePreferredSize(
      const views::SizeBounds& available_size) const override {
    int width = 0;
    int height = 0;
    for (const views::View* child : children()) {
      width += child->GetPreferredSize().width();
      height = std::max(height, child->GetPreferredSize().height());
    }
    const int gaps =
        children().empty() ? 0 : static_cast<int>(children().size()) - 1;
    width += gaps * (bar_ ? kBarIconGap : kTileGap);
    return bar_ ? gfx::Size(width, 1 + kBarLinePadding + height)
                : gfx::Size(width, height);
  }

  void Layout(PassKey) override {
    if (children().empty()) {
      return;
    }
    if (bar_) {
      const int y = 1 + kBarLinePadding;
      const int h = std::max(0, height() - y);
      int end = width();
      for (size_t i = children().size(); i-- > 0;) {
        views::View* child = children()[i];
        const int w = std::min(child->GetPreferredSize().width(), width());
        if (i == 0) {
          child->SetBounds(0, y, w, h);
        } else {
          child->SetBounds(end - w, y, w, h);
          end -= w + kBarIconGap;
        }
      }
      return;
    }
    // Equal tiles that stretch to the row; the last takes any odd pixel.
    const int n = static_cast<int>(children().size());
    const int w = std::max(0, (width() - (n - 1) * kTileGap) / n);
    int x = 0;
    for (int i = 0; i < n; ++i) {
      const int tile_width = i == n - 1 ? std::max(0, width() - x) : w;
      children()[i]->SetBounds(x, 0, tile_width, height());
      x += w + kTileGap;
    }
  }

  void OnPaint(gfx::Canvas* canvas) override {
    views::View::OnPaint(canvas);
    if (bar_) {
      canvas->FillRect(gfx::Rect(0, 0, width(), 1),
                       GetColorProvider()->GetColor(ui::kColorMenuSeparator));
    }
  }

 private:
  const bool bar_;
};

BEGIN_METADATA(ButtonRow)
END_METADATA

void PaintCard(const std::vector<views::MenuItemView*>& card) {
  for (size_t i = 0; i < card.size(); ++i) {
    const bool first = i == 0;
    const bool last = i + 1 == card.size();
    views::MenuItemView::MenuItemBackground background(
        kColorAppMenuToolsAndActionsBackground, first ? kCardRadius : 0,
        last ? kCardRadius : 0, kMenuPadding);
    background.top_padding = first ? kCardPadding : 0;
    background.bottom_padding = last ? kCardPadding : 0;
    background.highlight_radius = kRowRadius;
    background.highlight_inset = kCardPadding;
    card[i]->SetMenuItemBackground(background);
    card[i]->set_vertical_margin(kRowVerticalMargin);
    // The menu's usual hover tint hardly shows on the card's fill.
    card[i]->SetSelectedColorId(ui::kColorAppMenuRowBackgroundHovered);
  }
}

// What the keyboard selection is on: the hot button of a row of buttons,
// else the row's own title.
std::string SelectedForTest(views::MenuController* controller) {
  views::MenuItemView* item = controller->GetSelectedMenuItem();
  if (!item) {
    return "none";
  }
  std::vector<views::View*> todo(item->children().begin(),
                                 item->children().end());
  while (!todo.empty()) {
    views::View* view = todo.back();
    todo.pop_back();
    views::Button* button = views::Button::AsButton(view);
    if (button && button->IsHotTracked()) {
      return base::UTF16ToUTF8(button->GetViewAccessibility().GetCachedName());
    }
    todo.insert(todo.end(), view->children().begin(), view->children().end());
  }
  return base::UTF16ToUTF8(item->title());
}

// Test hook for tools/smoke_app_menu.py, with --boring-open-app-menu=keys
// (the switch app-menu-test-hook.patch opens the menu with): key events go
// to the open menu inside the browser, nothing to the desktop, and what is
// selected after each lands in boring-app-menu-keys.txt in the user data
// folder. Enter, last, presses the selected button.
void WalkKeysForTest() {
  // Down into the tiles, across and back, down the whole menu, End to the
  // bar, across it, up the menu, Home, down past Browse and back up, End,
  // Left to Settings. tools/smoke_app_menu.py (KEYS) reads the same list.
  constexpr char kKeys[] =
      "DRRLDDDDDDDDDDDDDDDDDDDDXLRLUUUUUUUUUUUUUUHDDDUXLE";
  views::MenuController* active = views::MenuController::GetActiveInstance();
  base::WeakPtr<views::MenuController> controller;
  if (active) {
    controller = active->AsWeakPtr();
  }
  std::string report;
  for (const char key : std::string_view(kKeys)) {
    if (!controller) {
      report += "no menu\n";
      break;
    }
    const ui::KeyboardCode code =
        key == 'D'   ? ui::VKEY_DOWN
        : key == 'U' ? ui::VKEY_UP
        : key == 'L' ? ui::VKEY_LEFT
        : key == 'R' ? ui::VKEY_RIGHT
        : key == 'X' ? ui::VKEY_END
        : key == 'H' ? ui::VKEY_HOME
                     : ui::VKEY_RETURN;
    ui::KeyEvent event(ui::EventType::kKeyPressed, code, ui::EF_NONE);
    controller->OnWillDispatchKeyEvent(&event);
    report += key == 'E' ? std::string("E pressed\n")
                         : base::StrCat({std::string(1, key), " ",
                                         SelectedForTest(controller.get()),
                                         "\n"});
  }
  base::ThreadPool::PostTask(
      FROM_HERE, {base::MayBlock()},
      base::BindOnce(
          [](const base::FilePath& path, const std::string& text) {
            base::WriteFile(path, text);
          },
          base::CommandLine::ForCurrentProcess()
              ->GetSwitchValuePath("user-data-dir")
              .AppendASCII("boring-app-menu-keys.txt"),
          std::move(report)));
}

}  // namespace

void AddAppMenuButtonRow(views::MenuItemView* item,
                         ui::ButtonMenuItemModel* model,
                         AppMenuPress press,
                         bool bar) {
  // No title, one child: the item becomes a plain container for the row.
  item->SetTitle(std::u16string());
  item->set_vertical_margin(0);
  item->set_children_use_full_width(true);
  auto row = std::make_unique<ButtonRow>(item, model, press, bar);
  row->SetProperty(views::kMarginsKey,
                   bar ? gfx::Insets::TLBR(kBarAbove, kMenuPadding,
                                           ExtraEdge(), kMenuPadding)
                       : gfx::Insets::TLBR(ExtraEdge(), kMenuPadding,
                                           kTileBelow, kMenuPadding));
  item->AddChildView(std::move(row));
}

void StyleAppMenu(views::MenuItemView* root) {
  views::SubmenuView* submenu = root->GetSubmenu();
  if (!submenu) {
    return;
  }
  // The compiled design's menu is 320 wide; this overrides menu-width.patch's
  // 360, set just before this is called.
  submenu->set_minimum_preferred_width(kMenuWidth);
  // A card is a run of rows. A separator, a heading, the tile row, the bar
  // or a row that paints its own background (the update row) ends it.
  std::vector<views::MenuItemView*> card;
  for (views::View* child : submenu->children()) {
    auto* item = views::AsViewClass<views::MenuItemView>(child);
    if (!item) {
      PaintCard(card);
      card.clear();
      continue;
    }
    if (!item->GetVisible()) {
      continue;
    }
    if (item->GetType() == views::MenuItemView::Type::kTitle) {
      PaintCard(card);
      card.clear();
      // Its own id gives it the heading font and colour (AppMenu::
      // GetLabelFontList); titles in submenus keep their look.
      item->SetCommand(kAppMenuHeadingId);
      // Read out as a heading, not as a menu item that does nothing, and
      // never a stop for the selection (MenuItemView::
      // IsTraversableByKeyboard), also with a screen reader on.
      item->GetViewAccessibility().SetRole(ax::mojom::Role::kHeading);
      item->SetBorder(views::CreateEmptyBorder(
          gfx::Insets::TLBR(0, kHeadingIndent, 0, 0)));
      item->set_top_margin(kHeadingAbove);
      item->set_bottom_margin(kHeadingBelow);
      continue;
    }
    const int command_id = item->GetCommand();
    if (command_id == IDC_BORING_FORGET_SESSION) {
      // The compiled design's eraser, in place of the model's bin.
      item->SetIcon(ui::ImageModel::FromVectorIcon(
          kBoringEraseIcon, ui::kColorMenuIcon, kRowIconSize));
    }
    if (command_id == IDC_BORING_APP_MENU_TILES ||
        command_id == IDC_BORING_APP_MENU_BAR ||
        item->GetMenuItemBackground().has_value()) {
      PaintCard(card);
      card.clear();
      continue;
    }
    card.push_back(item);
  }
  PaintCard(card);

  // The keyboard test hook, once per process (see WalkKeysForTest).
  static bool keys_posted = false;
  if (!keys_posted && base::CommandLine::ForCurrentProcess()->GetSwitchValueASCII(
                          "boring-open-app-menu") == "keys") {
    keys_posted = true;
    base::SingleThreadTaskRunner::GetCurrentDefault()->PostDelayedTask(
        FROM_HERE, base::BindOnce(&WalkKeysForTest), base::Milliseconds(600));
  }
}

const gfx::FontList& AppMenuHeadingFont() {
  static const base::NoDestructor<gfx::FontList> font([] {
    const gfx::FontList& menu_font = views::MenuConfig::instance().font_list;
    return menu_font.Derive(
        ScaledFontSize(kHeadingFontSize) - menu_font.GetFontSize(),
        gfx::Font::NORMAL, gfx::Font::Weight::SEMIBOLD);
  }());
  return *font;
}

}  // namespace boring
