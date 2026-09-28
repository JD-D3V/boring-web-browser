// Copyright 2026 boring. BSD style license.

#include "components/boring/adblock/cosmetic/cosmetic_filter_agent.h"

#include <iterator>
#include <memory>
#include <optional>
#include <string>
#include <utility>
#include <vector>

#include "base/functional/bind.h"
#include "base/json/json_reader.h"
#include "base/json/json_writer.h"
#include "base/rand_util.h"
#include "base/strings/string_number_conversions.h"
#include "base/values.h"
#include "components/boring/adblock/cosmetic/cosmetic_css.h"
#include "components/boring/adblock/cosmetic/cosmetic_scripts.h"
#include "components/boring/adblock/cosmetic/element_picker_agent.h"
#include "components/boring/adblock/renderer/adblock_renderer_throttle.h"
#include "content/public/renderer/render_frame.h"
#include "gin/arguments.h"
#include "gin/converter.h"
#include "gin/function_template.h"
#include "third_party/blink/public/common/thread_safe_browser_interface_broker_proxy.h"
#include "third_party/blink/public/platform/platform.h"
#include "third_party/blink/public/platform/scheduler/web_agent_group_scheduler.h"
#include "third_party/blink/public/platform/web_isolated_world_info.h"
#include "third_party/blink/public/platform/web_string.h"
#include "third_party/blink/public/web/web_css_origin.h"
#include "third_party/blink/public/web/web_document.h"
#include "third_party/blink/public/web/web_local_frame.h"
#include "third_party/blink/public/web/web_script_source.h"
#include "v8/include/v8.h"

