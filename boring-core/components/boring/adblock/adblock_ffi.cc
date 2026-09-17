// Copyright 2026 boring. BSD style license.

#include "components/boring/adblock/adblock_ffi.h"

#include "base/files/file_path.h"
#include "base/logging.h"
#include "base/no_destructor.h"
#include "base/path_service.h"
#include "base/scoped_native_library.h"
#include "build/build_config.h"

#if BUILDFLAG(IS_WIN)
#include <windows.h>

#include <softpub.h>
#include <wintrust.h>
#endif

namespace boring {

namespace {

#if BUILDFLAG(IS_WIN)

// True when the file carries an Authenticode signature that chains to a
// root this machine trusts.
//
// Revocation is deliberately not checked over the network: this runs on
// the path to loading the engine, and the browser does not phone home.
bool HasTrustedSignature(const base::FilePath& path) {
  WINTRUST_FILE_INFO file = {};
  file.cbStruct = sizeof(file);
  file.pcwszFilePath = path.value().c_str();

  WINTRUST_DATA data = {};
  data.cbStruct = sizeof(data);
  data.dwUIChoice = WTD_UI_NONE;
  data.fdwRevocationChecks = WTD_REVOKE_NONE;
  data.dwUnionChoice = WTD_CHOICE_FILE;
  data.pFile = &file;
  data.dwStateAction = WTD_STATEACTION_VERIFY;
  data.dwUIContext = WTD_UICONTEXT_EXECUTE;
  data.dwProvFlags = WTD_CACHE_ONLY_URL_RETRIEVAL;

  GUID action = WINTRUST_ACTION_GENERIC_VERIFY_V2;
  HWND no_ui = static_cast<HWND>(INVALID_HANDLE_VALUE);
  const LONG status = ::WinVerifyTrust(no_ui, &action, &data);

  // Only the trust provider frees this, and only when it allocated it.
  if (data.hWVTStateData != nullptr) {
    data.dwStateAction = WTD_STATEACTION_CLOSE;
    ::WinVerifyTrust(no_ui, &action, &data);
  }
  return status == ERROR_SUCCESS;
}

// A signed browser demands a signed engine. An unsigned browser is a
// developer build, where insisting on a signature would only stop the
// thing working before a certificate exists. If we cannot tell, we ask
// for the signature: the safe answer is the strict one.
bool ShouldRequireSignature() {
  base::FilePath self;
  if (!base::PathService::Get(base::FILE_EXE, &self)) {
    return true;
  }
  return HasTrustedSignature(self);
}

#endif  // BUILDFLAG(IS_WIN)

constexpr base::FilePath::CharType kLibraryName[] =
    FILE_PATH_LITERAL("boring_adblock.dll");

// Reads one symbol and reports a clear message when it is missing.
template <typename Fn>
bool Bind(base::NativeLibrary lib, const char* name, Fn* out) {
  void* symbol = base::GetFunctionPointerFromNativeLibrary(lib, name);
  if (!symbol) {
    LOG(ERROR) << "boring: missing symbol " << name;
    return false;
  }
  *out = reinterpret_cast<Fn>(symbol);
  return true;
}

struct Loaded {
  Loaded() {
    base::FilePath dir;
    if (!base::PathService::Get(base::DIR_MODULE, &dir)) {
      return;
    }
    // Always an absolute path next to the browser, never a bare name,
    // so the Windows library search order cannot be used to slip a
    // different DLL in ahead of ours.
    const base::FilePath path = dir.Append(kLibraryName);

#if BUILDFLAG(IS_WIN)
    // The engine runs in the browser process, outside the sandbox, so
    // whoever controls this file controls the browser. In a signed
    // build it must be signed too.
    if (ShouldRequireSignature() && !HasTrustedSignature(path)) {
      LOG(ERROR) << "boring: " << kLibraryName << " is not signed by a "
                 << "trusted publisher, refusing to load it. Protections "
                 << "are off.";
      return;
    }
#endif

    base::NativeLibraryLoadError error;
    library = base::ScopedNativeLibrary(base::LoadNativeLibrary(path, &error));
    if (!library.is_valid()) {
      LOG(WARNING) << "boring: could not load " << kLibraryName << ": "
                   << error.ToString() << ", protections are off";
      return;
    }
    base::NativeLibrary handle = library.get();
    all_symbols_bound =
        Bind(handle, "boring_adblock_new", &api.adblock_new) &&
        Bind(handle, "boring_adblock_check", &api.adblock_check) &&
        Bind(handle, "boring_adblock_free", &api.adblock_free) &&
        Bind(handle, "boring_scamlist_new", &api.scamlist_new) &&
        Bind(handle, "boring_scamlist_contains", &api.scamlist_contains) &&
        Bind(handle, "boring_scamlist_free", &api.scamlist_free) &&
        Bind(handle, "boring_scamlist_size", &api.scamlist_size);
  }

  base::ScopedNativeLibrary library;
  BoringLibrary api;
  bool all_symbols_bound = false;
};

}  // namespace

const BoringLibrary* GetBoringLibrary() {
  static base::NoDestructor<Loaded> loaded;
  return loaded->all_symbols_bound ? &loaded->api : nullptr;
}

}  // namespace boring
