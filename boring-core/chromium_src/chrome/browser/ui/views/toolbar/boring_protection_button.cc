// Copyright 2026 boring. BSD style license.

#include "chrome/browser/ui/views/toolbar/boring_protection_button.h"

#include "base/functional/bind.h"
#include "base/time/time.h"
#include "chrome/app/chrome_command_ids.h"
#include "chrome/browser/ui/browser_commands.h"
#include "components/boring/adblock/adblock_service.h"
#include "components/boring/scam/scam_service.h"
#include "components/vector_icons/vector_icons.h"
#include "ui/base/metadata/metadata_impl_macros.h"
#include "ui/color/color_id.h"
#include "ui/views/accessibility/view_accessibility.h"

namespace {

// How long to wait before asking the services again while a list is
// still loading. Neither service has anything to subscribe to, and the
// lists settle within a second or two of startup, so a short look is
// enough and it stops as soon as there is an answer.
constexpr base::TimeDelta kWhileLoading = base::Seconds(1);

}  // namespace

BoringProtectionButton::BoringProtectionButton(BrowserWindowInterface* browser)
    : ToolbarButton(base::BindRepeating(&BoringProtectionButton::OnPressed,
                                        base::Unretained(this))),
      browser_(browser) {
  SetVectorIcon(vector_icons::kShieldIcon);

  // Opening a window is a good moment to make sure the lists are loading,
  // the same as opening the Protection page, so what the shield says is
  // about the lists and not about timing.
  boring::ScamService::GetInstance()->EnsureLoading();
  boring::AdblockService::GetInstance()->EnsureLoading();

  UpdateState();
}

BoringProtectionButton::~BoringProtectionButton() = default;

void BoringProtectionButton::OnThemeChanged() {
  ToolbarButton::OnThemeChanged();
  // The "Needs attention" label carries a colour, so it has to be set
  // again once a new theme is in place.
  UpdateState();
}

BoringProtectionButton::State BoringProtectionButton::ReadState() const {
  const auto scam = boring::ScamService::GetInstance()->status();
  const auto ads = boring::AdblockService::GetInstance()->status();

  // A failure anywhere is the thing worth saying, so it wins over a list
  // that is still loading.
  if (scam == boring::ScamService::Status::kFailed ||
      ads == boring::AdblockService::Status::kFailed) {
    return State::kFailed;
  }
  if (scam == boring::ScamService::Status::kLoading ||
      ads == boring::AdblockService::Status::kLoading) {
    return State::kLoading;
  }
  return State::kWorking;
}

void BoringProtectionButton::UpdateState() {
  state_ = ReadState();

  if (state_ == State::kFailed) {
    // Say it on the toolbar rather than waiting to be asked. Coloured
    // text and a coloured shield, not a filled chip: this is a browser
    // that stays quiet, and a red pill in the toolbar is shouting.
    SetText(u"Needs attention");
    SetEnabledTextColors(ui::kColorAlertHighSeverity);
    if (const ui::ColorProvider* colors = GetColorProvider()) {
      const SkColor alert = colors->GetColor(ui::kColorAlertHighSeverity);
      UpdateIconsWithColors(vector_icons::kShieldIcon, alert, alert, alert,
                            alert);
    }
    SetTooltipText(u"Something is not being blocked. Open Protection.");
    GetViewAccessibility().SetName(u"Protection, needs attention");
  } else {
    SetText(std::u16string());
    SetEnabledTextColors(std::nullopt);
    SetVectorIcon(vector_icons::kShieldIcon);
    if (state_ == State::kWorking) {
      SetTooltipText(u"Protection is on. Scam sites and ads are blocked.");
      GetViewAccessibility().SetName(u"Protection, on");
    } else {
      SetTooltipText(u"Protection is starting up.");
      GetViewAccessibility().SetName(u"Protection, starting up");
    }
  }

  // Ask again only while there is nothing to report yet.
  if (state_ == State::kLoading) {
    while_loading_.Start(FROM_HERE, kWhileLoading,
                         base::BindOnce(&BoringProtectionButton::UpdateState,
                                        base::Unretained(this)));
  }
}

void BoringProtectionButton::OnPressed() {
  chrome::ExecuteCommand(browser_, IDC_BORING_PROTECTION);
}

BEGIN_METADATA(BoringProtectionButton)
END_METADATA
