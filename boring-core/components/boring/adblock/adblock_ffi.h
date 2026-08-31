// Copyright 2026 boring. BSD style license.
// Access to the boring_adblock DLL (built from boring-core/rust).
//
// The library is loaded by hand, at first use, and only in the browser
// process. It is never linked at build time, so the sandboxed renderer
// and utility processes never try to load it. That matters because the
// sandbox only allows Microsoft signed code in those processes.

#ifndef COMPONENTS_BORING_ADBLOCK_ADBLOCK_FFI_H_
#define COMPONENTS_BORING_ADBLOCK_ADBLOCK_FFI_H_

#include <stddef.h>

namespace boring {

// The C functions the DLL exports.
struct BoringLibrary {
  // Ad and tracker blocking.
  void* (*adblock_new)(const unsigned char* rules, size_t len) = nullptr;
  int (*adblock_check)(const void* engine,
                       const char* url,
                       const char* source_url,
                       const char* request_type) = nullptr;
  void (*adblock_free)(void* engine) = nullptr;

  // Scam and phishing blocklist.
  void* (*scamlist_new)(const unsigned char* text, size_t len) = nullptr;
  int (*scamlist_contains)(const void* list, const char* host) = nullptr;
  void (*scamlist_free)(void* list) = nullptr;
  size_t (*scamlist_size)(const void* list) = nullptr;
};

// Loads the library once and returns it. Returns null when the library
// is missing or a symbol is not found, in which case every protection
// stays off and the browser works as normal. Safe to call from any
// thread; the load happens once.
const BoringLibrary* GetBoringLibrary();

}  // namespace boring

#endif  // COMPONENTS_BORING_ADBLOCK_ADBLOCK_FFI_H_
