// Copyright 2026 boring. BSD style license.

#include "components/boring/update/browser_updater.h"

#include <windows.h>

#include <optional>
#include <string>
#include <utility>
#include <vector>

#include "base/at_exit.h"
#include "base/base64.h"
#include "base/command_line.h"
#include "base/files/file_path.h"
#include "base/files/file_util.h"
#include "base/functional/bind.h"
#include "base/functional/callback.h"
#include "base/logging.h"
#include "base/no_destructor.h"
#include "base/path_service.h"
#include "base/scoped_native_library.h"
#include "base/strings/string_number_conversions.h"
#include "base/strings/utf_string_conversions.h"
#include "base/task/sequenced_task_runner.h"
#include "base/task/thread_pool.h"
#include "base/win/registry.h"
#include "components/boring/core/boring_release.h"
#include "components/version_info/version_info.h"
#include "net/base/url_util.h"
#include "url/gurl.h"

namespace boring {

namespace {

// One address that never mentions a version, so a browser several
// releases behind still knows where to look. On our GitHub Pages site,
// published by the release steps beside the download page.
constexpr char kFeedUrl[] =
    "https://jd-d3v.github.io/boring-web-browser/appcast.xml";

// The EdDSA (Ed25519) public key our installers are signed with, base64,
// as `winsparkle-tool generate-key` prints it.
// The private half never enters the repo; losing it means no installed
// copy can ever be updated again.
//
// The key is checked first, so a build without a valid one makes no
// update request at all.
constexpr char kUpdateKey[] = "eGBavLH6pWpJTkkAfJ2nsRn7J40F85MbPCstiigKcko=";

// For the updater test, which serves a feed from this machine: read the
// feed from here, and trust this key as well. Both honoured only for a
// feed on localhost, so a shortcut with a switch on it cannot point a
// browser at somebody else's installers.
constexpr char kFeedUrlSwitch[] = "boring-update-url";
constexpr char kTestKeySwitch[] = "boring-update-key";
// Turn the updater off for one run, without changing anyone's setting.
constexpr char kDisableSwitch[] = "disable-boring-updates";

constexpr wchar_t kLibraryName[] = L"WinSparkle.dll";

// Where WinSparkle keeps its settings (last check, skipped version, the
// daily check switch), under HKEY_CURRENT_USER.
constexpr char kRegistryPath[] = "Software\\Boring Browser\\Updates";
constexpr wchar_t kRegistryPathW[] = L"Software\\Boring Browser\\Updates";
// WinSparkle's own name for the daily check setting.
constexpr wchar_t kAutomaticValue[] = L"CheckForUpdates";

// The part of WinSparkle's API we call, from include/winsparkle.h.
struct Api {
  using VoidFn = void(__cdecl*)();
  using SetStrFn = void(__cdecl*)(const char*);
  using SetKeyFn = int(__cdecl*)(const char*);
  using DetailsFn = void(__cdecl*)(const wchar_t*,
                                   const wchar_t*,
                                   const wchar_t*);
  using SetWStrFn = void(__cdecl*)(const wchar_t*);
  using SetIntFn = void(__cdecl*)(int);
  using GetIntFn = int(__cdecl*)();
  using CanShutdownFn = int(__cdecl*)();
  using SetCanShutdownFn = void(__cdecl*)(CanShutdownFn);
  using SetShutdownFn = void(__cdecl*)(VoidFn);

