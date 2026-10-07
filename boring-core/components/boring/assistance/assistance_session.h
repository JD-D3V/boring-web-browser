// Copyright 2026 boring. BSD style license.

#ifndef COMPONENTS_BORING_ASSISTANCE_ASSISTANCE_SESSION_H_
#define COMPONENTS_BORING_ASSISTANCE_ASSISTANCE_SESSION_H_

#include <string>

#include "base/functional/callback.h"
#include "base/memory/weak_ptr.h"
#include "base/time/time.h"
#include "base/timer/timer.h"
#include "content/public/browser/web_contents_observer.h"
#include "url/origin.h"

namespace base {
class Value;
}

namespace content {
class NavigationHandle;
class Page;
class WebContents;
}  // namespace content

namespace boring {

// One question about one tab, answered by Gemini in the panel beside it.
//
// Nothing leaves the machine before Share(). Prepare() reads the page in
// the tab's isolated world and builds the prompt there, so the panel can
// show exactly what would go out. Share() puts that prompt into Gemini's
// own composer and, unless `press_send`, leaves Send to the person. The
// reply is read back only to offer Show me, which outlines one control
// the page itself listed and never clicks it.
class AssistanceSession : public content::WebContentsObserver {
 public:
  enum class State {
    kIdle,             // Nothing read yet.
    kCapturing,        // Reading the page.
    kReady,            // Prompt built; nothing shared.
    kWaitingForSend,   // Prompt is in Gemini's box; the person sends it.
    kWaitingForReply,  // Sent; Gemini is answering.
    kAnswered,         // Reply read; CanShowMe() says if it named a control.
    kStale,            // The page changed after it was read.
    kFailed,           // reason() says why.
  };

  // `source` is the tab being asked about and `gemini` the panel's page.
  // The prompt is only ever put into a document of `provider`.
  AssistanceSession(content::WebContents* source,
                    content::WebContents* gemini,
                    const url::Origin& provider,
                    bool press_send,
                    base::RepeatingClosure on_changed);
  AssistanceSession(const AssistanceSession&) = delete;
  AssistanceSession& operator=(const AssistanceSession&) = delete;
  ~AssistanceSession() override;

  // Starts a new round and stops at kReady, for the preview. Any earlier
  // answer, and its Show me, is dropped.
  void Prepare(const std::u16string& question);
  // Prepare(), then Share() as soon as the prompt is built: the one press
  // of "Ask Gemini with this page".
  void Ask(const std::u16string& question);
  // Only from kReady.
  void Share();
  // Only while CanShowMe().
  void ShowMe();

  State state() const { return state_; }
  // A short machine reason, such as "signed_out" or "slow". Empty when
  // there is nothing to say.
  const std::string& reason() const { return reason_; }
  // The exact text Share() would put into Gemini, for the preview.
  const std::string& prompt() const { return prompt_; }
  bool CanShowMe() const;

  // content::WebContentsObserver, for the source tab:
  void PrimaryPageChanged(content::Page& page) override;
  void DidFinishNavigation(content::NavigationHandle* navigation) override;
  void WebContentsDestroyed() override;

 private:
  using ResultCallback = base::OnceCallback<void(base::Value)>;

  void StartCapture(const std::u16string& question, bool then_share);
  void RunInSource(const std::string& script, ResultCallback callback);
  void RunInGemini(const std::string& script, ResultCallback callback);
  bool GeminiIsProvider() const;

  void OnCaptured(base::Value result);
  void OnShared(base::Value result);
  void Poll();
  void OnPolled(base::Value result);
  void OnParsed(base::Value result);
  void OnHighlighted(base::Value result);

  // Drops in-flight work and any Show me, then moves to `state`.
  void Stop(State state, std::string reason);
  void SetState(State state, std::string reason);

  base::WeakPtr<content::WebContents> gemini_;
  const url::Origin provider_;
  const bool press_send_;
  base::RepeatingClosure on_changed_;

  State state_ = State::kIdle;
  std::string reason_;
  std::string request_id_;
  int revision_ = 0;
  std::string prompt_;
  std::string candidate_;
  bool share_when_ready_ = false;
  base::TimeTicks sent_at_;
  base::RepeatingTimer poll_timer_;

  base::WeakPtrFactory<AssistanceSession> weak_factory_{this};
};

}  // namespace boring

#endif  // COMPONENTS_BORING_ASSISTANCE_ASSISTANCE_SESSION_H_
