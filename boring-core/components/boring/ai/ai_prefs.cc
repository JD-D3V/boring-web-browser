// Copyright 2026 boring. BSD style license.

#include "components/boring/ai/ai_prefs.h"

#include "base/base64.h"
#include "base/strings/strcat.h"
#include "build/build_config.h"
#include "components/pref_registry/pref_registry_syncable.h"
#include "components/prefs/pref_service.h"
#include "net/base/url_util.h"
#include "url/gurl.h"

#if BUILDFLAG(IS_WIN)
#include <windows.h>

#include <wincrypt.h>
#endif

namespace boring {
namespace ai {

namespace {

// Encrypting the key with the operating system, so it is not sitting in
// the profile in the clear.
//
// On Windows this is DPAPI, the same facility Chromium's own password
// store uses, which ties the result to this Windows account: another
// user on the machine, or the file copied elsewhere, cannot read it.
// It does not defend against something already running as this user;
// nothing local can.
//
// TODO: when a second platform is built, move this to the browser's
// os_crypt_async Encryptor rather than adding more per platform code.
// Until then the other platforms refuse to store a key at all, which is
// deliberate: better no key saved than one saved in plain text.

#if BUILDFLAG(IS_WIN)

bool EncryptWithOs(const std::string& plaintext, std::string* out) {
  DATA_BLOB in = {};
  in.pbData = reinterpret_cast<BYTE*>(const_cast<char*>(plaintext.data()));
  in.cbData = static_cast<DWORD>(plaintext.size());

  DATA_BLOB encrypted = {};
  if (!::CryptProtectData(&in, L"boring ai key", /*pOptionalEntropy=*/nullptr,
                          /*pvReserved=*/nullptr,
                          /*pPromptStruct=*/nullptr, /*dwFlags=*/0,
                          &encrypted)) {
    return false;
  }
  out->assign(reinterpret_cast<char*>(encrypted.pbData), encrypted.cbData);
  ::LocalFree(encrypted.pbData);
  return true;
}

bool DecryptWithOs(const std::string& ciphertext, std::string* out) {
  if (ciphertext.empty()) {
    return false;
  }
  DATA_BLOB in = {};
  in.pbData = reinterpret_cast<BYTE*>(const_cast<char*>(ciphertext.data()));
  in.cbData = static_cast<DWORD>(ciphertext.size());

  DATA_BLOB plain = {};
  if (!::CryptUnprotectData(&in, /*ppszDataDescr=*/nullptr,
                            /*pOptionalEntropy=*/nullptr,
                            /*pvReserved=*/nullptr,
                            /*pPromptStruct=*/nullptr, /*dwFlags=*/0, &plain)) {
    return false;
  }
  out->assign(reinterpret_cast<char*>(plain.pbData), plain.cbData);
  ::SecureZeroMemory(plain.pbData, plain.cbData);
  ::LocalFree(plain.pbData);
  return true;
}

#else

bool EncryptWithOs(const std::string& plaintext, std::string* out) {
  return false;
}

bool DecryptWithOs(const std::string& ciphertext, std::string* out) {
  return false;
}

#endif  // BUILDFLAG(IS_WIN)

}  // namespace

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
  return HasApiKey(prefs);
}

bool IsPlausibleApiKey(const std::string& key) {
  // Long enough to be real, short enough to be sane.
  if (key.empty() || key.size() > 512) {
    return false;
  }
  for (const char c : key) {
    // Printable ASCII only: no space, no tab, and above all no CR or LF,
    // which would otherwise be copied straight into a request header.
    if (c < 0x21 || c > 0x7E) {
      return false;
    }
  }
  return true;
}

bool SetApiKey(PrefService* prefs, const std::string& key) {
  if (!prefs) {
    return false;
  }
  if (key.empty()) {
    prefs->SetString(prefs::kApiKey, std::string());
    return true;
  }
  if (!IsPlausibleApiKey(key)) {
    return false;
  }
  std::string encrypted;
  if (!EncryptWithOs(key, &encrypted)) {
    // Refuse rather than quietly falling back to storing it in the
    // clear. A key that did not save is better than one that leaks.
    return false;
  }
  prefs->SetString(prefs::kApiKey, base::Base64Encode(encrypted));
  return true;
}

std::string GetApiKey(const PrefService* prefs) {
  if (!prefs) {
    return std::string();
  }
  const std::string stored = prefs->GetString(prefs::kApiKey);
  if (stored.empty()) {
    return std::string();
  }
  std::string encrypted;
  if (!base::Base64Decode(stored, &encrypted)) {
    return std::string();
  }
  std::string key;
  if (!DecryptWithOs(encrypted, &key)) {
    return std::string();
  }
  // Guard the boundary again on the way out: what comes back from disk
  // is not trusted just because we put it there.
  return IsPlausibleApiKey(key) ? key : std::string();
}

bool HasApiKey(const PrefService* prefs) {
  return prefs && !prefs->GetString(prefs::kApiKey).empty();
}

bool OllamaStaysOnThisMachine(const PrefService* prefs) {
  if (!prefs) {
    return false;
  }
  const GURL url(prefs->GetString(prefs::kOllamaUrl));
  if (!url.is_valid() || !url.SchemeIsHTTPOrHTTPS()) {
    return false;
  }
  // "localhost" and anything resolving to a loopback literal stay here.
  // Anything else is a machine across a network, however it is spelled.
  return net::IsLocalhost(url);
}

std::string DestinationForDisplay(const PrefService* prefs) {
  if (!prefs) {
    return std::string();
  }
  const std::string provider = prefs->GetString(prefs::kProvider);
  if (provider == "ollama") {
    const GURL url(prefs->GetString(prefs::kOllamaUrl));
    if (!url.is_valid()) {
      return "an address that is not valid yet";
    }
    if (OllamaStaysOnThisMachine(prefs)) {
      return "Ollama on this computer";
    }
    // Say the real host out loud. This is the whole point of the screen.
    // host() hands back a view, so build the string rather than adding to it.
    return base::StrCat({"Ollama at ", url.host()});
  }
  return DescribeDestination(prefs);
}

}  // namespace ai
}  // namespace boring
