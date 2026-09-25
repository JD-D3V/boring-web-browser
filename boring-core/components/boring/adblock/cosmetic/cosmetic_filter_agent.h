// Copyright 2026 boring. BSD style license.

#ifndef COMPONENTS_BORING_ADBLOCK_COSMETIC_COSMETIC_FILTER_AGENT_H_
#define COMPONENTS_BORING_ADBLOCK_COSMETIC_COSMETIC_FILTER_AGENT_H_

#include <cstdint>
#include <string>
#include <vector>

#include "base/memory/weak_ptr.h"
#include "components/boring/adblock/mojom/adblock.mojom.h"
#include "content/public/renderer/render_frame_observer.h"
#include "content/public/renderer/render_frame_observer_tracker.h"
#include "mojo/public/cpp/bindings/remote.h"
#include "url/gurl.h"

namespace gin {
class Arguments;
}  // namespace gin

namespace boring {

// Applies the ad blocker's cosmetic filters to one frame's documents:
// hides elements with a user stylesheet, runs scriptlets in the page's
// main world before the page's own scripts, and starts a script in an
// isolated world that asks for generic hiding rules as class names and
// ids appear and applies procedural filters. One per frame, subframes
// included; owned by its RenderFrame. Does nothing for documents that
// are not http or https, or when the browser says blocking is off.
class CosmeticFilterAgent
    : public content::RenderFrameObserver,
      public content::RenderFrameObserverTracker<CosmeticFilterAgent> {
 public:
  // `isolated_world_id` is the world reserved for the filter script.
  CosmeticFilterAgent(content::RenderFrame* render_frame,
                      int32_t isolated_world_id);
  CosmeticFilterAgent(const CosmeticFilterAgent&) = delete;
  CosmeticFilterAgent& operator=(const CosmeticFilterAgent&) = delete;
  ~CosmeticFilterAgent() override;

  // Call from ContentRendererClient::RunScriptsAtDocumentStart: the
  // document element exists and no page script has run yet. Returns
  // false if the frame was destroyed meanwhile, in which case the caller
  // must not use `render_frame` again.
  static bool RunScriptsAtDocumentStart(content::RenderFrame* render_frame);

 private:
  // content::RenderFrameObserver:
  void DidCreateNewDocument() override;
  void OnDestruct() override;

  void ApplyAtDocumentStart();
  void InsertStyleSheet(const std::string& css);
  void StartIsolatedScript(const std::string& config_json);
  void RunScriptlets(const std::string& script);

  // The isolated script's one native call: new class names and ids.
  void OnClassIdsSeen(gin::Arguments* args);
  void OnHiddenClassIdSelectors(const std::vector<std::string>& selectors);

  mojom::CosmeticFilters* GetCosmeticFilters();

  const int32_t isolated_world_id_;
  mojo::Remote<mojom::CosmeticFilters> cosmetic_filters_;

  // Per document. RunScriptsAtDocumentStart can come twice for one
  // document (document.write can insert a second <html>), and the
  // filters must be applied once.
  bool applied_ = false;
  GURL top_frame_url_;
  std::vector<std::string> exceptions_;

  // Invalidated for every new document, so an answer that arrives late
  // never lands on the next page.
  base::WeakPtrFactory<CosmeticFilterAgent> document_weak_factory_{this};
  base::WeakPtrFactory<CosmeticFilterAgent> weak_factory_{this};
};

}  // namespace boring

#endif  // COMPONENTS_BORING_ADBLOCK_COSMETIC_COSMETIC_FILTER_AGENT_H_
