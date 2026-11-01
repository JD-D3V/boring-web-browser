// Copyright 2026 boring. BSD style license.

#include "components/boring/scam/phone/phone_scam_tab_helper.h"

#include <optional>
#include <string>

#include "base/functional/bind.h"
#include "base/functional/callback_helpers.h"
#include "base/strings/strcat.h"
#include "base/strings/utf_string_conversions.h"
#include "base/task/single_thread_task_runner.h"
#include "base/time/time.h"
#include "components/boring/guards/guard_infobar.h"
#include "components/boring/guards/guards_policy.h"
#include "components/boring/scam/phone/phone_scam_scripts.h"
#include "components/boring/scam/takeover/takeover_tab_helper.h"
#include "content/public/browser/navigation_handle.h"
#include "content/public/browser/render_frame_host.h"
#include "content/public/browser/web_contents.h"
#include "content/public/common/isolated_world_ids.h"
#include "ui/display/types/display_constants.h"
#include "url/gurl.h"

namespace boring {

namespace {

// Our script runs in an isolated world, away from the page's own
// scripts. ISOLATED_WORLD_ID_CHROME_INTERNAL, worked out the same way and
// for the same reason as in serp_tab_helper.cc: this component sits below
// chrome/.
constexpr int32_t kBoringWorldId = content::ISOLATED_WORLD_ID_CONTENT_END + 3;

// Pop-ups often appear a moment after the page loads, so the page is read
// once more later. Two looks, no more.
constexpr base::TimeDelta kSecondLook = base::Seconds(3);

constexpr char16_t kNotice[] =
    u"Real companies do not put phone numbers in pop-up warnings.";

// The detector is a file that evaluates to an object. It is called inside
// a function, so nothing it makes is left in the isolated world.
std::string BuildScript(bool tab_suspicious) {
  return base::StrCat({"(function() {\nvar detector =\n", kPhoneScamDetectScript,
                       "\nreturn detector.scanDocument(document, window, ",
                       tab_suspicious ? "true" : "false", ");\n})()"});
}

}  // namespace

WEB_CONTENTS_USER_DATA_KEY_IMPL(PhoneScamTabHelper);

PhoneScamTabHelper::PhoneScamTabHelper(content::WebContents* web_contents)
    : content::WebContentsObserver(web_contents),
      content::WebContentsUserData<PhoneScamTabHelper>(*web_contents) {}

PhoneScamTabHelper::~PhoneScamTabHelper() = default;

void PhoneScamTabHelper::DidFinishNavigation(content::NavigationHandle* handle) {
  if (handle->IsInPrimaryMainFrame() && handle->HasCommitted() &&
      !handle->IsSameDocument()) {
    ++document_;
    warned_ = false;
  }
}

void PhoneScamTabHelper::DocumentOnLoadCompletedInPrimaryMainFrame() {
  Scan(document_);
  base::SingleThreadTaskRunner::GetCurrentDefault()->PostDelayedTask(
      FROM_HERE,
      base::BindOnce(&PhoneScamTabHelper::Scan, weak_factory_.GetWeakPtr(),
                     document_),
      kSecondLook);
}

void PhoneScamTabHelper::Scan(int document) {
  content::WebContents* contents = web_contents();
  content::RenderFrameHost* frame = contents->GetPrimaryMainFrame();
  if (document != document_ || warned_ || !frame->IsRenderFrameLive() ||
      !contents->GetLastCommittedURL().SchemeIsHTTPOrHTTPS() ||
      !guards::IsEnabled(contents->GetBrowserContext())) {
    return;
  }
  frame->ExecuteJavaScriptInIsolatedWorld(
      base::UTF8ToUTF16(
          BuildScript(TakeoverTabHelper::LooksLikeScam(contents))),
      base::BindOnce(&PhoneScamTabHelper::OnScanned,
                     weak_factory_.GetWeakPtr(), document),
      kBoringWorldId);
}

void PhoneScamTabHelper::OnScanned(int document, base::Value result) {
  if (document != document_ || warned_) {
    return;
  }
  const base::DictValue* dict = result.GetIfDict();
  if (dict && dict->FindBool("scary").value_or(false)) {
    Warn();
  }
}

void PhoneScamTabHelper::Warn() {
  warned_ = true;
  content::WebContents* contents = web_contents();
  // The same signal the takeover detector sets, so the guards for remote
  // access downloads and pasted commands use their strong wording.
  TakeoverTabHelper::MarkLooksLikeScam(contents);
  // The bar is part of the browser window, which a fullscreen page covers.
  // The block on going back in is let go when this leaves scope: this is a
  // one-time exit, as in the clipboard guard.
  std::optional<base::ScopedClosureRunner> drop;
  if (contents->IsFullscreen()) {
    drop = contents->ForSecurityDropFullscreen(display::kInvalidDisplayId);
  }
  guards::GuardInfoBarDelegate::Show(contents, {.message = kNotice},
                                     guards::GuardInfoBarDelegate::Answered());
}

}  // namespace boring
