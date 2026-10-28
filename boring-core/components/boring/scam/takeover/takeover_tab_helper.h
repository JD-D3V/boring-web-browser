// Copyright 2026 boring. BSD style license.

#ifndef COMPONENTS_BORING_SCAM_TAKEOVER_TAKEOVER_TAB_HELPER_H_
#define COMPONENTS_BORING_SCAM_TAKEOVER_TAKEOVER_TAB_HELPER_H_

#include <deque>
#include <optional>
#include <set>

#include "base/functional/callback_helpers.h"
#include "base/memory/weak_ptr.h"
#include "base/time/time.h"
#include "content/public/browser/media_player_id.h"
#include "content/public/browser/web_contents_observer.h"
#include "content/public/browser/web_contents_user_data.h"

namespace boring {

// The host name of the Get me out page: chrome://boring-takeover
inline constexpr char kBoringTakeoverHost[] = "boring-takeover";

// Watches one tab for the way tech support scam pages lock a browser,
// scores it, and when it looks like one, drops fullscreen, silences the
// tab and replaces the page with a browser-owned screen that closes the
// tab. Everything stays in this process: nothing is sent anywhere.
//
// Normal fullscreen is never blocked. A fullscreen video (the YouTube
// button) is exempt. See DESIGN.md next to this file.
class TakeoverTabHelper
    : public content::WebContentsObserver,
      public content::WebContentsUserData<TakeoverTabHelper> {
 public:
  ~TakeoverTabHelper() override;

  // For the JavaScript dialog manager: called for each alert, confirm
  // and prompt. Counts it, and returns true when the dialog must not be
  // shown because the page is looping them.
  static bool ShouldSuppressDialog(content::WebContents* web_contents);

  // For the beforeunload dialog: true while the tab is being replaced by
  // the Get me out page, so the page cannot hold the tab with a prompt.
  static bool ShouldSkipBeforeUnload(content::WebContents* web_contents);

  // content::WebContentsObserver:
  void DidToggleFullscreenModeForTab(bool entered_fullscreen,
                                     bool will_cause_resize) override;
  void MediaEffectivelyFullscreenChanged(bool is_fullscreen) override;
  void OnAudioStateChanged(bool audible) override;
  void MediaStartedPlaying(const MediaPlayerInfo& video_type,
                           const content::MediaPlayerId& id) override;
  void MediaStoppedPlaying(
      const MediaPlayerInfo& video_type,
      const content::MediaPlayerId& id,
      content::WebContentsObserver::MediaStoppedReason reason) override;
  void KeyboardLockRequested() override;
  void DidFinishNavigation(content::NavigationHandle* handle) override;

 private:
  friend class content::WebContentsUserData<TakeoverTabHelper>;

  explicit TakeoverTabHelper(content::WebContents* web_contents);

  bool CountDialog();
  void Evaluate();
  void Trip();
  void ShowGetMeOut();
  void ResetForNewDocument();

  // What this document has done so far.
  bool in_fullscreen_ = false;
  bool video_fullscreen_ = false;
  bool keyboard_lock_ = false;
  bool audio_without_video_ = false;
  std::set<content::MediaPlayerId> video_players_;
  std::deque<base::TimeTicks> dialogs_;
  std::deque<base::TimeTicks> history_pushes_;
  std::deque<base::TimeTicks> reentries_;
  std::optional<base::TimeTicks> last_exit_;

  // Set when it has tripped, until the Get me out page is on screen.
  bool tripped_ = false;
  bool skip_beforeunload_ = false;
  // Holds fullscreen off while the Get me out page is loading.
  std::optional<base::ScopedClosureRunner> fullscreen_block_;

  base::WeakPtrFactory<TakeoverTabHelper> weak_factory_{this};
  WEB_CONTENTS_USER_DATA_KEY_DECL();
};

}  // namespace boring

#endif  // COMPONENTS_BORING_SCAM_TAKEOVER_TAKEOVER_TAB_HELPER_H_
