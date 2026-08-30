// Copyright 2026 boring. BSD style license.
// C interface of the boring_adblock DLL (built from boring-core/rust).

#ifndef COMPONENTS_BORING_ADBLOCK_ADBLOCK_FFI_H_
#define COMPONENTS_BORING_ADBLOCK_ADBLOCK_FFI_H_

#include <stddef.h>

extern "C" {

// Builds an engine from filter list text. Returns null on failure.
void* boring_adblock_new(const unsigned char* rules, size_t len);

// Returns 1 when the request should be blocked. Safe to call from any
// thread.
int boring_adblock_check(const void* engine,
                         const char* url,
                         const char* source_url,
                         const char* request_type);

void boring_adblock_free(void* engine);

}  // extern "C"

#endif  // COMPONENTS_BORING_ADBLOCK_ADBLOCK_FFI_H_
