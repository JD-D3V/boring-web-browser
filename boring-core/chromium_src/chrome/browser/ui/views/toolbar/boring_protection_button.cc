// Copyright 2026 boring. BSD style license.

#include "chrome/browser/ui/views/toolbar/boring_protection_button.h"

#include <memory>

#include "base/functional/bind.h"
#include "base/strings/utf_string_conversions.h"
#include "base/time/time.h"
#include "cc/paint/paint_flags.h"
#include "chrome/app/chrome_command_ids.h"
#include "chrome/browser/profiles/profile.h"
#include "chrome/browser/ui/browser_commands.h"
#include "chrome/browser/ui/browser_window/public/browser_window_interface.h"
#include "chrome/browser/ui/color/chrome_color_id.h"
#include "components/boring/adblock/adblock_service.h"
#include "components/boring/adblock/blocking_off_sites.h"
#include "components/boring/core/boring_capabilities.h"
#include "components/boring/core/boring_prefs.h"
#include "components/boring/scam/scam_service.h"
#include "components/prefs/pref_service.h"
#include "components/tabs/public/tab_interface.h"
#include "content/public/browser/navigation_controller.h"
#include "content/public/browser/reload_type.h"
#include "content/public/browser/web_contents.h"
#include "ui/accessibility/ax_enums.mojom.h"
#include "ui/base/menu_source_utils.h"
#include "ui/base/metadata/metadata_impl_macros.h"
#include "ui/base/models/image_model.h"
#include "ui/base/models/menu_separator_types.h"
#include "ui/color/color_id.h"
#include "ui/color/color_provider.h"
#include "ui/gfx/canvas.h"
#include "ui/gfx/font_list.h"
#include "ui/gfx/geometry/insets.h"
#include "ui/gfx/geometry/point_f.h"
#include "ui/gfx/image/canvas_image_source.h"
#include "ui/gfx/image/image_skia.h"
#include "ui/views/accessibility/view_accessibility.h"
#include "ui/views/controls/button/button.h"
#include "ui/views/controls/label.h"

namespace {

// How long to wait before asking the services again while a list is
// still loading. Neither service has anything to subscribe to, and the
// lists settle within a second or two of startup, so a short look is
// enough and it stops as soon as there is an answer.
constexpr base::TimeDelta kWhileLoading = base::Seconds(1);

// Commands in the shield's menu.
enum MenuCommand {
  kToggleSite = 1,
  kOpenProtection,
};

// Diameter, in DIP, of the status dot painted before the label. Small on
// purpose, the word does the talking and the dot is just a glance-check.
constexpr int kDotDiameter = 7;

// Paints a single filled circle in one colour. This is a real image rather
// than a text bullet, so it scales with the DIP scale factor and can be
// redrawn in whatever colour the current state and theme call for.
class DotImageSource : public gfx::CanvasImageSource {
 public:
  explicit DotImageSource(SkColor color)
      : gfx::CanvasImageSource(gfx::Size(kDotDiameter, kDotDiameter)),
        color_(color) {}

  DotImageSource(const DotImageSource&) = delete;
  DotImageSource& operator=(const DotImageSource&) = delete;

  ~DotImageSource() override = default;

  // gfx::CanvasImageSource:
  void Draw(gfx::Canvas* canvas) override {
    cc::PaintFlags flags;
    flags.setStyle(cc::PaintFlags::kFill_Style);
    flags.setColor(color_);
    flags.setAntiAlias(true);
    const float radius = kDotDiameter / 2.0f;
    canvas->DrawCircle(gfx::PointF(radius, radius), radius, flags);
  }

 private:
  const SkColor color_;
};

ui::ImageModel MakeDotImageModel(SkColor color) {
  return ui::ImageModel::FromImageSkia(
      gfx::CanvasImageSource::MakeImageSkia<DotImageSource>(color));
}

}  // namespace

