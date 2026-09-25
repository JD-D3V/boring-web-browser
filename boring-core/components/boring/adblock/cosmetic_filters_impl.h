// Copyright 2026 boring. BSD style license.

#ifndef COMPONENTS_BORING_ADBLOCK_COSMETIC_FILTERS_IMPL_H_
#define COMPONENTS_BORING_ADBLOCK_COSMETIC_FILTERS_IMPL_H_

#include <string>
#include <vector>

#include "base/memory/scoped_refptr.h"
#include "components/boring/adblock/adblock_service.h"
#include "components/boring/adblock/blocking_off_sites.h"
#include "components/boring/adblock/mojom/adblock.mojom.h"
#include "mojo/public/cpp/bindings/pending_receiver.h"

class GURL;

namespace boring {

// Answers renderers' cosmetic filter questions: what to hide and which
// scriptlets to run in a frame. Lives in the browser process on its own
// background sequence, self owned by its mojo pipe, so a renderer's sync
// call at document start never waits behind the network checks.
class CosmeticFiltersImpl : public mojom::CosmeticFilters {
 public:
  // Binds a new instance. Safe to call from any thread. `off_sites` and
  // `lists` are the renderer's profile's, as for AdblockCheckerImpl.
  static void Bind(scoped_refptr<BlockingOffSites> off_sites,
                   scoped_refptr<ProfileLists> lists,
                   mojo::PendingReceiver<mojom::CosmeticFilters> receiver);

  CosmeticFiltersImpl(scoped_refptr<BlockingOffSites> off_sites,
                      scoped_refptr<ProfileLists> lists);

  CosmeticFiltersImpl(const CosmeticFiltersImpl&) = delete;
  CosmeticFiltersImpl& operator=(const CosmeticFiltersImpl&) = delete;

  ~CosmeticFiltersImpl() override;

  // mojom::CosmeticFilters:
  void GetUrlResources(const GURL& frame_url,
                       const GURL& top_frame_url,
                       GetUrlResourcesCallback callback) override;
  void GetHiddenClassIdSelectors(
      const std::vector<std::string>& classes,
      const std::vector<std::string>& ids,
      const std::vector<std::string>& exceptions,
      const GURL& top_frame_url,
      GetHiddenClassIdSelectorsCallback callback) override;

 private:
  // False when the person turned blocking off for the page in the tab,
  // or for this run.
  bool IsOn(const GURL& top_frame_url) const;

  const scoped_refptr<BlockingOffSites> off_sites_;
  const scoped_refptr<ProfileLists> lists_;
};

}  // namespace boring

#endif  // COMPONENTS_BORING_ADBLOCK_COSMETIC_FILTERS_IMPL_H_
