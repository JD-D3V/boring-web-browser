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

// One filter list for BoringLibrary::adblock_new_lists. Matches
// BoringAdblockList in boring-core/rust/src/lib.rs.
struct BoringAdblockList {
  const unsigned char* text = nullptr;  // not NUL-terminated
  size_t len = 0;
  // Non-zero for uBO's own lists, which may use every scriptlet,
  // trusted ones included. Zero for everything else.
  int trusted = 0;
};

// Bits returned by BoringLibrary::adblock_check_request.
inline constexpr int kAdblockMatched = 1;    // a blocking rule matched
inline constexpr int kAdblockException = 2;  // an exception rule matched
inline constexpr int kAdblockImportant = 4;  // block, exceptions or not

// The C functions the DLL exports.
struct BoringLibrary {
  // Ad and tracker blocking.
  void* (*adblock_new)(const unsigned char* rules, size_t len) = nullptr;
  int (*adblock_check)(const void* engine,
                       const char* url,
                       const char* source_url,
                       const char* request_type) = nullptr;
  void (*adblock_free)(void* engine) = nullptr;

  // One engine from several lists, each trusted or not.
  void* (*adblock_new_lists)(const BoringAdblockList* lists,
                             size_t count) = nullptr;

  // Scriptlets and $redirect stubs, parsed once from resources.json and
  // shared by every engine given them. Returns 1 on success.
  void* (*resources_new)(const unsigned char* json, size_t len) = nullptr;
  size_t (*resources_count)(const void* resources) = nullptr;
  void (*resources_free)(void* resources) = nullptr;
  int (*adblock_use_resources)(void* engine, const void* resources) = nullptr;

  // Returns kAdblock* bits. `previously_matched` and
  // `force_check_exceptions` carry what earlier engines found, so that
  // several engines answer as one. `redirect_out`, when not null,
  // receives a data: URL or null; free it with string_free.
  int (*adblock_check_request)(const void* engine,
                               const char* url,
                               const char* source_url,
                               const char* request_type,
                               int previously_matched,
                               int force_check_exceptions,
                               char** redirect_out) = nullptr;

  // Cosmetic filters. Both return JSON, or null on failure; free the
  // result with string_free.
  char* (*adblock_url_cosmetic_resources)(const void* engine,
                                          const char* url) = nullptr;
  char* (*adblock_hidden_class_id_selectors)(const void* engine,
                                             const char* const* classes,
                                             size_t class_count,
                                             const char* const* ids,
                                             size_t id_count,
                                             const char* const* exceptions,
                                             size_t exception_count) = nullptr;
  void (*adblock_string_free)(char* s) = nullptr;

  // Engine cache. serialize returns null on failure, else bytes to free
  // with bytes_free; deserialize returns null for anything that is not
  // an engine from this crate version. A loaded engine has no resources
  // until given them again. crate_version is static, never freed.
  unsigned char* (*adblock_serialize)(const void* engine,
                                      size_t* len_out) = nullptr;
  void (*adblock_bytes_free)(unsigned char* data, size_t len) = nullptr;
  void* (*adblock_deserialize)(const unsigned char* data, size_t len) = nullptr;
  const char* (*adblock_crate_version)() = nullptr;

  // The lines of a person's own rules that the engine will not use, as
  // JSON [{line, rule, error}], lines 1-based. Free with string_free.
  char* (*adblock_check_rules)(const unsigned char* text, size_t len) = nullptr;

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