BoringProtectionButton::BoringProtectionButton(BrowserWindowInterface* browser)
    : ToolbarButton(base::BindRepeating(&BoringProtectionButton::OnPressed,
                                        base::Unretained(this)),
                    std::make_unique<ui::SimpleMenuModel>(this),
                    /*tab_strip_model=*/nullptr,
                    /*trigger_menu_on_long_press=*/false),
      browser_(browser) {
  // The dot and the label are painted below, by UpdateState().

  // Opening a window is a good moment to make sure the lists are loading,
  // the same as opening the Protection page, so what the shield says is
  // about the lists and not about timing.
  // Only the services this build actually has. Starting the scam
  // service on a build that ships no list would log a missing-list
  // error at every window and leave it reporting a failure that is not
  // one.
  if (boring::kScamBlockingAvailable) {
    boring::ScamService::GetInstance()->EnsureLoading();
  }
  boring::AdblockService::GetInstance()->EnsureLoading();

  // What the shield says depends on the tab's site too, so follow the
  // active tab, and the list of sites wherever it is changed from.
  tab_changed_ = browser_->RegisterActiveTabDidChange(base::BindRepeating(
      [](BoringProtectionButton* self, BrowserWindowInterface*) {
        self->FollowActiveTab();
      },
      base::Unretained(this)));
  pref_change_registrar_.Init(browser_->GetProfile()->GetPrefs());
  pref_change_registrar_.Add(
      boring::prefs::kBlockingOffSites,
      base::BindRepeating(&BoringProtectionButton::UpdateState,
                          base::Unretained(this)));
  FollowActiveTab();

  // boring: the reference's Protection control is 10 DIP of horizontal
  // padding around the dot and the word, 7 DIP between them, and 12px
  // text, not a generic toolbar button's sizing. Comes after
  // UpdateState() because SetLabelSideSpacing() only adds space when
  // there is already text to space away from, and this button always
  // has some (see ReadState(): every branch leaves a non-empty label).
  SetLayoutInsets(gfx::Insets::VH(0, 10));
  SetLabelSideSpacing(7);
  const gfx::FontList& current_font = label()->font_list();
  label()->SetFontList(
      current_font.DeriveWithSizeDelta(12 - current_font.GetFontSize()));
}

BoringProtectionButton::~BoringProtectionButton() = default;

void BoringProtectionButton::OnThemeChanged() {
  ToolbarButton::OnThemeChanged();
  // The dot and the label both carry a colour, so both have to be
  // repainted once a new theme is in place.
  UpdateState();
}

void BoringProtectionButton::FollowActiveTab() {
  tabs::TabInterface* active = browser_->GetActiveTabInterface();
  Observe(active ? active->GetContents() : nullptr);
  UpdateState();
}

void BoringProtectionButton::PrimaryPageChanged(content::Page& page) {
  UpdateState();
}

std::string BoringProtectionButton::CurrentSite() const {
  return web_contents()
             ? boring::GetBlockingSite(web_contents()->GetLastCommittedURL())
             : std::string();
}

bool BoringProtectionButton::IsOffHere() const {
  const std::string site = CurrentSite();
  return !site.empty() && browser_->GetProfile()
                              ->GetPrefs()
                              ->GetList(boring::prefs::kBlockingOffSites)
                              .contains(site);
}

BoringProtectionButton::State BoringProtectionButton::ReadState() const {
  // Turned off for this run (a test switch): nothing is blocked, so the
  // shield must not say it is.
  if (boring::AdblockService::IsDisabled()) {
    return State::kFailed;
  }
  const auto ads = boring::AdblockService::GetInstance()->status();

  // The shield speaks for the protections this build has. Scam blocking
  // is not one of them in this version, and a service with no list to
  // load reports a failure for a reason that is not a fault, so asking
  // it would put a red shield on a browser that is working exactly as
  // intended. The Protection page is where the absence is stated; see
  // components/boring/core/boring_capabilities.h.
  if (boring::kScamBlockingAvailable) {
    const auto scam = boring::ScamService::GetInstance()->status();
    // A failure anywhere is the thing worth saying, so it wins over a
    // list that is still loading.
    if (scam == boring::ScamService::Status::kFailed) {
      return State::kFailed;
    }
    if (scam == boring::ScamService::Status::kLoading) {
      return State::kLoading;
    }
  }
  if (ads == boring::AdblockService::Status::kFailed) {
    return State::kFailed;
  }
  // A choice the person made for this site is settled, so it is worth
  // saying even while the lists are still loading.
  if (IsOffHere()) {
    return State::kOffHere;
  }
  if (ads == boring::AdblockService::Status::kLoading) {
    return State::kLoading;
  }
  return State::kWorking;
}