  VoidFn init = nullptr;
  VoidFn cleanup = nullptr;
  SetStrFn set_appcast_url = nullptr;
  SetKeyFn set_eddsa_public_key = nullptr;
  DetailsFn set_app_details = nullptr;
  SetWStrFn set_app_build_version = nullptr;
  SetStrFn set_registry_path = nullptr;
  SetIntFn set_automatic_check_for_updates = nullptr;
  GetIntFn get_automatic_check_for_updates = nullptr;
  SetCanShutdownFn set_can_shutdown_callback = nullptr;
  SetShutdownFn set_shutdown_request_callback = nullptr;
  VoidFn check_update_with_ui = nullptr;
};

struct Updater {
  BrowserUpdater::State state = BrowserUpdater::State::kStarting;
  bool started = false;
  base::ScopedNativeLibrary library;
  Api api;
  base::RepeatingClosure request_exit;
  scoped_refptr<base::SequencedTaskRunner> ui_task_runner;
};

Updater& Get() {
  static base::NoDestructor<Updater> updater;
  return *updater;
}

template <typename Fn>
bool Bind(base::NativeLibrary lib, const char* name, Fn* out) {
  void* symbol = base::GetFunctionPointerFromNativeLibrary(lib, name);
  if (!symbol) {
    LOG(ERROR) << "boring: WinSparkle is missing " << name;
    return false;
  }
  *out = reinterpret_cast<Fn>(symbol);
  return true;
}

bool IsEd25519Key(const std::string& base64) {
  const std::optional<std::vector<uint8_t>> key = base::Base64Decode(base64);
  return key && key->size() == 32;
}

GURL FeedUrl() {
  const base::CommandLine* command_line =
      base::CommandLine::ForCurrentProcess();
  if (command_line->HasSwitch(kFeedUrlSwitch)) {
    GURL url(command_line->GetSwitchValueASCII(kFeedUrlSwitch));
    if (url.is_valid() && net::IsLocalhost(url)) {
      return url;
    }
  }
  return GURL(kFeedUrl);
}

// The key to hand WinSparkle, or empty when there is none worth using.
std::string KeyToTrust(const GURL& feed) {
  const base::CommandLine* command_line =
      base::CommandLine::ForCurrentProcess();
  if (net::IsLocalhost(feed) && command_line->HasSwitch(kTestKeySwitch)) {
    const std::string test_key =
        command_line->GetSwitchValueASCII(kTestKeySwitch);
    return IsEd25519Key(test_key) ? test_key : std::string();
  }
  return IsEd25519Key(kUpdateKey) ? std::string(kUpdateKey) : std::string();
}

// Called by WinSparkle from its own thread, never the UI thread.
int __cdecl CanShutdown() {
  return 1;
}

// Called by WinSparkle from its own thread once the installer is running.
void __cdecl RequestShutdown() {
  Updater& updater = Get();
  if (updater.ui_task_runner && updater.request_exit) {
    updater.ui_task_runner->PostTask(FROM_HERE, updater.request_exit);
  }
}

struct Loaded {
  BrowserUpdater::State state = BrowserUpdater::State::kNoLibrary;
  base::ScopedNativeLibrary library;
  Api api;
  bool first_run = false;
};

// Blocking work, on a pool thread: find out whether this copy can update
// at all, and load the library if it can.
Loaded Load() {
  Loaded loaded;
  base::FilePath dir;
  if (!base::PathService::Get(base::DIR_MODULE, &dir)) {
    return loaded;
  }
  // The installer puts setup.exe in <version>\Installer beside chrome.dll.
  // A copy unpacked from the zip has none, and an installer run from it
  // would install a second browser rather than update this one.
  if (!base::PathExists(
          dir.AppendASCII("Installer").AppendASCII("setup.exe"))) {
    loaded.state = BrowserUpdater::State::kNotInstalled;
    return loaded;
  }

  // An absolute path beside the browser, never a bare name, so the
  // library search order cannot put another WinSparkle.dll first.
  const base::FilePath path = dir.Append(kLibraryName);
  base::NativeLibraryLoadError error;
  base::ScopedNativeLibrary library(base::LoadNativeLibrary(path, &error));
  if (!library.is_valid()) {
    LOG(WARNING) << "boring: could not load WinSparkle: " << error.ToString();
    return loaded;
  }
  Api api;
  base::NativeLibrary lib = library.get();
  const bool bound =
      Bind(lib, "win_sparkle_init", &api.init) &&
      Bind(lib, "win_sparkle_cleanup", &api.cleanup) &&
      Bind(lib, "win_sparkle_set_appcast_url", &api.set_appcast_url) &&
      Bind(lib, "win_sparkle_set_eddsa_public_key",
           &api.set_eddsa_public_key) &&
      Bind(lib, "win_sparkle_set_app_details", &api.set_app_details) &&
      Bind(lib, "win_sparkle_set_app_build_version",
           &api.set_app_build_version) &&
      Bind(lib, "win_sparkle_set_registry_path", &api.set_registry_path) &&
      Bind(lib, "win_sparkle_set_automatic_check_for_updates",
           &api.set_automatic_check_for_updates) &&
      Bind(lib, "win_sparkle_get_automatic_check_for_updates",
           &api.get_automatic_check_for_updates) &&
      Bind(lib, "win_sparkle_set_can_shutdown_callback",
           &api.set_can_shutdown_callback) &&
      Bind(lib, "win_sparkle_set_shutdown_request_callback",
           &api.set_shutdown_request_callback) &&
      Bind(lib, "win_sparkle_check_update_with_ui", &api.check_update_with_ui);
  if (!bound) {
    return loaded;
  }

  // No setting yet means nobody has chosen. The daily check is on by
  // default, because a browser that never hears about a new version
  // keeps every hole fixed since the day it was installed.
  base::win::RegKey key(HKEY_CURRENT_USER, kRegistryPathW, KEY_QUERY_VALUE);
  loaded.first_run = !key.Valid() || !key.HasValue(kAutomaticValue);

  loaded.library = std::move(library);
  loaded.api = api;
  loaded.state = BrowserUpdater::State::kReady;
  return loaded;
}

void Configure(Loaded loaded) {
  Updater& updater = Get();
  updater.state = loaded.state;
  if (loaded.state != BrowserUpdater::State::kReady) {
    return;
  }
  updater.library = std::move(loaded.library);
  updater.api = loaded.api;
  const Api& api = updater.api;

  const GURL feed = FeedUrl();
  const std::string key = KeyToTrust(feed);
  // Checked again here, not only before loading, because the test key
  // decides it too. A key WinSparkle does not accept means no updates:
  // it would otherwise fall back to looking for one in our resources.
  if (key.empty() || api.set_eddsa_public_key(key.c_str()) != 1) {
    updater.state = BrowserUpdater::State::kNoKey;
    return;
  }
  api.set_appcast_url(feed.spec().c_str());
  const std::wstring version = base::UTF8ToWide(BrowserUpdater::BuildVersion());
  api.set_app_details(L"Boring Browser", L"Boring Browser", version.c_str());
  api.set_app_build_version(version.c_str());
  api.set_registry_path(kRegistryPath);
  api.set_can_shutdown_callback(&CanShutdown);
  api.set_shutdown_request_callback(&RequestShutdown);
  if (loaded.first_run) {
    api.set_automatic_check_for_updates(1);
  }
  api.init();
  // WinSparkle checks, downloads and shows its window on threads of its
  // own. Stop them before the process ends, as winsparkle.h asks, rather
  // than have them cut off halfway when it does. This runs on the main
  // thread once the browser has shut down; the library stays loaded.
  base::AtExitManager::RegisterTask(
      base::BindOnce([] { Get().api.cleanup(); }));
}

}  // namespace

// static
void BrowserUpdater::StartOnce(base::RepeatingClosure request_exit) {
  Updater& updater = Get();
  if (updater.started) {
    return;
  }
  updater.started = true;
  if (base::CommandLine::ForCurrentProcess()->HasSwitch(kDisableSwitch)) {
    updater.state = State::kDisabled;
    return;
  }
  // Nothing to load and nothing to ask while there is no key to check an
  // installer against.
  if (KeyToTrust(FeedUrl()).empty()) {
    updater.state = State::kNoKey;
    return;
  }
  updater.request_exit = std::move(request_exit);
  updater.ui_task_runner = base::SequencedTaskRunner::GetCurrentDefault();
  base::ThreadPool::PostTaskAndReplyWithResult(
      FROM_HERE, {base::MayBlock(), base::TaskPriority::BEST_EFFORT},
      base::BindOnce(&Load), base::BindOnce(&Configure));
}

// static
BrowserUpdater::State BrowserUpdater::GetState() {
  return Get().state;
}

// static
bool BrowserUpdater::IsAutomatic() {
  Updater& updater = Get();
  return updater.state == State::kReady &&
         updater.api.get_automatic_check_for_updates() == 1;
}

// static
void BrowserUpdater::SetAutomatic(bool automatic) {
  Updater& updater = Get();
  if (updater.state == State::kReady) {
    updater.api.set_automatic_check_for_updates(automatic ? 1 : 0);
  }
}

// static
void BrowserUpdater::CheckNow() {
  Updater& updater = Get();
  if (updater.state == State::kReady) {
    updater.api.check_update_with_ui();
  }
}

// static
std::string BrowserUpdater::BuildVersion() {
  return std::string(version_info::GetVersionNumber()) + "." +
         base::NumberToString(kBoringRelease);
}

}  // namespace boring
