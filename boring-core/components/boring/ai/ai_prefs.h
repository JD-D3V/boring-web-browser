// Copyright 2026 boring. BSD style license.

#ifndef COMPONENTS_BORING_AI_AI_PREFS_H_
#define COMPONENTS_BORING_AI_AI_PREFS_H_

#include <string>

class PrefRegistrySimple;
class PrefService;

namespace user_prefs {
class PrefRegistrySyncable;
}

namespace boring {
namespace ai {

// Which service answers a question. Nothing runs unless the user asks,
// and nothing leaves the device unless the user picked a cloud service
// and typed their own key.
namespace prefs {

// One of: off, ollama, gemini, openai, openrouter, groq.
inline constexpr char kProvider[] = "boring.ai.provider";
// Model name, for example "llama3.2" or "gemini-2.0-flash".
inline constexpr char kModel[] = "boring.ai.model";
// Where a local Ollama server is listening.
inline constexpr char kOllamaUrl[] = "boring.ai.ollama_url";
// The user's own key for a cloud service. Kept on this device only and
// never synced.
inline constexpr char kApiKey[] = "boring.ai.api_key";

}  // namespace prefs

void RegisterProfilePrefs(user_prefs::PrefRegistrySyncable* registry);

// Where a request would go, in plain words, for the honest label we
// show before anything is sent. Returns an empty string when nothing
// would leave the device.
std::string DescribeDestination(const PrefService* prefs);

// True when a provider is set up well enough to answer.
bool IsReady(const PrefService* prefs);

}  // namespace ai
}  // namespace boring

#endif  // COMPONENTS_BORING_AI_AI_PREFS_H_
