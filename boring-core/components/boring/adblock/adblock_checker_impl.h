// Copyright 2026 boring. BSD style license.

#ifndef COMPONENTS_BORING_ADBLOCK_ADBLOCK_CHECKER_IMPL_H_
#define COMPONENTS_BORING_ADBLOCK_ADBLOCK_CHECKER_IMPL_H_

#include "base/memory/scoped_refptr.h"
#include "components/boring/adblock/adblock_service.h"
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
  // with blocking turned off, `lists` its optional lists.
  // `render_process_id` is the renderer asking, so a $redirect stub is
  // only offered once that renderer's requests go through the proxy
  // that serves it (AdblockRedirectProxy).
  static void Bind(int render_process_id,
                   scoped_refptr<BlockingOffSites> off_sites,
                   scoped_refptr<ProfileLists> lists,
                   mojo::PendingReceiver<mojom::AdblockChecker> receiver);

  AdblockCheckerImpl(int render_process_id,
                     scoped_refptr<BlockingOffSites> off_sites,
                     scoped_refptr<ProfileLists> lists);
  ~AdblockCheckerImpl() override;

  // mojom::AdblockChecker:
  void Check(const GURL& url,
             const GURL& initiator,
             const std::string& request_type,
             const GURL& top_frame_url,
             CheckCallback callback) override;
  void Clone(mojo::PendingReceiver<mojom::AdblockChecker> receiver) override;

 private:
  const int render_process_id_;
  const scoped_refptr<BlockingOffSites> off_sites_;
  const scoped_refptr<ProfileLists> lists_;
};

}  // namespace boring

#endif  // COMPONENTS_BORING_ADBLOCK_ADBLOCK_CHECKER_IMPL_H_
