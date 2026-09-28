// Copyright 2026 boring. BSD style license.

#ifndef COMPONENTS_BORING_ADBLOCK_ELEMENT_PICKER_H_
#define COMPONENTS_BORING_ADBLOCK_ELEMENT_PICKER_H_

#include "components/boring/adblock/mojom/adblock.mojom-forward.h"
#include "mojo/public/cpp/bindings/pending_associated_receiver.h"

namespace content {
class RenderFrameHost;
class WebContents;
}  // namespace content

namespace boring {

// Lets the person pick an element on the page in `contents` and block
// it: the toolbar shield's "Block this element".
//
// Starts an overlay in the page's main frame, in the cosmetic filters'
// isolated world, which the page can neither see into nor script.
// Hovering highlights an element, a click picks it, and a small panel
// shows the selector it made (the id if it is stable, else stable class
// names, else nth-of-type steps) with Block and Cancel. Escape cancels;
// the arrow keys widen or narrow the pick. On Block the element is
// hidden at once and "host##selector" is added to the profile's custom
// rules (prefs::kBoringCustomRules), so it stays hidden on later visits.
//
// Does nothing for a page that is not http or https, or while ad
// blocking is off for this run. UI thread.
void StartElementPicker(content::WebContents* contents);

// Test only: true when the browser runs with --boring-element-picker-test.
// Only then may a page ask for the picker itself (ElementPickerTestHook
// in adblock.mojom), which is how smoke_picker.py drives it.
bool IsElementPickerTestHookEnabled();

// Binds the test hook for `frame`. Does nothing unless the switch is on.
void BindElementPickerTestHook(
    content::RenderFrameHost* frame,
    mojo::PendingAssociatedReceiver<mojom::ElementPickerTestHook> receiver);

}  // namespace boring

#endif  // COMPONENTS_BORING_ADBLOCK_ELEMENT_PICKER_H_
