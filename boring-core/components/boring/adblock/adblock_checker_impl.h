// Copyright 2026 boring. BSD style license.

#ifndef COMPONENTS_BORING_ADBLOCK_ADBLOCK_CHECKER_IMPL_H_
#define COMPONENTS_BORING_ADBLOCK_ADBLOCK_CHECKER_IMPL_H_

#include "base/memory/scoped_refptr.h"
#include "components/boring/adblock/blocking_off_sites.h"
#include "components/boring/adblock/mojom/adblock.mojom.h"
#include "mojo/public/cpp/bindings/pending_receiver.h"

namespace boring {

// Answers ad block questions from renderers. Lives in the browser
// process on a background sequence, self owned by its mojo pipe.
class AdblockCheckerImpl : public mojom::AdblockChecker {
 public:
  // Binds a new instance on a background sequence. Safe to call from
  // any thread. `off_sites` is the renderer's profile's list of sites
  // with blocking turned off.
  static void Bind(scoped_refptr<BlockingOffSites> off_sites,
                   mojo::PendingReceiver<mojom::AdblockChecker> receiver);

  explicit AdblockCheckerImpl(scoped_refptr<BlockingOffSites> off_sites);
  ~AdblockCheckerImpl() override;

  // mojom::AdblockChecker:
  void Check(const GURL& url,
             const GURL& initiator,
             const std::string& request_type,
             const GURL& top_frame_url,
             CheckCallback callback) override;
  void Clone(mojo::PendingReceiver<mojom::AdblockChecker> receiver) override;

 private:
  const scoped_refptr<BlockingOffSites> off_sites_;
};

}  // namespace boring

#endif  // COMPONENTS_BORING_ADBLOCK_ADBLOCK_CHECKER_IMPL_H_