namespace boring {

namespace {

constexpr char kHideDeclarations[] = "display:none !important";

// Limits on one native call from the isolated script. The script stays
// well under them; they only bound what reaches the browser.
constexpr size_t kMaxNamesPerCall = 1000;
constexpr size_t kMaxNameLength = 256;

void SetUpIsolatedWorld(int32_t world_id) {
  static bool done = false;
  if (done) {
    return;
  }
  done = true;
  blink::WebIsolatedWorldInfo info;
  info.human_readable_name =
      blink::WebString::FromUtf8("Boring Browser cosmetic filters");
  blink::SetIsolatedWorldInfo(world_id, info);
}

// The page in the tab. A main frame is its own; for a subframe the top
// frame may live in another process, and only its origin is known here.
GURL TopFrameUrl(blink::WebLocalFrame* frame) {
  if (!frame->Parent()) {
    return frame->GetDocument().Url();
  }
  return AdblockRendererThrottle::TopFrameUrlFor(frame->GetLocalFrameToken());
}

// An attribute name the page is unlikely to use or guess, one per
// document, that the procedural filters set to hide or style a match.
std::string RandomAttributeName() {
  return "bb" + base::NumberToString(base::RandUint64());
}

// Keeps only the strings a class name or id could be.
std::vector<std::string> CapNames(std::vector<std::string> names) {
  if (names.size() > kMaxNamesPerCall) {
    names.resize(kMaxNamesPerCall);
  }
  std::erase_if(names, [](const std::string& name) {
    return name.empty() || name.size() > kMaxNameLength;
  });
  return names;
}

struct ProceduralSetup {
  // Rules for the user stylesheet: plain CSS filters with a style, and
  // the attributes the isolated script sets.
  std::string css;
  // Filters the isolated script has to run, with the attribute each sets.
  base::ListValue filters;
};

// Sorts adblock-rust's procedural and action filters into what CSS alone
// can do and what needs the isolated script.
ProceduralSetup SetUpProcedural(const std::vector<std::string>& actions,
                                const std::string& hide_attr) {
  ProceduralSetup setup;
  int style_count = 0;
  for (const std::string& json : actions) {
    std::optional<base::DictValue> filter =
        base::JSONReader::ReadDict(json, base::JSON_PARSE_RFC);
    if (!filter) {
      continue;
    }
    const base::ListValue* selector = filter->FindList("selector");
    if (!selector || selector->empty()) {
      continue;
    }
    const base::DictValue* action = filter->FindDict("action");
    const std::string* action_type =
        action ? action->FindString("type") : nullptr;
    if (action && !action_type) {
      continue;
    }
    const std::string* style =
        action_type && *action_type == "style" ? action->FindString("arg")
                                               : nullptr;
    if (action_type && *action_type == "style" &&
        (!style || !IsSafeDeclarations(*style))) {
      continue;
    }

    // A plain selector with a style needs no script at all.
    const base::DictValue* first = selector->front().GetIfDict();
    const std::string* first_type = first ? first->FindString("type") : nullptr;
    const std::string* first_arg = first ? first->FindString("arg") : nullptr;
    if (selector->size() == 1 && first_type && first_arg &&
        *first_type == "css-selector" && (!action || style)) {
      setup.css += BuildRules({*first_arg}, style ? *style : kHideDeclarations);
      continue;
    }

    std::string attr;
    if (!action) {
      attr = hide_attr;
    } else if (style) {
      attr = hide_attr + "s" + base::NumberToString(style_count++);
      setup.css += "[" + attr + "]{" + *style + "}\n";
    }
    filter->Set("attr", attr);
    setup.filters.Append(std::move(*filter));
  }
  if (!setup.filters.empty()) {
    setup.css += "[" + hide_attr + "]{" + kHideDeclarations + "}\n";
  }
  return setup;
}

}  // namespace

CosmeticFilterAgent::CosmeticFilterAgent(content::RenderFrame* render_frame,
                                         int32_t isolated_world_id)
    : content::RenderFrameObserver(render_frame),
      content::RenderFrameObserverTracker<CosmeticFilterAgent>(render_frame),
      isolated_world_id_(isolated_world_id) {
  SetUpIsolatedWorld(isolated_world_id_);
  // "Block this element" picks from the page in the tab, so only the
  // main frame gets a picker.
  if (render_frame->IsMainFrame() && !render_frame->IsInFencedFrameTree()) {
    element_picker_ = std::make_unique<ElementPickerAgent>(*render_frame,
                                                           isolated_world_id_);
  }
}

CosmeticFilterAgent::~CosmeticFilterAgent() = default;

// static
bool CosmeticFilterAgent::RunScriptsAtDocumentStart(
    content::RenderFrame* render_frame) {
  CosmeticFilterAgent* agent = Get(render_frame);
  if (!agent) {
    return true;
  }
  base::WeakPtr<CosmeticFilterAgent> alive = agent->weak_factory_.GetWeakPtr();
  agent->ApplyAtDocumentStart();
  // The agent goes away with its frame.
  return !!alive;
}

void CosmeticFilterAgent::DidCreateNewDocument() {
  applied_ = false;
  top_frame_url_ = GURL();
  exceptions_.clear();
  document_weak_factory_.InvalidateWeakPtrs();
  if (element_picker_) {
    element_picker_->DidCreateNewDocument();
  }
}

void CosmeticFilterAgent::DidFinishLoad() {
  if (element_picker_) {
    element_picker_->DidFinishLoad();
  }
}

void CosmeticFilterAgent::OnDestruct() {
  delete this;
}

void CosmeticFilterAgent::ApplyAtDocumentStart() {
  if (applied_) {
    return;
  }
  applied_ = true;
  blink::WebLocalFrame* frame = render_frame()->GetWebFrame();
  const GURL url = frame->GetDocument().Url();
  if (!url.SchemeIsHTTPOrHTTPS()) {
    return;
  }
  mojom::CosmeticFilters* cosmetic_filters = GetCosmeticFilters();
  if (!cosmetic_filters) {
    return;
  }
  top_frame_url_ = TopFrameUrl(frame);

  // The one call that holds the page up: rules have to be in place before
  // the first script or paint.
  mojom::UrlCosmeticResourcesPtr resources;
  if (!cosmetic_filters->GetUrlResources(url, top_frame_url_, &resources) ||
      !resources) {
    return;
  }
  exceptions_ = std::move(resources->exceptions);

  const std::string hide_attr = RandomAttributeName();
  ProceduralSetup procedural =
      SetUpProcedural(resources->procedural_actions, hide_attr);
  InsertStyleSheet(BuildRules(resources->hide_selectors, kHideDeclarations) +
                   procedural.css);

  base::WeakPtr<CosmeticFilterAgent> alive = weak_factory_.GetWeakPtr();
  if (!resources->generichide || !procedural.filters.empty()) {
    base::DictValue config;
    config.Set("generic", !resources->generichide);
    config.Set("filters", std::move(procedural.filters));
    std::optional<std::string> config_json = base::WriteJson(config);
    if (config_json) {
      StartIsolatedScript(*config_json);
    }
    if (!alive) {
      return;
    }
  }
  // Last, so nothing a scriptlet does can get in the way of the rest.
  RunScriptlets(resources->injected_script);
}

void CosmeticFilterAgent::InsertStyleSheet(const std::string& css) {
  if (css.empty()) {
    return;
  }
  // User origin, so the page's own !important rules cannot win.
  render_frame()->GetWebFrame()->GetDocument().InsertStyleSheet(
      blink::WebString::FromUtf8(css), /*key=*/nullptr,
      blink::WebCssOrigin::kUser);
}

void CosmeticFilterAgent::StartIsolatedScript(const std::string& config_json) {
  blink::WebLocalFrame* frame = render_frame()->GetWebFrame();
  v8::Isolate* isolate = frame->GetAgentGroupScheduler()->Isolate();
  v8::HandleScope handle_scope(isolate);

  // The script evaluates to a function, so the native callback and the
  // config are handed to it directly and never sit on a global.
  v8::Local<v8::Value> script_function =
      frame->ExecuteScriptInIsolatedWorldAndReturnValue(
          isolated_world_id_,
          blink::WebScriptSource(
              blink::WebString::FromUtf8(kCosmeticIsolatedScript)),
          blink::BackForwardCacheAware::kAllow);
  if (script_function.IsEmpty() || !script_function->IsFunction()) {
    return;
  }
  v8::Local<v8::Context> context =
      frame->GetScriptContextFromWorldId(isolate, isolated_world_id_);
  if (context.IsEmpty()) {
    return;
  }
  v8::Context::Scope context_scope(context);

  v8::Local<v8::Function> send_class_ids;
  if (!gin::CreateFunctionTemplate(
           isolate,
           base::BindRepeating(&CosmeticFilterAgent::OnClassIdsSeen,
                               document_weak_factory_.GetWeakPtr()))
           ->GetFunction(context)
           .ToLocal(&send_class_ids)) {
    return;
  }
  v8::Local<v8::Value> argv[] = {send_class_ids,
                                 gin::StringToV8(isolate, config_json)};
  // Runs even where the person turned JavaScript off for the site: this
  // is the browser's own script in its own world, and hiding ads is part
  // of how the page should look.
  frame->CallFunctionEvenIfScriptDisabled(
      script_function.As<v8::Function>(), v8::Undefined(isolate),
      static_cast<int>(std::size(argv)), argv);
}

void CosmeticFilterAgent::RunScriptlets(const std::string& script) {
  if (script.empty()) {
    return;
  }
  // adblock-rust already wraps each scriptlet call in try/catch. The
  // function keeps the helpers they share off the page's globals, where
  // they could clash with the page's own names. uBO's scriptlets all
  // read a shared scriptletGlobals object that uBO's own wrapper
  // declares; without it the first scriptlet on the page throws.
  render_frame()->GetWebFrame()->ExecuteScript(
      blink::WebScriptSource(blink::WebString::FromUtf8(
          "(function() {\nconst scriptletGlobals = {};\n" + script +
          "\n})();")));
}

void CosmeticFilterAgent::OnClassIdsSeen(gin::Arguments* args) {
  std::vector<std::string> classes;
  std::vector<std::string> ids;
  if (!args->GetNext(&classes) || !args->GetNext(&ids)) {
    return;
  }
  classes = CapNames(std::move(classes));
  ids = CapNames(std::move(ids));
  if (classes.empty() && ids.empty()) {
    return;
  }
  mojom::CosmeticFilters* cosmetic_filters = GetCosmeticFilters();
  if (!cosmetic_filters) {
    return;
  }
  cosmetic_filters->GetHiddenClassIdSelectors(
      classes, ids, exceptions_, top_frame_url_,
      base::BindOnce(&CosmeticFilterAgent::OnHiddenClassIdSelectors,
                     document_weak_factory_.GetWeakPtr()));
}

void CosmeticFilterAgent::OnHiddenClassIdSelectors(
    const std::vector<std::string>& selectors) {
  InsertStyleSheet(BuildRules(selectors, kHideDeclarations));
}

mojom::CosmeticFilters* CosmeticFilterAgent::GetCosmeticFilters() {
  if (!cosmetic_filters_.is_bound()) {
    // Bound per render process in the browser, beside AdblockChecker.
    blink::Platform::Current()->GetBrowserInterfaceBroker()->GetInterface(
        cosmetic_filters_.BindNewPipeAndPassReceiver());
    cosmetic_filters_.reset_on_disconnect();
  }
  return cosmetic_filters_.is_bound() ? cosmetic_filters_.get() : nullptr;
}

}  // namespace boring
