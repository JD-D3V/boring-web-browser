// Copyright 2026 boring. BSD style license.

#include "components/boring/ai/ai_summary_service.h"

#include <optional>
#include <utility>

#include "base/functional/bind.h"
#include "base/json/json_reader.h"
#include "base/json/json_writer.h"
#include "base/strings/strcat.h"
#include "base/values.h"
#include "components/boring/ai/ai_prefs.h"
#include "components/prefs/pref_service.h"
#include "net/traffic_annotation/network_traffic_annotation.h"
#include "services/network/public/cpp/resource_request.h"
#include "services/network/public/cpp/shared_url_loader_factory.h"
#include "services/network/public/cpp/simple_url_loader.h"
#include "url/gurl.h"

namespace boring {
namespace ai {

namespace {

// Long pages are cut down before sending. This keeps the request small
// and means less of the page leaves the machine.
constexpr size_t kMaxTextLength = 24000;
constexpr size_t kMaxResponseBytes = 1024 * 1024;

constexpr char kInstruction[] =
    "Summarise the following web page in plain language, in at most six "
    "short bullet points. Say what the page is for and what it says. Do "
    "not invent anything that is not in the text.\n\n";

// Builds the request for whichever service the person picked. Returns
// false when the settings are not filled in.
bool BuildRequest(const std::string& provider,
                  const PrefService* prefs,
                  const std::string& text,
                  GURL* url,
                  std::string* body,
                  std::string* auth_header) {
  const std::string model = prefs->GetString(prefs::kModel);
  const std::string key = prefs->GetString(prefs::kApiKey);
  const std::string prompt = base::StrCat({kInstruction, text});

  if (provider == "ollama") {
    GURL base(prefs->GetString(prefs::kOllamaUrl));
    if (!base.is_valid()) {
      return false;
    }
    *url = base.Resolve("/api/generate");
    base::DictValue request;
    request.Set("model", model.empty() ? "llama3.2" : model);
    request.Set("prompt", prompt);
    request.Set("stream", false);
    return base::JSONWriter::Write(request, body);
  }

  if (provider == "gemini") {
    if (key.empty()) {
      return false;
    }
    const std::string name = model.empty() ? "gemini-2.0-flash" : model;
    *url = GURL("https://generativelanguage.googleapis.com/v1beta/models/" +
                name + ":generateContent");
    *auth_header = "x-goog-api-key: " + key;
    base::DictValue part;
    part.Set("text", prompt);
    base::ListValue parts;
    parts.Append(std::move(part));
    base::DictValue content;
    content.Set("parts", std::move(parts));
    base::ListValue contents;
    contents.Append(std::move(content));
    base::DictValue request;
    request.Set("contents", std::move(contents));
    return base::JSONWriter::Write(request, body);
  }

  // The rest all speak the same shape as OpenAI's chat endpoint.
  if (key.empty()) {
    return false;
  }
  if (provider == "openai") {
    *url = GURL("https://api.openai.com/v1/chat/completions");
  } else if (provider == "openrouter") {
    *url = GURL("https://openrouter.ai/api/v1/chat/completions");
  } else if (provider == "groq") {
    *url = GURL("https://api.groq.com/openai/v1/chat/completions");
  } else {
    return false;
  }
  *auth_header = "Authorization: Bearer " + key;

  base::DictValue message;
  message.Set("role", "user");
  message.Set("content", prompt);
  base::ListValue messages;
  messages.Append(std::move(message));
  base::DictValue request;
  request.Set("model", model.empty() ? "gpt-4o-mini" : model);
  request.Set("messages", std::move(messages));
  return base::JSONWriter::Write(request, body);
}

// Digs the answer out of whichever shape came back.
std::string ReadAnswer(const std::string& provider, const std::string& body) {
  std::optional<base::DictValue> parsed =
      base::JSONReader::ReadDict(body, base::JSON_PARSE_CHROMIUM_EXTENSIONS);
  if (!parsed) {
    return std::string();
  }
  const base::DictValue& root = *parsed;

  if (provider == "ollama") {
    const std::string* response = root.FindString("response");
    return response ? *response : std::string();
  }

  if (provider == "gemini") {
    const base::ListValue* candidates = root.FindList("candidates");
    if (!candidates || candidates->empty()) {
      return std::string();
    }
    const base::DictValue* first = (*candidates)[0].GetIfDict();
    if (!first) {
      return std::string();
    }
    const base::DictValue* content = first->FindDict("content");
    if (!content) {
      return std::string();
    }
    const base::ListValue* parts = content->FindList("parts");
    if (!parts || parts->empty()) {
      return std::string();
    }
    const base::DictValue* part = (*parts)[0].GetIfDict();
    if (!part) {
      return std::string();
    }
    const std::string* text = part->FindString("text");
    return text ? *text : std::string();
  }

  const base::ListValue* choices = root.FindList("choices");
  if (!choices || choices->empty()) {
    return std::string();
  }
  const base::DictValue* first = (*choices)[0].GetIfDict();
  if (!first) {
    return std::string();
  }
  const base::DictValue* message = first->FindDict("message");
  if (!message) {
    return std::string();
  }
  const std::string* content = message->FindString("content");
  return content ? *content : std::string();
}

}  // namespace

// static
AiSummaryService* AiSummaryService::GetInstance() {
  static base::NoDestructor<AiSummaryService> instance;
  return instance.get();
}

AiSummaryService::AiSummaryService() = default;
AiSummaryService::~AiSummaryService() = default;

void AiSummaryService::HoldPage(const std::string& title,
                                const std::string& url,
                                const std::string& text) {
  loader_.reset();
  title_ = title;
  url_ = url;
  text_ = text.size() > kMaxTextLength ? text.substr(0, kMaxTextLength) : text;
  summary_.clear();
  error_.clear();
  state_ = text_.empty() ? State::kNothing : State::kWaiting;
}

void AiSummaryService::Forget() {
  loader_.reset();
  title_.clear();
  url_.clear();
  text_.clear();
  summary_.clear();
  error_.clear();
  state_ = State::kNothing;
}

void AiSummaryService::Send(
    PrefService* prefs,
    scoped_refptr<network::SharedURLLoaderFactory> loader_factory,
    base::RepeatingClosure on_change) {
  if (state_ != State::kWaiting || !prefs || !loader_factory) {
    return;
  }
  on_change_ = std::move(on_change);
  provider_ = prefs->GetString(prefs::kProvider);

  GURL url;
  std::string body;
  std::string auth_header;
  if (!BuildRequest(provider_, prefs, text_, &url, &body, &auth_header) ||
      !url.is_valid()) {
    error_ = "The AI settings are not filled in yet.";
    Finish(State::kFailed);
    return;
  }

  net::NetworkTrafficAnnotationTag annotation =
      net::DefineNetworkTrafficAnnotation("boring_ai_summary", R"(
        semantics {
          sender: "boring AI summary"
          description:
            "Sends the text of the page the user asked about to the AI "
            "service the user chose, to get a summary back."
          trigger:
            "The user picks Summarise this page and then confirms where "
            "it will be sent. Nothing is sent otherwise."
          data:
            "The visible text of the page, and the user's own API key "
            "for the service they picked."
          destination: OTHER
          destination_other:
            "The service the user chose in the AI settings, which may be "
            "a server on their own machine."
        }
        policy {
          cookies_allowed: NO
          setting:
            "Off by default. Turned on in the AI settings page, where the "
            "user picks a service and enters their own key."
          policy_exception_justification: "Not implemented yet."
        })");

  auto request = std::make_unique<network::ResourceRequest>();
  request->url = url;
  request->method = "POST";
  request->credentials_mode = network::mojom::CredentialsMode::kOmit;
  if (!auth_header.empty()) {
    size_t colon = auth_header.find(": ");
    request->headers.SetHeader(auth_header.substr(0, colon),
                               auth_header.substr(colon + 2));
  }

  loader_ = network::SimpleURLLoader::Create(std::move(request), annotation);
  loader_->AttachStringForUpload(body, "application/json");
  state_ = State::kWorking;
  if (on_change_) {
    on_change_.Run();
  }
  loader_->DownloadToString(
      loader_factory.get(),
      base::BindOnce(
          [](AiSummaryService* self, std::optional<std::string> response) {
            self->OnResponse(response ? std::make_unique<std::string>(
                                            std::move(*response))
                                      : nullptr);
          },
          base::Unretained(this)),
      kMaxResponseBytes);
}

void AiSummaryService::OnResponse(std::unique_ptr<std::string> body) {
  if (!body) {
    error_ =
        "Could not reach the service. Check the settings and your network.";
    Finish(State::kFailed);
    return;
  }
  std::string answer = ReadAnswer(provider_, *body);
  if (answer.empty()) {
    error_ = "The service replied, but there was no summary in the reply.";
    Finish(State::kFailed);
    return;
  }
  summary_ = std::move(answer);
  Finish(State::kDone);
}

void AiSummaryService::Finish(State state) {
  loader_.reset();
  state_ = state;
  if (on_change_) {
    on_change_.Run();
  }
}

}  // namespace ai
}  // namespace boring
