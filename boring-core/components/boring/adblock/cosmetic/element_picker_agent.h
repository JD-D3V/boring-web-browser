// Copyright 2026 boring. BSD style license.

#ifndef COMPONENTS_BORING_ADBLOCK_COSMETIC_ELEMENT_PICKER_AGENT_H_
#define COMPONENTS_BORING_ADBLOCK_COSMETIC_ELEMENT_PICKER_AGENT_H_

#include <cstdint>
#include <string>

#include "base/memory/raw_ref.h"
#include "base/memory/weak_ptr.h"
#include "components/boring/adblock/mojom/adblock.mojom.h"
#include "mojo/public/cpp/bindings/associated_receiver_set.h"
#include "mojo/public/cpp/bindings/associated_remote.h"
#include "mojo/public/cpp/bindings/pending_associated_receiver.h"

namespace content {
class RenderFrame;
}  // namespace content

namespace gin {
class Arguments;
}  // namespace gin

namespace boring {

// The renderer half of the element picker (see element_picker.h in the
// browser half) for one main frame. Runs element_picker.js in the
// cosmetic filter isolated world when the browser asks, hides the
// picked element with a user stylesheet at once, and answers with the
// selector. Owned by the frame's CosmeticFilterAgent, which forwards
// the frame events below.
class ElementPickerAgent : public mojom::ElementPicker {
 public:
  ElementPickerAgent(content::RenderFrame& render_frame,
                     int32_t isolated_world_id);
  ElementPickerAgent(const ElementPickerAgent&) = delete;
  ElementPickerAgent& operator=(const ElementPickerAgent&) = delete;
  ~ElementPickerAgent() override;

  // A new document replaces the one being picked from: the pick is
  // cancelled.
  void DidCreateNewDocument();

  // Test only: a page whose address ends in #boring-test-element-picker
  // asks the browser to start the picker on it. The browser ignores the
  // request unless it runs with --boring-element-picker-test.
  void DidFinishLoad();

  // mojom::ElementPicker:
  void Start(StartCallback callback) override;

 private:
  void Bind(mojo::PendingAssociatedReceiver<mojom::ElementPicker> receiver);

  // Runs the picker script. False when it could not be started.
  bool RunPickerScript();

  // The script's one native call, with the selector or ''.
  void OnPickerDone(gin::Arguments* args);

  // Hides the element (unless `selector` is empty) and answers.
  void Finish(const std::string& selector);

  const raw_ref<content::RenderFrame> render_frame_;
  const int32_t isolated_world_id_;

  // Declared before the receivers, so it outlives them: a reply dropped
  // after its pipe closed is fine, one dropped before is a mojo error.
  StartCallback pending_;
  mojo::AssociatedReceiverSet<mojom::ElementPicker> receivers_;
  mojo::AssociatedRemote<mojom::ElementPickerTestHook> test_hook_;

  // Invalidated with every new document, so a late answer from a page
  // that is gone cannot finish a pick on the next one.
  base::WeakPtrFactory<ElementPickerAgent> document_weak_factory_{this};
  base::WeakPtrFactory<ElementPickerAgent> weak_factory_{this};
};

}  // namespace boring

#endif  // COMPONENTS_BORING_ADBLOCK_COSMETIC_ELEMENT_PICKER_AGENT_H_
