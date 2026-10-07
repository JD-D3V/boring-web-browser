// Copyright 2026 boring. BSD style license.

#ifndef COMPONENTS_BORING_ASSISTANCE_ASSISTANCE_SESSION_H_
#define COMPONENTS_BORING_ASSISTANCE_ASSISTANCE_SESSION_H_

#include <string>
#include <string_view>
#include <vector>

#include "base/functional/callback.h"
#include "base/memory/weak_ptr.h"
#include "base/time/time.h"
#include "base/timer/timer.h"
#include "content/public/browser/web_contents_observer.h"
#include "url/gurl.h"
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

// One chat website the panel can hand a question to.
struct AssistanceProvider {
  AssistanceProvider(std::u16string name,
                     GURL start_url,
                     std::string chat_path,
                     std::string_view adapter_script,
                     std::u16string history_note);
  AssistanceProvider(const AssistanceProvider&);
  AssistanceProvider& operator=(const AssistanceProvider&);
  ~AssistanceProvider();

  // Shown on the panel's button, as in "Ask Gemini with this page".
  std::u16string name;
  // Where the panel opens; its origin is the only one the prompt may enter.
  GURL start_url;
  // The prompt only goes into pages at this path or below it ("/" for any).
  std::string chat_path;
  // An expression evaluating to (document, location, origin) => adapter,
  // with the interface gemini_adapter.js has.
  std::string_view adapter_script;
  // One line shown before anything is shared: what the site keeps.
  std::u16string history_note;
};

// Gemini's own website. `start_url` is https://gemini.google.com/app, or
// the local fake under the test switch.
AssistanceProvider GeminiProvider(const GURL& start_url);

// One question about one tab, answered by a chat site in the panel beside
// it, or found locally among the page's own buttons and links.
//
// Nothing leaves the machine before Share(). Prepare() reads the page in
// the tab's isolated world and builds the prompt there, so the panel can
// show exactly what would go out. Share() puts that prompt into the chat
// site's own composer and, unless `press_send`, leaves Send to the person.
// The reply is read back only to offer Show me, which outlines one control
// the page itself listed and never clicks it. Find() never involves the
// chat site at all.
class AssistanceSession : public content::WebContentsObserver {
 public:
  enum class State {
    kIdle,             // Nothing read yet.
    kCapturing,        // Reading the page.
    kReady,            // Prompt built; nothing shared.
    kWaitingForSend,   // Prompt is in the chat box; the person sends it.
    kWaitingForReply,  // Sent; the chat site is answering.
    kAnswered,         // Reply read; CanShowMe() says if it named a control.
    kFound,            // Find() finished; match_labels() has the results.
    kStale,            // The page changed after it was read.
    kFailed,           // reason() says why.
  };

  // `source` is the tab being asked about and `chat` the panel's page.
  AssistanceSession(content::WebContents* source,
                    content::WebContents* chat,
                    const AssistanceProvider& provider,
                    bool press_send,
                    base::RepeatingClosure on_changed);
  AssistanceSession(const AssistanceSession&) = delete;
  AssistanceSession& operator=(const AssistanceSession&) = delete;
  ~AssistanceSession() override;

  // Starts a new round and stops at kReady, for the preview. Any earlier
  // answer, and its Show me, is dropped.
  void Prepare(std::u16string_view question);
  // Prepare(), then Share() as soon as the prompt is built: the one press
  // of "Ask Gemini with this page".
  void Ask(std::u16string_view question);
  // Only from kReady.
  void Share();
  // Only while CanShowMe().
  void ShowMe();

  // Searches the page's own buttons and links for `query` on this machine.
  void Find(std::u16string_view query);
  // Outlines match `index` of the last Find(), while state() is kFound.
  void ShowMatch(size_t index);

  State state() const { return state_; }
  // A short machine reason, such as "signed_out" or "slow". Empty when
  // there is nothing to say.
  const std::string& reason() const { return reason_; }
  // The exact text Share() would put into the chat site, for the preview.
  const std::string& prompt() const { return prompt_; }
  bool CanShowMe() const;
  // Labels of what Find() matched, best first.
  const std::vector<std::string>& match_labels() const { return match_labels_; }

  // content::WebContentsObserver, for the source tab:
  void PrimaryPageChanged(content::Page& page) override;
  void DidFinishNavigation(content::NavigationHandle* navigation) override;
  void WebContentsDestroyed() override;

 private:
  using ResultCallback = base::OnceCallback<void(base::Value)>;

  // Checks the page and `text`, starts a new request id, and moves to
  // kCapturing. False, with the state set to kFailed, when it cannot.
  bool StartRequest(std::u16string_view text, size_t max_bytes);
  void StartCapture(std::u16string_view question, bool then_share);
  void RunInSource(const std::string& script, ResultCallback callback);
  void RunInChat(const std::string& script, ResultCallback callback);
  bool ChatIsProvider() const;

  void OnCaptured(base::Value result);
  void OnShared(base::Value result);
  void Poll();
  void OnPolled(base::Value result);
  void OnParsed(base::Value result);
  void Highlight(const std::string& candidate);
  void OnHighlighted(base::Value result);
  void OnFound(base::Value result);

  // Drops in-flight work, Show me and matches, then moves to `state`.
  void Stop(State state, std::string reason);
  void SetState(State state, std::string reason);

  base::WeakPtr<content::WebContents> chat_;
  const AssistanceProvider provider_;
  const url::Origin provider_origin_;
  const bool press_send_;
  base::RepeatingClosure on_changed_;

  State state_ = State::kIdle;
  std::string reason_;
  std::string request_id_;
  int revision_ = 0;
  std::string prompt_;
  std::string candidate_;
  std::vector<std::string> match_ids_;
  std::vector<std::string> match_labels_;
  bool share_when_ready_ = false;
  base::TimeTicks sent_at_;
  base::RepeatingTimer poll_timer_;

  base::WeakPtrFactory<AssistanceSession> weak_factory_{this};
};

}  // namespace boring

#endif  // COMPONENTS_BORING_ASSISTANCE_ASSISTANCE_SESSION_H_
