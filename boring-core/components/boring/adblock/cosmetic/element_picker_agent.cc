// Copyright 2026 boring. BSD style license.

#include "components/boring/adblock/cosmetic/element_picker_agent.h"

#include <iterator>
#include <string>
#include <utility>

#include "base/functional/bind.h"
#include "components/boring/adblock/cosmetic/cosmetic_css.h"
#include "components/boring/adblock/cosmetic/element_picker_script.h"
#include "content/public/renderer/render_frame.h"
#include "gin/arguments.h"
#include "gin/function_template.h"
#include "third_party/blink/public/common/associated_interfaces/associated_interface_provider.h"
#include "third_party/blink/public/common/associated_interfaces/associated_interface_registry.h"
#include "third_party/blink/public/platform/scheduler/web_agent_group_scheduler.h"
#include "third_party/blink/public/platform/web_string.h"
#include "third_party/blink/public/web/web_css_origin.h"
#include "third_party/blink/public/web/web_document.h"
#include "third_party/blink/public/web/web_local_frame.h"
#include "third_party/blink/public/web/web_script_source.h"
#include "url/gurl.h"
#include "v8/include/v8.h"

namespace boring {

namespace {

constexpr char kHideDeclarations[] = "display:none !important";

// The address fragment that asks for the picker in a test run.
constexpr char kTestFragment[] = "boring-test-element-picker";

}  // namespace

ElementPickerAgent::ElementPickerAgent(content::RenderFrame& render_frame,
                                       int32_t isolated_world_id)
    : render_frame_(render_frame), isolated_world_id_(isolated_world_id) {
  // Weak, because the registry belongs to the frame and could in theory
  // be asked for a binding while the frame is going away.
  render_frame.GetAssociatedInterfaceRegistry()
      ->AddInterface<mojom::ElementPicker>(base::BindRepeating(
          &ElementPickerAgent::Bind, weak_factory_.GetWeakPtr()));
}

ElementPickerAgent::~ElementPickerAgent() {
  if (pending_) {
    std::move(pending_).Run(std::string());
  }
}

void ElementPickerAgent::Bind(
    mojo::PendingAssociatedReceiver<mojom::ElementPicker> receiver) {
  receivers_.Add(this, std::move(receiver));
}

void ElementPickerAgent::DidCreateNewDocument() {
  document_weak_factory_.InvalidateWeakPtrs();
  if (pending_) {
    std::move(pending_).Run(std::string());
  }
}

void ElementPickerAgent::DidFinishLoad() {
  const GURL url = render_frame_->GetWebFrame()->GetDocument().Url();
  if (!url.SchemeIsHTTPOrHTTPS() || url.GetRef() != kTestFragment) {
    return;
  }
  if (!test_hook_.is_bound()) {
    render_frame_->GetRemoteAssociatedInterfaces()->GetInterface(&test_hook_);
  }
  test_hook_->StartPicker();
}

void ElementPickerAgent::Start(StartCallback callback) {
  // One pick at a time: a second request while the panel is up changes
  // nothing on the page and is answered as cancelled.
  if (pending_) {
    std::move(callback).Run(std::string());
    return;
  }
  const GURL url = render_frame_->GetWebFrame()->GetDocument().Url();
  if (!url.SchemeIsHTTPOrHTTPS()) {
    std::move(callback).Run(std::string());
    return;
  }
  pending_ = std::move(callback);
  if (!RunPickerScript() && pending_) {
    std::move(pending_).Run(std::string());
  }
}

bool ElementPickerAgent::RunPickerScript() {
  blink::WebLocalFrame* frame = render_frame_->GetWebFrame();
  v8::Isolate* isolate = frame->GetAgentGroupScheduler()->Isolate();
  v8::HandleScope handle_scope(isolate);

  // Same shape as the cosmetic filter script: the source evaluates to a
  // function, and the native callback is handed to it directly.
  v8::Local<v8::Value> script_function =
      frame->ExecuteScriptInIsolatedWorldAndReturnValue(
          isolated_world_id_,
          blink::WebScriptSource(
              blink::WebString::FromUtf8(kElementPickerScript)),
          blink::BackForwardCacheAware::kAllow);
  if (script_function.IsEmpty() || !script_function->IsFunction()) {
    return false;
  }
  v8::Local<v8::Context> context =
      frame->GetScriptContextFromWorldId(isolate, isolated_world_id_);
  if (context.IsEmpty()) {
    return false;
  }
  v8::Context::Scope context_scope(context);

  v8::Local<v8::Function> done;
  if (!gin::CreateFunctionTemplate(
           isolate, base::BindRepeating(&ElementPickerAgent::OnPickerDone,
                                        document_weak_factory_.GetWeakPtr()))
           ->GetFunction(context)
           .ToLocal(&done)) {
    return false;
  }
  v8::Local<v8::Value> argv[] = {done};
  // The person asked for this, so it runs where the site's own scripts
  // are turned off too.
  frame->CallFunctionEvenIfScriptDisabled(
      script_function.As<v8::Function>(), v8::Undefined(isolate),
      static_cast<int>(std::size(argv)), argv);
  return true;
}

void ElementPickerAgent::OnPickerDone(gin::Arguments* args) {
  std::string selector;
  if (!args->GetNext(&selector)) {
    selector.clear();
  }
  Finish(selector);
}

void ElementPickerAgent::Finish(const std::string& selector) {
  if (!pending_) {
    return;
  }
  // Only a selector that is safe as a stylesheet rule goes anywhere. The
  // browser checks again before it writes the rule.
  if (selector.empty() || !IsSafeSelector(selector)) {
    std::move(pending_).Run(std::string());
    return;
  }
  // Hidden now, not on the next visit: user origin, like the filters.
  render_frame_->GetWebFrame()->GetDocument().InsertStyleSheet(
      blink::WebString::FromUtf8(BuildRules({selector}, kHideDeclarations)),
      /*key=*/nullptr, blink::WebCssOrigin::kUser);
  std::move(pending_).Run(selector);
}

}  // namespace boring
