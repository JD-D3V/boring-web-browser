// Copyright 2026 boring. BSD style license.

#ifndef COMPONENTS_BORING_AI_AI_SUMMARY_SERVICE_H_
#define COMPONENTS_BORING_AI_AI_SUMMARY_SERVICE_H_

#include <memory>
#include <string>

#include "base/functional/callback.h"
#include "base/memory/scoped_refptr.h"
#include "base/no_destructor.h"

class PrefService;

namespace network {
class SharedURLLoaderFactory;
class SimpleURLLoader;
}  // namespace network

namespace boring {
namespace ai {

// Runs a summary when, and only when, a person asks for one.
//
// The flow on purpose has two steps. Asking for a summary only puts the
// page aside as "waiting". Nothing is sent anywhere until the person
// looks at where it would go and says send. That is what makes the
// honest label real rather than decoration.
class AiSummaryService {
 public:
  enum class State {
    kNothing,   // no page is waiting
    kWaiting,   // a page is ready, nothing sent yet
    kWorking,   // sent, waiting for an answer
    kDone,      // there is a summary to read
    kFailed,    // something went wrong
  };

  static AiSummaryService* GetInstance();

  AiSummaryService(const AiSummaryService&) = delete;
  AiSummaryService& operator=(const AiSummaryService&) = delete;

  // Puts a page aside, ready to be sent if the person agrees. Replaces
  // anything already waiting.
  void HoldPage(const std::string& title,
                const std::string& url,
                const std::string& text);

  // Sends the page that is waiting. Does nothing unless the state is
  // kWaiting. on_change is called whenever the state moves on.
  void Send(PrefService* prefs,
            scoped_refptr<network::SharedURLLoaderFactory> loader_factory,
            base::RepeatingClosure on_change);

  // Throws the waiting page away without sending it.
  void Forget();

  State state() const { return state_; }
  const std::string& title() const { return title_; }
  const std::string& url() const { return url_; }
  const std::string& summary() const { return summary_; }
  const std::string& error() const { return error_; }
  // How much text is waiting, so a person can see what would be sent.
  size_t text_length() const { return text_.size(); }

 private:
  friend class base::NoDestructor<AiSummaryService>;

  AiSummaryService();
  ~AiSummaryService();

  void OnResponse(std::unique_ptr<std::string> body);
  void Finish(State state);

  State state_ = State::kNothing;
  std::string title_;
  std::string url_;
  std::string text_;
  std::string summary_;
  std::string error_;
  std::string provider_;

  base::RepeatingClosure on_change_;
  std::unique_ptr<network::SimpleURLLoader> loader_;
};

}  // namespace ai
}  // namespace boring

#endif  // COMPONENTS_BORING_AI_AI_SUMMARY_SERVICE_H_
