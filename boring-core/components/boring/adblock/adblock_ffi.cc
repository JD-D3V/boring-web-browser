// Copyright 2026 boring. BSD style license.

#include "components/boring/adblock/adblock_ffi.h"

#include "base/files/file_path.h"
#include "base/logging.h"
#include "base/no_destructor.h"
#include "base/path_service.h"
#include "base/scoped_native_library.h"

namespace boring {

namespace {

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
    base::NativeLibraryLoadError error;
    library = base::ScopedNativeLibrary(
        base::LoadNativeLibrary(dir.Append(kLibraryName), &error));
    if (!library.is_valid()) {
      LOG(WARNING) << "boring: could not load " << kLibraryName << ": "
                   << error.ToString() << ", protections are off";
      return;
    }
    base::NativeLibrary handle = library.get();
    ok = Bind(handle, "boring_adblock_new", &api.adblock_new) &&
         Bind(handle, "boring_adblock_check", &api.adblock_check) &&
         Bind(handle, "boring_adblock_free", &api.adblock_free) &&
         Bind(handle, "boring_scamlist_new", &api.scamlist_new) &&
         Bind(handle, "boring_scamlist_contains", &api.scamlist_contains) &&
         Bind(handle, "boring_scamlist_free", &api.scamlist_free) &&
         Bind(handle, "boring_scamlist_size", &api.scamlist_size);
  }

  base::ScopedNativeLibrary library;
  BoringLibrary api;
  bool ok = false;
};

}  // namespace

const BoringLibrary* GetBoringLibrary() {
  static base::NoDestructor<Loaded> loaded;
  return loaded->ok ? &loaded->api : nullptr;
}

}  // namespace boring
