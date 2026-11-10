// Copyright 2026 boring. BSD style license.

#ifndef COMPONENTS_BORING_SCAM_QUAD9_ANSWER_H_
#define COMPONENTS_BORING_SCAM_QUAD9_ANSWER_H_

#include <string>
#include <string_view>

namespace boring {

// Plain C++ with no Chromium types, so tools/tests/test_quad9_answer.py
// compiles this file alone and feeds it captured answers.

enum class Quad9Verdict {
  // "No such name" with Extended DNS Error 17 (Filtered): Quad9 refused to
  // resolve the name because it is on its threat list.
  kBlocked,
  // A well formed answer that is anything else: a real "does not exist",
  // an address, another error code.
  kNotBlocked,
  // Not a DNS answer for `host`, or cut short. The bytes come from the
  // network, so every read is bounds checked.
  kInvalid,
};

// The DNS message (RFC 1035) that asks for the A record of `host`, with
// id 0 as DNS over HTTPS wants. Empty when `host` is not a name that can be
// written (empty, an empty label, a label over 63 bytes, over 253 in all).
std::string BuildDnsQuery(std::string_view host);

// Reads the answer to BuildDnsQuery(host). Only an NXDOMAIN with no answer
// and no authority records and an Extended DNS Error with info code 17
// (RFC 8914) is kBlocked.
Quad9Verdict ParseQuad9Answer(std::string_view response,
                              std::string_view host);

}  // namespace boring

#endif  // COMPONENTS_BORING_SCAM_QUAD9_ANSWER_H_
