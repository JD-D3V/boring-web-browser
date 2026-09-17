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
// The user's own key for a cloud service, encrypted with the operating
// system's own facility and then base64'd. Kept on this device only and
// never synced. Read it with GetApiKey, never straight off the pref.
inline constexpr char kApiKey[] = "boring.ai.api_key";

}  // namespace prefs

void RegisterProfilePrefs(user_prefs::PrefRegistrySyncable* registry);

// Where a request would go, in plain words, for the honest label we
// show before anything is sent. Returns an empty string when nothing
// would leave the device.
std::string DescribeDestination(const PrefService* prefs);

// True when a provider is set up well enough to answer.
bool IsReady(const PrefService* prefs);

// A key must be printable ASCII with no spaces and no control
// characters. That is what every one of these services issues, and it
// stops a stray newline from turning into a second request header.
bool IsPlausibleApiKey(const std::string& key);

// Stores the key encrypted. An empty key clears it. Returns false when
// the key looks wrong or the operating system refused to encrypt it, in
// which case nothing is written.
bool SetApiKey(PrefService* prefs, const std::string& key);

// Returns the key in the clear, or an empty string when there is none
// or it cannot be decrypted.
std::string GetApiKey(const PrefService* prefs);

// True when a key is stored, without decrypting it. Use this instead of
// reading the key when all you need to know is whether one is set.
bool HasApiKey(const PrefService* prefs);

// True when the Ollama address points back at this machine, so that
// "nothing leaves this computer" is a fact rather than a hope.
bool OllamaStaysOnThisMachine(const PrefService* prefs);

// The address a request would actually go to, for the confirm screen.
// For Ollama this is the origin the person typed, so a remote one is
// named out loud instead of being described as local.
std::string DestinationForDisplay(const PrefService* prefs);

}  // namespace ai
}  // namespace boring

#endif  // COMPONENTS_BORING_AI_AI_PREFS_H_
