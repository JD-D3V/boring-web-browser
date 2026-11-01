// Copyright 2026 boring. BSD style license.

#include "components/boring/scam/takeover/takeover_tab_helper.h"

#include <string>

#include "base/functional/bind.h"
#include "base/task/single_thread_task_runner.h"
#include "components/boring/scam/takeover/takeover_policy.h"
#include "content/public/browser/navigation_controller.h"
#include "content/public/browser/navigation_handle.h"
#include "content/public/browser/web_contents.h"
#include "ui/base/page_transition_types.h"
#include "ui/display/types/display_constants.h"
#include "url/gurl.h"

namespace boring {

namespace {

// Dialogs: the fourth inside ten seconds is not shown. Three inside ten
// seconds is a burst and counts as a signal.
constexpr base::TimeDelta kDialogWindow = base::Seconds(10);
constexpr size_t kDialogBurst = 3;
constexpr size_t kDialogSuppressAfter = 3;

// Same document history entries added by the page by itself.
constexpr base::TimeDelta kHistoryWindow = base::Seconds(5);
constexpr size_t kHistorySpam = 20;

// Leaving fullscreen and being put back in it by the page.
constexpr base::TimeDelta kReentryWindow = base::Seconds(30);
constexpr size_t kReentries = 2;

// Two signals trip it, but not two quiet ones: a game or a remote
// desktop in fullscreen locks the keyboard and plays sound. At least one
// has to be something no ordinary page does.
constexpr int kSignalsToTrip = 2;

void Prune(std::deque<base::TimeTicks>& times,
           base::TimeTicks now,
           base::TimeDelta window) {
  while (!times.empty() && now - times.front() > window) {
    times.pop_front();
  }
}

}  // namespace

WEB_CONTENTS_USER_DATA_KEY_IMPL(TakeoverTabHelper);

TakeoverTabHelper::TakeoverTabHelper(content::WebContents* web_contents)
    : content::WebContentsObserver(web_contents),
      content::WebContentsUserData<TakeoverTabHelper>(*web_contents) {}

TakeoverTabHelper::~TakeoverTabHelper() = default;

// static
bool TakeoverTabHelper::ShouldSuppressDialog(
    content::WebContents* web_contents) {
  TakeoverTabHelper* helper = FromWebContents(web_contents);
  return helper && IsStopTakeoversEnabled(web_contents) &&
         helper->CountDialog();
}

// static
bool TakeoverTabHelper::ShouldSkipBeforeUnload(
    content::WebContents* web_contents) {
  TakeoverTabHelper* helper = FromWebContents(web_contents);
  return helper && helper->skip_beforeunload_;
}

// static
bool TakeoverTabHelper::LooksLikeScam(content::WebContents* web_contents) {
  TakeoverTabHelper* helper = FromWebContents(web_contents);
  return helper && helper->looked_like_scam_;
}

// static
void TakeoverTabHelper::MarkLooksLikeScam(content::WebContents* web_contents) {
  if (TakeoverTabHelper* helper = FromWebContents(web_contents)) {
    helper->looked_like_scam_ = true;
  }
}

bool TakeoverTabHelper::CountDialog() {
  base::TimeTicks now = base::TimeTicks::Now();
  Prune(dialogs_, now, kDialogWindow);
  // Suppressed ones count too, so a loop keeps the burst alive.
  bool suppress = dialogs_.size() >= kDialogSuppressAfter;
  dialogs_.push_back(now);
  Evaluate();
  return suppress;
}

void TakeoverTabHelper::DidToggleFullscreenModeForTab(bool entered_fullscreen,
                                                      bool will_cause_resize) {
  base::TimeTicks now = base::TimeTicks::Now();
  if (entered_fullscreen) {
    fullscreen_seen_ = true;
    if (last_exit_ && now - *last_exit_ <= kReentryWindow) {
      reentries_.push_back(now);
    }
  } else {
    last_exit_ = now;
    video_fullscreen_ = false;
  }
  Evaluate();
}

void TakeoverTabHelper::MediaEffectivelyFullscreenChanged(bool is_fullscreen) {
  video_fullscreen_ = is_fullscreen;
}

void TakeoverTabHelper::MediaStartedPlaying(const MediaPlayerInfo& video_type,
                                            const content::MediaPlayerId& id) {
  if (video_type.has_video) {
    video_players_.insert(id);
  }
}

void TakeoverTabHelper::MediaStoppedPlaying(
    const MediaPlayerInfo& video_type,
    const content::MediaPlayerId& id,
    content::WebContentsObserver::MediaStoppedReason reason) {
  video_players_.erase(id);
}

void TakeoverTabHelper::OnAudioStateChanged(bool audible) {
  audio_without_video_ = audible && video_players_.empty();
  Evaluate();
}

void TakeoverTabHelper::KeyboardLockRequested() {
  keyboard_lock_ = true;
  Evaluate();
}

void TakeoverTabHelper::DidFinishNavigation(content::NavigationHandle* handle) {
  if (!handle->IsInPrimaryMainFrame() || !handle->HasCommitted()) {
    return;
  }
  if (handle->IsSameDocument()) {
    // A page adding history entries by itself, without a click.
    if (handle->IsRendererInitiated() && !handle->HasUserGesture()) {
      base::TimeTicks now = base::TimeTicks::Now();
      Prune(history_pushes_, now, kHistoryWindow);
      history_pushes_.push_back(now);
      Evaluate();
    }
    return;
  }
  const GURL& url = handle->GetURL();
  if (url.SchemeIs("chrome") && url.host() == kBoringTakeoverHost) {
    // The Get me out page is up and the old page is gone. Give the tab
    // its sound back for whatever comes next.
    web_contents()->SetAudioMuted(false);
    skip_beforeunload_ = false;
    return;
  }
  ResetForNewDocument();
}

void TakeoverTabHelper::ResetForNewDocument() {
  fullscreen_seen_ = web_contents()->IsFullscreen();
  video_fullscreen_ = false;
  keyboard_lock_ = false;
  audio_without_video_ = false;
  video_players_.clear();
  dialogs_.clear();
  history_pushes_.clear();
  reentries_.clear();
  last_exit_.reset();
  tripped_ = false;
  skip_beforeunload_ = false;
  fullscreen_block_.reset();
}

void TakeoverTabHelper::Evaluate() {
  if (tripped_ || !fullscreen_seen_ || video_fullscreen_ ||
      !IsStopTakeoversEnabled(web_contents())) {
    return;
  }
  base::TimeTicks now = base::TimeTicks::Now();
  Prune(dialogs_, now, kDialogWindow);
  Prune(history_pushes_, now, kHistoryWindow);
  Prune(reentries_, now, kReentryWindow);

  // Things no ordinary page does.
  int hostile = 0;
  hostile += dialogs_.size() >= kDialogBurst;
  hostile += history_pushes_.size() >= kHistorySpam;
  hostile += reentries_.size() >= kReentries;
  // Things a game or a remote desktop does too.
  int quiet = 0;
  quiet += keyboard_lock_;
  quiet += audio_without_video_;
  quiet += web_contents()->NeedToFireBeforeUnloadOrUnloadEvents();

  if (hostile >= 1 && hostile + quiet >= kSignalsToTrip) {
    Trip();
  }
}

void TakeoverTabHelper::Trip() {
  tripped_ = true;
  looked_like_scam_ = true;
  skip_beforeunload_ = true;
  web_contents()->SetAudioMuted(true);
  // Leaving fullscreen also lets go of the keyboard lock. Holding it off
  // stops the page putting the tab straight back while the screen loads.
  fullscreen_block_ =
      web_contents()->ForSecurityDropFullscreen(display::kInvalidDisplayId);
  // Not from inside the observer call that found it.
  base::SingleThreadTaskRunner::GetCurrentDefault()->PostTask(
      FROM_HERE, base::BindOnce(&TakeoverTabHelper::ShowGetMeOut,
                                weak_factory_.GetWeakPtr()));
}

void TakeoverTabHelper::ShowGetMeOut() {
  std::string site(web_contents()->GetLastCommittedURL().host());
  GURL page("chrome://" + std::string(kBoringTakeoverHost) + "/?site=" + site);
  content::NavigationController::LoadURLParams params(page);
  params.transition_type = ui::PAGE_TRANSITION_AUTO_TOPLEVEL;
  // The scam page must not stay in the Back list.
  params.should_replace_current_entry = true;
  web_contents()->GetController().LoadURLWithParams(params);
}

}  // namespace boring
