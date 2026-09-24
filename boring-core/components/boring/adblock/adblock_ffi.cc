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
#include <wincrypt.h>
#include <wintrust.h>

#include <string>
#include <vector>

#include "components/boring/adblock/buildflags.h"
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

// Reads the name on the certificate a file was signed with, the way
// Windows would show it in the file's properties.
//
// A trusted signature on its own says only that somebody Windows
// trusts signed this file, and anybody can buy a certificate that
// Windows trusts. What we care about is whether *we* signed it, so the
// name has to come back out and be compared.
std::wstring SignerName(const base::FilePath& path) {
  HCERTSTORE store = nullptr;
  HCRYPTMSG message = nullptr;
  DWORD encoding = 0;
  DWORD content_type = 0;
  DWORD format_type = 0;
  if (!::CryptQueryObject(CERT_QUERY_OBJECT_FILE, path.value().c_str(),
                          CERT_QUERY_CONTENT_FLAG_PKCS7_SIGNED_EMBED,
                          CERT_QUERY_FORMAT_FLAG_BINARY, 0, &encoding,
                          &content_type, &format_type, &store, &message,
                          nullptr)) {
    return std::wstring();
  }

  std::wstring name;
  DWORD size = 0;
  if (::CryptMsgGetParam(message, CMSG_SIGNER_INFO_PARAM, 0, nullptr, &size) &&
      size >= sizeof(CMSG_SIGNER_INFO)) {
    std::vector<uint8_t> buffer(size);
    if (::CryptMsgGetParam(message, CMSG_SIGNER_INFO_PARAM, 0, buffer.data(),
                           &size)) {
      const auto* signer =
          reinterpret_cast<const CMSG_SIGNER_INFO*>(buffer.data());
      // The signature names the certificate by issuer and serial
      // number; the certificate itself travels in the same blob.
      CERT_INFO wanted = {};
      wanted.Issuer = signer->Issuer;
      wanted.SerialNumber = signer->SerialNumber;
      PCCERT_CONTEXT cert = ::CertFindCertificateInStore(
          store, encoding, 0, CERT_FIND_SUBJECT_CERT, &wanted, nullptr);
      if (cert) {
        const DWORD length = ::CertGetNameStringW(
            cert, CERT_NAME_SIMPLE_DISPLAY_TYPE, 0, nullptr, nullptr, 0);
        if (length > 1) {
          name.resize(length);
          ::CertGetNameStringW(cert, CERT_NAME_SIMPLE_DISPLAY_TYPE, 0, nullptr,
                               name.data(), length);
          name.resize(length - 1);  // Drop the terminator.
        }
        ::CertFreeCertificateContext(cert);
      }
    }
  }

  ::CryptMsgClose(message);
  ::CertCloseStore(store, 0);
  return name;
}

bool SameSigner(const std::wstring& a, const std::wstring& b) {
  return !a.empty() && a.size() == b.size() &&
         ::CompareStringOrdinal(a.c_str(), static_cast<int>(a.size()),
                                b.c_str(), static_cast<int>(b.size()),
                                /*bIgnoreCase=*/TRUE) == CSTR_EQUAL;
}

// Who the engine has to be signed by, or empty when the build does not
// know. A release build is told at compile time, so the answer cannot
// be changed by editing anything on the machine the browser runs on.
std::wstring ExpectedSigner() {
  const std::string configured = BUILDFLAG(BORING_SIGNING_SUBJECT);
  if (!configured.empty()) {
    return std::wstring(configured.begin(), configured.end());
  }
  // Nothing configured, so fall back to whoever signed the browser.
  // That still shuts out every other trusted signer, and it keeps a
  // build working before a certificate exists.
  base::FilePath self;
  if (!base::PathService::Get(base::FILE_EXE, &self)) {
    return std::wstring();
  }
  return HasTrustedSignature(self) ? SignerName(self) : std::wstring();
}

// True when the engine may be loaded.
//
// The old rule was "a signed browser demands a signed engine", which
// meant deleting the browser's own signature turned the check off. A
// release build now requires the signature outright.
bool EngineMayBeLoaded(const base::FilePath& engine) {
  const std::wstring expected = ExpectedSigner();
  if (expected.empty()) {
    if (BUILDFLAG(BORING_REQUIRE_SIGNED_ENGINE)) {
      LOG(ERROR) << "boring: this build requires a signed engine but the "
                 << "browser itself is not signed by a publisher we can "
                 << "name, refusing to load the engine";
      return false;
    }
    return true;  // Developer build, no certificate anywhere.
  }
  if (!HasTrustedSignature(engine)) {
    return false;
  }
  return SameSigner(expected, SignerName(engine));
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
    // whoever controls this file controls the browser.
    if (!EngineMayBeLoaded(path)) {
      LOG(ERROR) << "boring: " << kLibraryName << " is not signed by the "
                 << "publisher this browser was signed by, refusing to "
                 << "load it. Protections are off.";
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
