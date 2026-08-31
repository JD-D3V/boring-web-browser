// Copyright 2026 boring. BSD style license.

#include "components/boring/ai/ai_prefs.h"

#include "components/pref_registry/pref_registry_syncable.h"
#include "components/prefs/pref_service.h"

namespace boring {
namespace ai {

void RegisterProfilePrefs(user_prefs::PrefRegistrySyncable* registry) {
  registry->RegisterStringPref(prefs::kProvider, "off");
  registry->RegisterStringPref(prefs::kModel, "");
  registry->RegisterStringPref(prefs::kOllamaUrl, "http://localhost:11434");
  // The key is never synced to other devices.
  registry->RegisterStringPref(prefs::kApiKey, "");
}

std::string DescribeDestination(const PrefService* prefs) {
  if (!prefs) {
    return std::string();
  }
  const std::string provider = prefs->GetString(prefs::kProvider);
  if (provider == "ollama") {
    return "your own computer";
  }
  if (provider == "gemini") {
    return "Google Gemini";
  }
  if (provider == "openai") {
    return "OpenAI";
  }
  if (provider == "openrouter") {
    return "OpenRouter";
  }
  if (provider == "groq") {
    return "Groq";
  }
  return std::string();
}

bool IsReady(const PrefService* prefs) {
  if (!prefs) {
    return false;
  }
  const std::string provider = prefs->GetString(prefs::kProvider);
  if (provider == "off" || provider.empty()) {
    return false;
  }
  if (provider == "ollama") {
    return !prefs->GetString(prefs::kOllamaUrl).empty();
  }
  return !prefs->GetString(prefs::kApiKey).empty();
}

}  // namespace ai
}  // namespace boring
