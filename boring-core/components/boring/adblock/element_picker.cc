// Copyright 2026 boring. BSD style license.

#include "components/boring/adblock/element_picker.h"

#include <memory>
#include <string>
#include <utility>

#include "base/command_line.h"
#include "base/functional/bind.h"
#include "base/logging.h"
#include "base/memory/weak_ptr.h"
#include "base/strings/strcat.h"
#include "components/boring/adblock/adblock_service.h"
#include "components/boring/adblock/custom_rules.h"
#include "components/boring/adblock/mojom/adblock.mojom.h"
#include "content/public/browser/global_routing_id.h"
#include "content/public/browser/render_frame_host.h"
#include "content/public/browser/web_contents.h"
#include "mojo/public/cpp/bindings/associated_remote.h"
#include "mojo/public/cpp/bindings/self_owned_associated_receiver.h"
#include "third_party/blink/public/common/associated_interfaces/associated_interface_provider.h"
#include "url/gurl.h"

namespace boring {

namespace {

constexpr char kTestHookSwitch[] = "boring-element-picker-test";

// A selector the renderer made is still text from a process that runs
// web content. These are what we refuse to write into a rule; anything
// else that is not a valid selector simply matches nothing.
constexpr size_t kMaxSelectorLength = 2048;

bool IsAcceptableSelector(const std::string& selector) {
  if (selector.empty() || selector.size() > kMaxSelectorLength) {
    return false;
  }
  for (char c : selector) {
    // A line break would start a second rule; a brace would end the
    // hiding rule early in the stylesheet it becomes.
    if (static_cast<unsigned char>(c) < 0x20 || c == '{' || c == '}') {
      return false;
    }
  }
  return true;
}

void OnPicked(base::WeakPtr<content::WebContents> contents,
              std::string host,
              mojo::AssociatedRemote<mojom::ElementPicker> picker,
              const std::string& selector) {
  if (!contents || selector.empty()) {
    return;  // Cancelled, or the tab went away.
  }
  if (!IsAcceptableSelector(selector)) {
    LOG(WARNING) << "boring: the element picker sent a selector we will not "
                    "use";
    return;
  }
  const std::string rule = base::StrCat({host, "##", selector});
  if (!CheckCustomRules(rule).empty()) {
    LOG(WARNING) << "boring: the picked rule does not parse: " << rule;
    return;
  }
  AddCustomRule(contents->GetBrowserContext(), rule);
}

class ElementPickerTestHookImpl : public mojom::ElementPickerTestHook {
 public:
  explicit ElementPickerTestHookImpl(content::GlobalRenderFrameHostId frame_id)
      : frame_id_(frame_id) {}

  ElementPickerTestHookImpl(const ElementPickerTestHookImpl&) = delete;
  ElementPickerTestHookImpl& operator=(const ElementPickerTestHookImpl&) =
      delete;

  ~ElementPickerTestHookImpl() override = default;

  // mojom::ElementPickerTestHook:
  void StartPicker() override {
    content::RenderFrameHost* frame =
        content::RenderFrameHost::FromID(frame_id_);
    if (!frame || !frame->IsInPrimaryMainFrame()) {
      return;
    }
    StartElementPicker(content::WebContents::FromRenderFrameHost(frame));
  }

 private:
  const content::GlobalRenderFrameHostId frame_id_;
};

}  // namespace

void StartElementPicker(content::WebContents* contents) {
  if (!contents || AdblockService::IsDisabled()) {
    return;
  }
  content::RenderFrameHost* frame = contents->GetPrimaryMainFrame();
  const GURL url = frame->GetLastCommittedURL();
  if (!url.SchemeIsHTTPOrHTTPS() || !frame->IsRenderFrameLive()) {
    return;
  }
  // The rule is for the host the page is on, as uBO's picker writes it.
  // An IPv6 literal cannot be written into a cosmetic rule.
  std::string host = url.GetHost();
  if (host.empty() || host.front() == '[') {
    return;
  }
  mojo::AssociatedRemote<mojom::ElementPicker> picker;
  frame->GetRemoteAssociatedInterfaces()->GetInterface(&picker);
  // The remote rides along with its own reply so the pipe stays open
  // until the person has chosen; closing the tab drops both.
  mojom::ElementPicker* raw_picker = picker.get();
  raw_picker->Start(base::BindOnce(&OnPicked, contents->GetWeakPtr(),
                                   std::move(host), std::move(picker)));
}

bool IsElementPickerTestHookEnabled() {
  return base::CommandLine::ForCurrentProcess()->HasSwitch(kTestHookSwitch);
}

void BindElementPickerTestHook(
    content::RenderFrameHost* frame,
    mojo::PendingAssociatedReceiver<mojom::ElementPickerTestHook> receiver) {
  if (!IsElementPickerTestHookEnabled()) {
    return;
  }
  mojo::MakeSelfOwnedAssociatedReceiver(
      std::make_unique<ElementPickerTestHookImpl>(frame->GetGlobalId()),
      std::move(receiver));
}

}  // namespace boring
