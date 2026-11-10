// Copyright 2026 boring. BSD style license.

#ifndef COMPONENTS_BORING_SCAM_QUAD9_BLOCK_CHECKER_H_
#define COMPONENTS_BORING_SCAM_QUAD9_BLOCK_CHECKER_H_

#include <memory>
#include <optional>
#include <string>

#include "base/functional/callback.h"

namespace content {
class BrowserContext;
}

namespace network {
class SimpleURLLoader;
}

namespace boring {

// Asks Quad9, once, whether it refused to resolve a name because the name
// is on its threat list. The browser's own lookup only learns "not found",
// the same as for a typo. The answer to this question tells them apart.
//
// The question goes to the server the person already uses for secure DNS
// (dns.quad9.net), as a DNS over HTTPS GET. No cookies, no credentials, no
// referrer, a small cap on the answer and a short timeout. Anything but a
// clear "blocked" is reported as not blocked.
class Quad9BlockChecker {
 public:
  using Callback = base::OnceCallback<void(bool blocked)>;

  Quad9BlockChecker();
  ~Quad9BlockChecker();

  // True when the question was sent, and then `callback` runs once, unless
  // this object is deleted first. False when `host` cannot be asked about;
  // `callback` never runs then.
  bool Check(content::BrowserContext* context,
             const std::string& host,
             Callback callback);

 private:
  void OnDownloaded(std::optional<std::string> body);

  std::unique_ptr<network::SimpleURLLoader> loader_;
  std::string host_;
  Callback callback_;
};

}  // namespace boring

#endif  // COMPONENTS_BORING_SCAM_QUAD9_BLOCK_CHECKER_H_