void BoringProtectionButton::UpdateState() {
  state_ = ReadState();

  // The label always spells out which state this is, not just the
  // colour, so a forced-colours or high-contrast theme still tells the
  // states apart once the accent and the muted colour collapse together.
  ui::ColorId color_id = ui::kColorSysPrimary;
  std::u16string label = u"Protection";
  std::u16string accessible_name;

  if (state_ == State::kFailed) {
    // Say it on the toolbar rather than waiting to be asked. Coloured
    // text and a coloured dot, not a filled chip: this is a browser that
    // stays quiet, and a red pill in the toolbar is shouting.
    color_id = ui::kColorAlertHighSeverity;
    label = u"Needs attention";
    SetTooltipText(u"Something is not being blocked. Open Protection.");
    accessible_name = u"Protection, needs attention";
  } else if (state_ == State::kOffHere) {
    const std::u16string site = base::UTF8ToUTF16(CurrentSite());
    color_id = kColorToolbarButtonIconInactive;
    label = u"Blocking off";
    SetTooltipText(u"Ads and trackers are not blocked on " + site + u".");
    accessible_name = u"Protection, blocking off for " + site;
  } else if (state_ == State::kWorking) {
    SetTooltipText(u"Protection is on. Scam sites and ads are blocked.");
    accessible_name = u"Protection, on";
  } else {
    color_id = kColorToolbarButtonIconInactive;
    SetTooltipText(u"Protection is starting up.");
    accessible_name = u"Protection, starting up";
  }

  SetText(label);
  // After SetText(), which sets the accessible name to the label: the
  // label alone ("Protection") would not tell a screen reader the state.
  GetViewAccessibility().SetName(accessible_name);
  SetEnabledTextColors(color_id);
  // The dot bakes in a concrete colour, so it needs an actual provider to
  // resolve one. There is none yet the first time this runs, before the
  // button is in a Widget; OnThemeChanged() calls back in once there is.
  if (const ui::ColorProvider* colors = GetColorProvider()) {
    SetImageModel(views::Button::STATE_NORMAL,
                  MakeDotImageModel(colors->GetColor(color_id)));
  }

  // Ask again only while there is nothing to report yet.
  if (state_ == State::kLoading) {
    while_loading_.Start(FROM_HERE, kWhileLoading,
                         base::BindOnce(&BoringProtectionButton::UpdateState,
                                        base::Unretained(this)));
  }

  // On a web page the shield opens a menu, and says so to a screen
  // reader; anywhere else it opens the Protection page directly.
  GetViewAccessibility().SetHasPopup(CurrentSite().empty()
                                         ? ax::mojom::HasPopup::kFalse
                                         : ax::mojom::HasPopup::kMenu);
}

ui::SimpleMenuModel* BoringProtectionButton::site_menu() {
  return static_cast<ui::SimpleMenuModel*>(menu_model());
}

void BoringProtectionButton::OnPressed(const ui::Event& event) {
  ShowDropDownMenu(ui::GetMenuSourceTypeForEvent(event));
}

void BoringProtectionButton::ShowDropDownMenu(
    ui::mojom::MenuSourceType source_type) {
  if (IsMenuShowing()) {
    return;
  }
  menu_site_ = CurrentSite();
  if (menu_site_.empty()) {
    chrome::ExecuteCommand(browser_, IDC_BORING_PROTECTION);
    return;
  }
  const std::u16string site = base::UTF8ToUTF16(menu_site_);
  const bool off = IsOffHere();
  ui::SimpleMenuModel* menu = site_menu();
  menu->Clear();
  menu->AddTitle(off ? u"Blocking is off on " + site
                     : u"Blocking is on for " + site);
  menu->AddItem(kToggleSite, off ? u"Turn blocking back on"
                                 : u"Turn off blocking on this site");
  menu->AddSeparator(ui::NORMAL_SEPARATOR);
  menu->AddItem(kOpenProtection, u"Open Protection");
  ShowMenuForModel(source_type, menu);
}

void BoringProtectionButton::ExecuteCommand(int command_id, int event_flags) {
  if (command_id == kOpenProtection) {
    chrome::ExecuteCommand(browser_, IDC_BORING_PROTECTION);
    return;
  }
  if (command_id != kToggleSite || menu_site_.empty()) {
    return;
  }
  Profile* profile = browser_->GetProfile();
  PrefService* prefs = profile->GetPrefs();
  const bool off =
      prefs->GetList(boring::prefs::kBlockingOffSites).contains(menu_site_);
  boring::SetBlockingOffForSite(prefs, menu_site_, !off);
  // Bring the copy the renderer checks read up to date now, rather than
  // at the reload's first request.
  boring::BlockingOffSites::ForContext(profile);
  // What was blocked, or is now to be blocked, only changes with a fresh
  // load, so reload the page the choice was made on.
  if (web_contents() && CurrentSite() == menu_site_) {
    web_contents()->GetController().Reload(content::ReloadType::NORMAL,
                                           /*check_for_repost=*/true);
  }
}

BEGIN_METADATA(BoringProtectionButton)
END_METADATA
