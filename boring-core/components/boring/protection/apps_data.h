// Copyright 2026 boring. BSD style license.

// What the Protection page needs to know about "Apps you added" that is
// not in Chromium: which group known add-ons belong to, and how the AI
// assistant row reads. Standard library only, so tools/tests/apps_probe.cc
// can build it without Chromium.

#ifndef COMPONENTS_BORING_PROTECTION_APPS_DATA_H_
#define COMPONENTS_BORING_PROTECTION_APPS_DATA_H_

#include <string>
#include <string_view>

namespace boring {

enum class AddonGroup {
  kOther,
  kPasswordManager,
  kCloud,
  kAi,
};

struct KnownAddon {
  const char* id;
  AddonGroup group;
  // What it connects to, in plain words. Names come from the add-on
  // itself, so this never repeats a brand.
  const char* line;
};

// Chrome Web Store IDs of the add-ons we recognize. An add-on that
// is not here is "Other add-ons".
inline constexpr KnownAddon kKnownAddons[] = {
    // Bitwarden
    {"nngceckbapebfimnlniiiahkandclblb", AddonGroup::kPasswordManager,
     "Fills in passwords."},
    // 1Password
    {"aeblfdkhhhdcdjpifhhbdiojplfjncoa", AddonGroup::kPasswordManager,
     "Fills in passwords."},
    // KeePassXC-Browser
    {"oboonakemofpalcgghocfoadofidjkkk", AddonGroup::kPasswordManager,
     "Fills in passwords."},
    // Proton Pass
    {"ghmbeldphafepmbegfdlkpapadhbakde", AddonGroup::kPasswordManager,
     "Fills in passwords."},
    // Save to Google Drive
    {"gmbmikajjgmnabiglmofipeabaddhgne", AddonGroup::kCloud, ""},
    // Sider
    {"difoiogjjojoaoomphldepapgpbgkhkb", AddonGroup::kAi, ""},
};

inline const KnownAddon* FindKnownAddon(std::string_view id) {
  for (const KnownAddon& known : kKnownAddons) {
    if (id == known.id) {
      return &known;
    }
  }
  return nullptr;
}

inline AddonGroup GroupForAddon(std::string_view id) {
  const KnownAddon* known = FindKnownAddon(id);
  return known ? known->group : AddonGroup::kOther;
}

inline const char* AddonGroupKey(AddonGroup group) {
  switch (group) {
    case AddonGroup::kPasswordManager:
      return "password";
    case AddonGroup::kCloud:
      return "cloud";
    case AddonGroup::kAi:
      return "ai";
    case AddonGroup::kOther:
      return "other";
  }
}

// The "AI assistant" row, from the provider chrome://boring-ai saved.
struct AiRow {
  bool on = false;
  std::string label;  // "Off", "Ollama on this computer", ...
  std::string host;   // Where a request goes. Empty when off or local.
};

// `provider` is the boring.ai.provider pref, `ollama_host` the host part
// of boring.ai.ollama_url. A provider this build does not know reads as
// off, the same as the AI page does.
inline AiRow DescribeAiRow(std::string_view provider,
                           std::string_view ollama_host,
                           bool ollama_is_local) {
  AiRow row;
  row.label = "Off";
  if (provider == "ollama") {
    row.on = true;
    if (ollama_is_local) {
      row.label = "Ollama on this computer";
    } else if (ollama_host.empty()) {
      row.label = "Ollama address needs to be set up";
    } else {
      row.label = "Ollama at " + std::string(ollama_host);
    }
    return row;
  }
  struct Cloud {
    const char* provider;
    const char* name;
    const char* host;
  };
  static constexpr Cloud kCloud[] = {
      {"gemini", "Gemini", "generativelanguage.googleapis.com"},
      {"openai", "OpenAI", "api.openai.com"},
      {"openrouter", "OpenRouter", "openrouter.ai"},
      {"groq", "Groq", "api.groq.com"},
  };
  for (const Cloud& cloud : kCloud) {
    if (provider == cloud.provider) {
      row.on = true;
      row.label = std::string(cloud.name) + ", your key, on click only";
      row.host = cloud.host;
      return row;
    }
  }
  return row;
}

}  // namespace boring

#endif  // COMPONENTS_BORING_PROTECTION_APPS_DATA_H_
