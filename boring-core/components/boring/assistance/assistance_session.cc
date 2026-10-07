// Copyright 2026 boring. BSD style license.

#include "components/boring/assistance/assistance_session.h"

#include <array>
#include <cstdint>
#include <optional>
#include <string_view>
#include <utility>

#include "base/json/json_writer.h"
#include "base/rand_util.h"
#include "base/strings/strcat.h"
#include "base/strings/string_number_conversions.h"
#include "base/strings/string_util.h"
#include "base/strings/utf_string_conversions.h"
#include "base/values.h"
#include "components/boring/assistance/assistance_scripts.h"
#include "content/public/browser/browser_context.h"
#include "content/public/browser/navigation_handle.h"
#include "content/public/browser/render_frame_host.h"
#include "content/public/browser/web_contents.h"
#include "content/public/common/isolated_world_ids.h"
#include "url/gurl.h"

namespace boring {

namespace {

// ISOLATED_WORLD_ID_CHROME_INTERNAL, worked out the same way and for the
// same reason as in serp_tab_helper.cc: this component sits below chrome/.
constexpr int32_t kAssistanceWorldId =
    content::ISOLATED_WORLD_ID_CONTENT_END + 3;

// The same limit protocol.js enforces, checked here so an oversized
// question never reaches the page at all.
constexpr size_t kMaxQuestionBytes = 4096;
constexpr base::TimeDelta kPollInterval = base::Seconds(1);
// Spec: after a minute say it is taking longer, and never resend.
constexpr base::TimeDelta kSlowAfter = base::Seconds(60);

// Every value that goes into a script goes through JSON, never string
// pasting, so page text or a question cannot end the literal it sits in.
std::string Json(const base::Value& value) {
  return base::WriteJson(value).value_or("null");
}

std::string Json(std::string_view text) {
  return Json(base::Value(text));
}

// The scripts are expressions; installing them once per document keeps
// the page reader's revision counter and target map between calls.
std::string InstallPageScripts() {
  return base::StrCat({"globalThis.__boringAssistPage ??= (\n",
                       kAssistancePageScript, "\n);\n",
                       "globalThis.__boringAssistProtocol ??= (\n",
                       kAssistanceProtocolScript, "\n);\n"});
}

const std::string* FindReason(const base::DictValue& result) {
  return result.FindString("reason");
}

}  // namespace

AssistanceSession::AssistanceSession(content::WebContents* source,
                                     content::WebContents* gemini,
                                     const url::Origin& provider,
                                     bool press_send,
                                     base::RepeatingClosure on_changed)
    : content::WebContentsObserver(source),
      gemini_(gemini->GetWeakPtr()),
      provider_(provider),
      press_send_(press_send),
      on_changed_(std::move(on_changed)) {}

AssistanceSession::~AssistanceSession() {
  // Spec: closing the session destroys its snapshot and target map. What
  // already went to Google stays there; this only clears our side.
  if (web_contents()) {
    RunInSource(
        "globalThis.__boringAssistPage?.dispose();"
        "delete globalThis.__boringAssistSnapshot; true",
        base::NullCallback());
  }
  if (gemini_) {
    RunInGemini(
        "globalThis.__boringAssistGemini?.dispose();"
        "delete globalThis.__boringAssistGemini; true",
        base::NullCallback());
  }
}

void AssistanceSession::Prepare(const std::u16string& question) {
  StartCapture(question, /*then_share=*/false);
}

void AssistanceSession::Ask(const std::u16string& question) {
  StartCapture(question, /*then_share=*/true);
}

void AssistanceSession::StartCapture(const std::u16string& question,
                                     bool then_share) {
  if (state_ == State::kCapturing) {
    return;
  }
  Stop(State::kIdle, std::string());
  prompt_.clear();
  share_when_ready_ = then_share;

  content::WebContents* source = web_contents();
  if (!source || source->GetBrowserContext()->IsOffTheRecord() ||
      !source->GetLastCommittedURL().SchemeIsHTTPOrHTTPS()) {
    SetState(State::kFailed, "unsupported_page");
    return;
  }
  const std::string text =
      base::UTF16ToUTF8(base::TrimWhitespace(question, base::TRIM_ALL));
  if (text.empty()) {
    SetState(State::kFailed, "empty_question");
    return;
  }
  if (text.size() > kMaxQuestionBytes) {
    SetState(State::kFailed, "question_too_long");
    return;
  }

  std::array<uint8_t, 8> bytes;
  base::RandBytes(bytes);
  request_id_ = base::HexEncode(bytes);
  SetState(State::kCapturing, std::string());

  // The snapshot stays in the isolated world; only the prompt comes back.
  // A navigation destroys the world, and with it any later Show me.
  RunInSource(
      base::StrCat(
          {InstallPageScripts(),
           "(() => {\n"
           "  try {\n"
           "    const snapshot = globalThis.__boringAssistPage.capture(",
           Json(request_id_),
           ");\n"
           "    globalThis.__boringAssistSnapshot = snapshot;\n"
           "    return {revision: snapshot.revision,\n"
           "      prompt: globalThis.__boringAssistProtocol.makePrompt(",
           Json(text),
           ", snapshot)};\n"
           "  } catch (error) {\n"
           "    return {error: String(error && error.message || error)};\n"
           "  }\n"
           "})()"}),
      base::BindOnce(&AssistanceSession::OnCaptured,
                     weak_factory_.GetWeakPtr()));
}

void AssistanceSession::OnCaptured(base::Value result) {
  const base::DictValue* dict = result.GetIfDict();
  const std::string* prompt = dict ? dict->FindString("prompt") : nullptr;
  const std::optional<int> revision =
      dict ? dict->FindInt("revision") : std::nullopt;
  if (!prompt || !revision) {
    SetState(State::kFailed, "capture_failed");
    return;
  }
  prompt_ = *prompt;
  revision_ = *revision;
  SetState(State::kReady, std::string());
  if (std::exchange(share_when_ready_, false)) {
    Share();
  }
}

void AssistanceSession::Share() {
  if (state_ != State::kReady) {
    return;
  }
  if (!GeminiIsProvider()) {
    SetState(State::kFailed, "provider_not_ready");
    return;
  }
  // A fresh adapter per request: each one sends at most once.
  RunInGemini(
      base::StrCat({"globalThis.__boringAssistGemini?.dispose();\n"
                    "globalThis.__boringAssistGemini = (\n",
                    kAssistanceGeminiScript,
                    "\n)(document, () => new URL(location.href), ",
                    Json(provider_.Serialize()),
                    ");\n"
                    "(() => {\n"
                    "  const gemini = globalThis.__boringAssistGemini;\n"
                    "  const prepared = gemini.prepare(",
                    Json(prompt_),
                    ");\n"
                    "  return prepared.ok && ",
                    press_send_ ? "true" : "false",
                    " ? gemini.submit() : prepared;\n"
                    "})()"}),
      base::BindOnce(&AssistanceSession::OnShared, weak_factory_.GetWeakPtr()));
}

void AssistanceSession::OnShared(base::Value result) {
  const base::DictValue* dict = result.GetIfDict();
  const std::string* reason = dict ? FindReason(*dict) : nullptr;
  if (!dict || !dict->FindBool("ok").value_or(false)) {
    SetState(State::kFailed, reason ? *reason : "provider_not_ready");
    return;
  }
  sent_at_ = base::TimeTicks::Now();
  SetState(press_send_ ? State::kWaitingForReply : State::kWaitingForSend,
           std::string());
  poll_timer_.Start(FROM_HERE, kPollInterval,
                    base::BindRepeating(&AssistanceSession::Poll,
                                        weak_factory_.GetWeakPtr()));
}

void AssistanceSession::Poll() {
  if (!GeminiIsProvider()) {
    Stop(State::kFailed, "provider_not_ready");
    return;
  }
  RunInGemini(
      "(() => {\n"
      "  const gemini = globalThis.__boringAssistGemini;\n"
      "  if (!gemini) return {ok: false, reason: 'gemini_reloaded'};\n"
      "  const reply = gemini.readReply();\n"
      "  if (reply.ok || reply.reason !== 'waiting') return reply;\n"
      "  return {ok: false, reason:\n"
      "    gemini.status().reason === 'generating' ? 'generating' : "
      "'waiting'};\n"
      "})()",
      base::BindOnce(&AssistanceSession::OnPolled, weak_factory_.GetWeakPtr()));
}

void AssistanceSession::OnPolled(base::Value result) {
  const base::DictValue* dict = result.GetIfDict();
  if (!dict) {
    // The frame was busy or swapping; the next tick asks again.
    return;
  }
  const std::string* reason = FindReason(*dict);
  if (dict->FindBool("ok").value_or(false)) {
    poll_timer_.Stop();
    const std::string* text = dict->FindString("text");
    if (!text) {
      SetState(State::kAnswered, "reply_unreadable");
      return;
    }
    RunInSource(base::StrCat({"(() => {\n"
                              "  try {\n"
                              "    const snapshot = "
                              "globalThis.__boringAssistSnapshot;\n"
                              "    if (!snapshot || snapshot.requestId !== ",
                              Json(request_id_),
                              ") return null;\n"
                              "    return globalThis.__boringAssistProtocol"
                              ".parseGuidance(",
                              Json(*text),
                              ", snapshot);\n"
                              "  } catch (error) {\n"
                              "    return null;\n"
                              "  }\n"
                              "})()"}),
                base::BindOnce(&AssistanceSession::OnParsed,
                               weak_factory_.GetWeakPtr()));
    return;
  }
  if (!reason) {
    return;
  }
  if (*reason == "waiting" && state_ == State::kWaitingForSend) {
    return;
  }
  if (*reason == "invalid_reply_size") {
    // The answer is still there to read in Gemini; it just names nothing.
    Stop(State::kAnswered, "reply_too_long");
    return;
  }
  if (*reason == "gemini_reloaded" || *reason == "unexpected_destination" ||
      *reason == "disposed") {
    Stop(State::kFailed, *reason);
    return;
  }
  // Anything else means Gemini has it and is still answering.
  if (state_ == State::kWaitingForSend) {
    sent_at_ = base::TimeTicks::Now();
    SetState(State::kWaitingForReply, std::string());
  } else if (base::TimeTicks::Now() - sent_at_ > kSlowAfter &&
             reason_ != "slow") {
    SetState(State::kWaitingForReply, "slow");
  }
}

void AssistanceSession::OnParsed(base::Value result) {
  candidate_ = result.is_string() ? result.GetString() : std::string();
  SetState(State::kAnswered, std::string());
}

bool AssistanceSession::CanShowMe() const {
  return state_ == State::kAnswered && !candidate_.empty();
}

void AssistanceSession::ShowMe() {
  if (!CanShowMe()) {
    return;
  }
  RunInSource(
      base::StrCat({"globalThis.__boringAssistPage ? "
                    "globalThis.__boringAssistPage.highlight(",
                    Json(request_id_), ", ", base::NumberToString(revision_),
                    ", ", Json(candidate_),
                    ") : {ok: false, reason: 'stale_or_unknown_target'}"}),
      base::BindOnce(&AssistanceSession::OnHighlighted,
                     weak_factory_.GetWeakPtr()));
}

void AssistanceSession::OnHighlighted(base::Value result) {
  const base::DictValue* dict = result.GetIfDict();
  if (dict && dict->FindBool("ok").value_or(false)) {
    return;
  }
  // Spec: a stale or changed target asks for a fresh question rather than
  // outlining something else.
  candidate_.clear();
  SetState(State::kAnswered, "stale_target");
}

void AssistanceSession::PrimaryPageChanged(content::Page& page) {
  if (state_ != State::kIdle && state_ != State::kFailed) {
    Stop(State::kStale, "page_changed");
  }
}

void AssistanceSession::DidFinishNavigation(
    content::NavigationHandle* navigation) {
  // Cross-document loads arrive through PrimaryPageChanged; this catches
  // the pushState and fragment changes single-page apps make.
  if (navigation->IsInPrimaryMainFrame() && navigation->HasCommitted() &&
      navigation->IsSameDocument() && state_ != State::kIdle &&
      state_ != State::kFailed) {
    Stop(State::kStale, "page_changed");
  }
}

void AssistanceSession::WebContentsDestroyed() {
  Stop(State::kFailed, "tab_closed");
  Observe(nullptr);
}

void AssistanceSession::RunInSource(const std::string& script,
                                    ResultCallback callback) {
  content::WebContents* source = web_contents();
  if (!source) {
    return;
  }
  source->GetPrimaryMainFrame()->ExecuteJavaScriptInIsolatedWorld(
      base::UTF8ToUTF16(script), std::move(callback), kAssistanceWorldId);
}

void AssistanceSession::RunInGemini(const std::string& script,
                                    ResultCallback callback) {
  if (!gemini_) {
    return;
  }
  gemini_->GetPrimaryMainFrame()->ExecuteJavaScriptInIsolatedWorld(
      base::UTF8ToUTF16(script), std::move(callback), kAssistanceWorldId);
}

bool AssistanceSession::GeminiIsProvider() const {
  if (!gemini_) {
    return false;
  }
  // Spec: page context goes only to the exact provider origin, and only
  // on its chat page. Sign-in pages and redirects never get it.
  content::RenderFrameHost* frame = gemini_->GetPrimaryMainFrame();
  const std::string_view path = frame->GetLastCommittedURL().path();
  return frame->GetLastCommittedOrigin().IsSameOriginWith(provider_) &&
         (path == "/app" || base::StartsWith(path, "/app/"));
}

void AssistanceSession::Stop(State state, std::string reason) {
  weak_factory_.InvalidateWeakPtrs();
  poll_timer_.Stop();
  candidate_.clear();
  share_when_ready_ = false;
  SetState(state, std::move(reason));
}

void AssistanceSession::SetState(State state, std::string reason) {
  state_ = state;
  reason_ = std::move(reason);
  if (on_changed_) {
    on_changed_.Run();
  }
}

}  // namespace boring
