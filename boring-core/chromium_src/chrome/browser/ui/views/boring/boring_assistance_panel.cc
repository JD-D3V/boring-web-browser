// Copyright 2026 boring. BSD style license.

#include "chrome/browser/ui/views/boring/boring_assistance_panel.h"

#include <map>
#include <memory>
#include <optional>
#include <string>
#include <utility>
#include <vector>

#include "base/command_line.h"
#include "base/functional/bind.h"
#include "base/memory/raw_ptr.h"
#include "base/no_destructor.h"
#include "base/notreached.h"
#include "base/strings/strcat.h"
#include "base/strings/utf_string_conversions.h"
#include "base/values.h"
#include "chrome/browser/profiles/profile.h"
#include "chrome/browser/ui/actions/chrome_action_id.h"
#include "chrome/browser/ui/browser_actions.h"
#include "chrome/browser/ui/browser_web_contents_delegate/browser_web_contents_delegate.h"
#include "chrome/browser/ui/browser_window/public/browser_window_interface.h"
#include "chrome/browser/ui/browser_window/public/global_browser_collection.h"
#include "chrome/browser/ui/side_panel/side_panel_entry.h"
#include "chrome/browser/ui/side_panel/side_panel_entry_id.h"
#include "chrome/browser/ui/side_panel/side_panel_entry_key.h"
#include "chrome/browser/ui/side_panel/side_panel_entry_scope.h"
#include "chrome/browser/ui/side_panel/side_panel_enums.h"
#include "chrome/browser/ui/side_panel/side_panel_registry.h"
#include "chrome/browser/ui/side_panel/side_panel_ui.h"
#include "chrome/browser/ui/tabs/tab_strip_model.h"
#include "chrome/common/chrome_isolated_world_ids.h"
#include "components/boring/assistance/assistance_session.h"
#include "components/boring/assistance/assistance_test_hook.h"
#include "components/tabs/public/tab_interface.h"
#include "components/vector_icons/vector_icons.h"
#include "content/public/browser/navigation_controller.h"
#include "content/public/browser/page_navigator.h"
#include "content/public/browser/render_frame_host.h"
#include "content/public/browser/web_contents.h"
#include "content/public/browser/web_contents_delegate.h"
#include "content/public/common/referrer.h"
#include "ui/actions/actions.h"
#include "ui/base/clipboard/clipboard_buffer.h"
#include "ui/base/clipboard/scoped_clipboard_writer.h"
#include "ui/base/metadata/metadata_header_macros.h"
#include "ui/base/metadata/metadata_impl_macros.h"
#include "ui/base/models/image_model.h"
#include "ui/base/page_transition_types.h"
#include "ui/base/window_open_disposition.h"
#include "ui/color/color_id.h"
#include "ui/events/event.h"
#include "ui/events/keycodes/keyboard_codes.h"
#include "ui/gfx/geometry/insets.h"
#include "ui/gfx/text_constants.h"
#include "ui/views/accessibility/view_accessibility.h"
#include "ui/views/controls/button/md_text_button.h"
#include "ui/views/controls/label.h"
#include "ui/views/controls/textarea/textarea.h"
#include "ui/views/controls/textfield/textfield.h"
#include "ui/views/controls/textfield/textfield_controller.h"
#include "ui/views/controls/webview/webview.h"
#include "ui/views/layout/box_layout.h"
#include "ui/views/view.h"
#include "url/gurl.h"
#include "url/url_constants.h"

namespace boring {

namespace {

using State = AssistanceSession::State;

constexpr char kGeminiUrl[] = "https://gemini.google.com/app";

SidePanelEntry::Key PanelKey() {
  return SidePanelEntry::Key(SidePanelEntryId::kAssistant);
}

// Gemini, or under the test switch a fake one on this machine, so a test
// never sends anything anywhere.
GURL StartUrl() {
  const base::CommandLine& command_line =
      *base::CommandLine::ForCurrentProcess();
  if (command_line.HasSwitch(kAssistanceTestSwitch)) {
    const GURL test_url(
        command_line.GetSwitchValueASCII(kAssistanceProviderForTestSwitch));
    if (test_url.is_valid() && test_url.SchemeIs(url::kHttpScheme) &&
        test_url.host() == "127.0.0.1" && test_url.has_port()) {
      return test_url;
    }
  }
  return GURL(kGeminiUrl);
}

const char* StateName(State state) {
  switch (state) {
    case State::kIdle:
      return "idle";
    case State::kCapturing:
      return "capturing";
    case State::kReady:
      return "ready";
    case State::kWaitingForSend:
      return "waitingForSend";
    case State::kWaitingForReply:
      return "waitingForReply";
    case State::kAnswered:
      return "answered";
    case State::kFound:
      return "found";
    case State::kStale:
      return "stale";
    case State::kFailed:
      return "failed";
  }
  NOTREACHED();
}

// The question bar above the chat site, and the chat site itself. One per
// tab: the entry is tab-scoped, so switching tabs hides it with its tab
// and never points it at another page. Closing the panel destroys it, and
// the session with it.
class AssistancePanelView : public views::View,
                            public views::TextfieldController,
                            public content::WebContentsDelegate {
  METADATA_HEADER(AssistancePanelView, views::View)

 public:
  explicit AssistancePanelView(tabs::TabInterface* tab);
  AssistancePanelView(const AssistancePanelView&) = delete;
  AssistancePanelView& operator=(const AssistancePanelView&) = delete;
  ~AssistancePanelView() override;

  // The buttons' own actions, also driven by the test hook.
  void PressAsk();
  void PressPreview();
  void PressFind();
  void PressShowMe();
  void PressMatch(size_t index);
  void PressCopy();

  // Test only.
  void SetQuestionForTesting(const std::u16string& text);
  void PressSendForTesting();
  base::DictValue StateForTesting() const;

  // Panels alive now, by tab, for the test hook.
  static std::map<tabs::TabInterface*, AssistancePanelView*>& Live();

 private:
  void SetPreviewing(bool previewing);
  void UpdateUi();
  std::u16string StatusText() const;
  std::u16string FailureText(const std::string& reason) const;
  void OpenInBrowser(const GURL& url);

  // views::TextfieldController:
  bool HandleKeyEvent(views::Textfield* sender,
                      const ui::KeyEvent& key_event) override;

  // content::WebContentsDelegate, for the chat page:
  content::WebContents* OpenURLFromTab(
      content::WebContents* source,
      const content::OpenURLParams& params,
      base::OnceCallback<void(content::NavigationHandle&)>
          navigation_handle_callback) override;
  content::WebContents* AddNewContents(
      content::WebContents* source,
      std::unique_ptr<content::WebContents> new_contents,
      const GURL& target_url,
      WindowOpenDisposition disposition,
      const blink::mojom::WindowFeatures& window_features,
      bool user_gesture,
      bool* was_blocked) override;
  bool HandleKeyboardEvent(content::WebContents* source,
                           const input::NativeWebKeyboardEvent& event) override;

  const raw_ptr<tabs::TabInterface> tab_;
  const AssistanceProvider provider_;
  bool previewing_ = false;

  raw_ptr<views::Label> title_ = nullptr;
  raw_ptr<views::Textfield> question_ = nullptr;
  raw_ptr<views::MdTextButton> ask_ = nullptr;
  raw_ptr<views::MdTextButton> preview_ = nullptr;
  raw_ptr<views::Label> status_ = nullptr;
  raw_ptr<views::View> matches_ = nullptr;
  raw_ptr<views::MdTextButton> show_me_ = nullptr;
  raw_ptr<views::MdTextButton> copy_ = nullptr;
  raw_ptr<views::Textarea> preview_text_ = nullptr;
  raw_ptr<views::WebView> web_view_ = nullptr;

  // Declared last so it goes first: its destructor still talks to the
  // chat page, which the WebView child owns.
  std::unique_ptr<AssistanceSession> session_;
};

AssistancePanelView::AssistancePanelView(tabs::TabInterface* tab)
    : tab_(tab), provider_(GeminiProvider(StartUrl())) {
  auto* layout = SetLayoutManager(std::make_unique<views::BoxLayout>(
      views::BoxLayout::Orientation::kVertical, gfx::Insets(12), 8));
  layout->set_cross_axis_alignment(
      views::BoxLayout::CrossAxisAlignment::kStretch);

  title_ = AddChildView(std::make_unique<views::Label>());
  title_->SetHorizontalAlignment(gfx::ALIGN_LEFT);
  title_->SetElideBehavior(gfx::ELIDE_TAIL);

  question_ = AddChildView(std::make_unique<views::Textfield>());
  question_->SetPlaceholderText(u"Where do I create an API key?");
  question_->GetViewAccessibility().SetName(u"Question");
  question_->set_controller(this);

  // The one button that sends page text says so on its face.
  ask_ = AddChildView(std::make_unique<views::MdTextButton>(
      base::BindRepeating(&AssistancePanelView::PressAsk,
                          base::Unretained(this)),
      base::StrCat({u"Ask ", provider_.name, u" with this page"})));
  ask_->SetStyle(ui::ButtonStyle::kProminent);

  auto* row = AddChildView(std::make_unique<views::View>());
  row->SetLayoutManager(std::make_unique<views::BoxLayout>(
      views::BoxLayout::Orientation::kHorizontal, gfx::Insets(), 8));
  row->AddChildView(std::make_unique<views::MdTextButton>(
      base::BindRepeating(&AssistancePanelView::PressFind,
                          base::Unretained(this)),
      u"Find on page"));
  preview_ = row->AddChildView(std::make_unique<views::MdTextButton>(
      base::BindRepeating(&AssistancePanelView::PressPreview,
                          base::Unretained(this)),
      u"Preview"));

  status_ = AddChildView(std::make_unique<views::Label>());
  status_->SetMultiLine(true);
  status_->SetHorizontalAlignment(gfx::ALIGN_LEFT);

  matches_ = AddChildView(std::make_unique<views::View>());
  matches_->SetLayoutManager(std::make_unique<views::BoxLayout>(
      views::BoxLayout::Orientation::kVertical, gfx::Insets(), 4,
      /*collapse_margins_spacing=*/false));

  show_me_ = AddChildView(std::make_unique<views::MdTextButton>(
      base::BindRepeating(&AssistancePanelView::PressShowMe,
                          base::Unretained(this)),
      u"Show me"));
  copy_ = AddChildView(std::make_unique<views::MdTextButton>(
      base::BindRepeating(&AssistancePanelView::PressCopy,
                          base::Unretained(this)),
      u"Copy text"));

  preview_text_ = AddChildView(std::make_unique<views::Textarea>());
  preview_text_->SetReadOnly(true);
  preview_text_->GetViewAccessibility().SetName(u"Text that would be shared");
  preview_text_->SetVisible(false);
  layout->SetFlexForView(preview_text_, 1);

  content::WebContents* source = tab->GetContents();
  web_view_ = AddChildView(std::make_unique<views::WebView>(
      Profile::FromBrowserContext(source->GetBrowserContext())));
  layout->SetFlexForView(web_view_, 1);
  content::WebContents* chat = web_view_->GetWebContents();
  chat->SetDelegate(this);
  web_view_->LoadInitialURL(provider_.start_url);

  // The person presses the chat site's own Send: the last act before
  // anything reaches the provider is theirs.
  session_ = std::make_unique<AssistanceSession>(
      source, chat, provider_, /*press_send=*/false,
      base::BindRepeating(&AssistancePanelView::UpdateUi,
                          base::Unretained(this)));
  Live()[tab] = this;
  UpdateUi();
}

AssistancePanelView::~AssistancePanelView() {
  Live().erase(tab_.get());
  session_.reset();
  web_view_->GetWebContents()->SetDelegate(nullptr);
}

// static
std::map<tabs::TabInterface*, AssistancePanelView*>&
AssistancePanelView::Live() {
  static base::NoDestructor<std::map<tabs::TabInterface*, AssistancePanelView*>>
      panels;
  return *panels;
}

void AssistancePanelView::PressAsk() {
  // After a preview, share exactly what was shown rather than reading the
  // page again.
  if (previewing_ && session_->state() == State::kReady) {
    session_->Share();
  } else {
    session_->Ask(question_->GetText());
  }
  SetPreviewing(false);
}

void AssistancePanelView::PressPreview() {
  if (previewing_) {
    SetPreviewing(false);
    return;
  }
  session_->Prepare(question_->GetText());
  SetPreviewing(true);
}

void AssistancePanelView::PressFind() {
  SetPreviewing(false);
  session_->Find(question_->GetText());
}

void AssistancePanelView::PressShowMe() {
  session_->ShowMe();
}

void AssistancePanelView::PressMatch(size_t index) {
  session_->ShowMatch(index);
}

void AssistancePanelView::PressCopy() {
  // The fallback when the chat site's layout changed: the person pastes it.
  ui::ScopedClipboardWriter(ui::ClipboardBuffer::kCopyPaste)
      .WriteText(base::UTF8ToUTF16(session_->prompt()));
}

void AssistancePanelView::SetQuestionForTesting(const std::u16string& text) {
  question_->SetText(text);
}

void AssistancePanelView::PressSendForTesting() {
  // Stands in for the person's own press of the chat site's Send button.
  web_view_->GetWebContents()
      ->GetPrimaryMainFrame()
      ->ExecuteJavaScriptInIsolatedWorld(
          u"document.querySelector('button[aria-label=\"Send message\"]')"
          u"?.click(); true",
          base::NullCallback(), ISOLATED_WORLD_ID_CHROME_INTERNAL);
}

base::DictValue AssistancePanelView::StateForTesting() const {
  base::DictValue out;
  out.Set("sourceUrl", tab_->GetContents()->GetLastCommittedURL().spec());
  out.Set("providerUrl",
          web_view_->GetWebContents()->GetLastCommittedURL().spec());
  out.Set("state", StateName(session_->state()));
  out.Set("reason", session_->reason());
  out.Set("canShowMe", session_->CanShowMe());
  out.Set("prompt", session_->prompt());
  out.Set("status", base::UTF16ToUTF8(status_->GetText()));
  out.Set("previewing", previewing_);
  base::ListValue matches;
  for (const std::string& label : session_->match_labels()) {
    matches.Append(label);
  }
  out.Set("matches", std::move(matches));
  return out;
}

void AssistancePanelView::SetPreviewing(bool previewing) {
  previewing_ = previewing;
  preview_text_->SetVisible(previewing);
  web_view_->SetVisible(!previewing);
  preview_->SetText(previewing ? base::StrCat({u"Back to ", provider_.name})
                               : std::u16string(u"Preview"));
  UpdateUi();
}

void AssistancePanelView::UpdateUi() {
  title_->SetText(base::StrCat(
      {u"Ask about ",
       base::UTF8ToUTF16(tab_->GetContents()->GetLastCommittedURL().host())}));
  const State state = session_->state();
  const std::u16string status = StatusText();
  status_->SetText(status);
  status_->SetVisible(!status.empty());
  ask_->SetEnabled(state != State::kCapturing);
  show_me_->SetVisible(session_->CanShowMe());
  copy_->SetVisible(state == State::kFailed && !session_->prompt().empty());
  preview_text_->SetText(base::UTF8ToUTF16(session_->prompt()));

  // Rebuilt only from session changes, never from inside one of these
  // buttons' own presses: ShowMatch() answers asynchronously.
  matches_->RemoveAllChildViews();
  if (state == State::kFound) {
    const std::vector<std::string>& labels = session_->match_labels();
    for (size_t i = 0; i < labels.size(); ++i) {
      matches_->AddChildView(std::make_unique<views::MdTextButton>(
          base::BindRepeating(&AssistancePanelView::PressMatch,
                              base::Unretained(this), i),
          base::UTF8ToUTF16(labels[i])));
    }
  }
  matches_->SetVisible(!matches_->children().empty());
  InvalidateLayout();
}

std::u16string AssistancePanelView::StatusText() const {
  const std::string& reason = session_->reason();
  const std::u16string& name = provider_.name;
  switch (session_->state()) {
    case State::kIdle:
      return provider_.history_note;
    case State::kCapturing:
      return u"Reading this page";
    case State::kReady:
      return u"Nothing sent yet";
    case State::kWaitingForSend:
      return base::StrCat({u"Press Send in ", name});
    case State::kWaitingForReply:
      return reason == "slow" ? base::StrCat({name, u" is taking longer"})
                              : base::StrCat({name, u" is answering"});
    case State::kAnswered:
      if (reason == "stale_target") {
        return u"That button changed. Ask again.";
      }
      return session_->CanShowMe() ? std::u16string()
                                   : u"No button to show for this answer";
    case State::kFound:
      if (reason == "stale_target") {
        return u"That button changed. Search again.";
      }
      return reason == "no_match" ? u"No matching button on this page"
                                  : std::u16string();
    case State::kStale:
      return u"Page changed. Ask again to use the new page.";
    case State::kFailed:
      return FailureText(reason);
  }
  NOTREACHED();
}

std::u16string AssistancePanelView::FailureText(
    const std::string& reason) const {
  const std::u16string& name = provider_.name;
  if (reason == "signed_out") {
    return base::StrCat({u"Sign in to ", name});
  }
  if (reason == "existing_draft") {
    return base::StrCat({u"Clear the text in ", name, u" first"});
  }
  if (reason == "generating") {
    return base::StrCat({u"Wait for ", name, u" to finish"});
  }
  if (reason == "unsupported_page") {
    return u"Not available on this page";
  }
  if (reason == "empty_question") {
    return u"Type a question first";
  }
  if (reason == "question_too_long") {
    return u"That question is too long";
  }
  if (reason == "capture_failed") {
    return u"Couldn't read this page";
  }
  if (reason == "provider_not_ready" || reason == "unexpected_destination") {
    return base::StrCat({u"Go back to a ", name, u" chat first"});
  }
  if (reason == "chat_reloaded" || reason == "disposed") {
    return base::StrCat({name, u" reloaded. Ask again."});
  }
  if (reason == "tab_closed") {
    return std::u16string();
  }
  // Every other reason is the adapter failing closed on a layout it does
  // not recognise; the Copy button is the way through.
  return base::StrCat({name, u" changed. Copy the text and paste it in."});
}

void AssistancePanelView::OpenInBrowser(const GURL& url) {
  BrowserWindowInterface* browser = tab_->GetBrowserWindowInterface();
  if (!browser || !url.is_valid()) {
    return;
  }
  browser->OpenURL(
      content::OpenURLParams(url, content::Referrer(),
                             WindowOpenDisposition::NEW_FOREGROUND_TAB,
                             ui::PAGE_TRANSITION_LINK,
                             /*is_renderer_initiated=*/false),
      /*navigation_handle_callback=*/{});
}

bool AssistancePanelView::HandleKeyEvent(views::Textfield* sender,
                                         const ui::KeyEvent& key_event) {
  if (key_event.type() == ui::EventType::kKeyPressed &&
      key_event.key_code() == ui::VKEY_RETURN) {
    PressAsk();
    return true;
  }
  return false;
}

content::WebContents* AssistancePanelView::OpenURLFromTab(
    content::WebContents* source,
    const content::OpenURLParams& params,
    base::OnceCallback<void(content::NavigationHandle&)>
        navigation_handle_callback) {
  if (params.disposition == WindowOpenDisposition::CURRENT_TAB) {
    source->GetController().LoadURLWithParams(
        content::NavigationController::LoadURLParams(params));
    return source;
  }
  // Links out of the chat (sources, help pages) open as ordinary tabs,
  // never inside the panel.
  OpenInBrowser(params.url);
  return nullptr;
}

content::WebContents* AssistancePanelView::AddNewContents(
    content::WebContents* source,
    std::unique_ptr<content::WebContents> new_contents,
    const GURL& target_url,
    WindowOpenDisposition disposition,
    const blink::mojom::WindowFeatures& window_features,
    bool user_gesture,
    bool* was_blocked) {
  // The popup itself is dropped; what it wanted to show opens as a tab.
  OpenInBrowser(target_url);
  return nullptr;
}

bool AssistancePanelView::HandleKeyboardEvent(
    content::WebContents* source,
    const input::NativeWebKeyboardEvent& event) {
  // Browser shortcuts (new tab, close tab) still work with focus in here.
  BrowserWindowInterface* browser = tab_->GetBrowserWindowInterface();
  content::WebContentsDelegate* delegate =
      browser ? BrowserWebContentsDelegate::From(browser) : nullptr;
  return delegate && delegate->HandleKeyboardEvent(source, event);
}

BEGIN_METADATA(AssistancePanelView)
END_METADATA

std::unique_ptr<views::View> CreatePanel(tabs::TabInterface* tab,
                                         SidePanelEntryScope& scope) {
  return std::make_unique<AssistancePanelView>(tab);
}

// Chromium names an action for kAssistant but never creates one, and the
// side panel header reads its title and icon from that action with no
// null check, so showing the entry without it crashes the browser. Create
// it once per window. False when the window has no actions to hold it.
bool EnsureAction(BrowserWindowInterface* browser) {
  BrowserActions* browser_actions = BrowserActions::From(browser);
  actions::ActionItem* root =
      browser_actions ? browser_actions->root_action_item() : nullptr;
  if (!root) {
    return false;
  }
  if (actions::ActionManager::Get().FindAction(kActionSidePanelShowAssistant,
                                               root)) {
    return true;
  }
  root->AddChild(
      actions::ActionItem::Builder(
          base::BindRepeating(
              [](BrowserWindowInterface* window, actions::ActionItem* item,
                 actions::ActionInvocationContext context) {
                ToggleAssistancePanel(window);
              },
              base::Unretained(browser)))
          .SetActionId(kActionSidePanelShowAssistant)
          .SetText(u"Ask Gemini")
          .SetTooltipText(u"Ask Gemini")
          .SetImage(ui::ImageModel::FromVectorIcon(vector_icons::kChatSparkIcon,
                                                   ui::kColorIcon))
          .SetProperty(actions::kActionItemPinnableKey,
                       std::underlying_type_t<actions::ActionPinnableState>(
                           actions::ActionPinnableState::kNotPinnable))
          .Build());
  return true;
}

}  // namespace

bool CanAssist(tabs::TabInterface* tab) {
  content::WebContents* contents = tab ? tab->GetContents() : nullptr;
  if (!contents) {
    return false;
  }
  Profile* profile = Profile::FromBrowserContext(contents->GetBrowserContext());
  return !profile->IsOffTheRecord() && !profile->IsGuestSession() &&
         contents->GetLastCommittedURL().SchemeIsHTTPOrHTTPS();
}

void ToggleAssistancePanel(BrowserWindowInterface* browser) {
  tabs::TabInterface* tab =
      browser ? browser->GetActiveTabInterface() : nullptr;
  SidePanelUI* side_panel = browser ? SidePanelUI::From(browser) : nullptr;
  if (!tab || !side_panel) {
    return;
  }
  if (side_panel->IsSidePanelEntryShowing(PanelKey())) {
    side_panel->Close(SidePanelEntryHideReason::kSidePanelClosed,
                      /*suppress_animations=*/false);
    return;
  }
  if (!CanAssist(tab) || !EnsureAction(browser)) {
    return;
  }
  SidePanelRegistry* registry = SidePanelRegistry::From(tab);
  if (!registry) {
    return;
  }
  if (!registry->GetEntryForKey(PanelKey())) {
    // Showing an unregistered key is a CHECK failure, so register first.
    registry->Register(std::make_unique<SidePanelEntry>(
        PanelKey(), base::BindRepeating(&CreatePanel, base::Unretained(tab)),
        /*default_content_width_callback=*/base::NullCallback()));
  }
  side_panel->Show(SidePanelEntryId::kAssistant, /*open_trigger=*/std::nullopt,
                   /*suppress_animations=*/false);
}

base::Value RunAssistanceTestCommand(content::WebContents* page,
                                     const base::ListValue& args) {
  if (!base::CommandLine::ForCurrentProcess()->HasSwitch(
          kAssistanceTestSwitch) ||
      args.empty() || !args[0].is_string()) {
    return base::Value();
  }
  // The tab the last "open" chose. A weak pointer, so a closed tab reads
  // as no panel rather than a dangling one.
  static base::NoDestructor<base::WeakPtr<tabs::TabInterface>> target;
  const std::string& command = args[0].GetString();
  const std::string text =
      args.size() > 1 && args[1].is_string() ? args[1].GetString() : "";

  if (command == "open") {
    // The test drives from a new tab page in another window, so the source
    // is found by address and made the active tab of its own window.
    BrowserWindowInterface* found_browser = nullptr;
    int found_index = -1;
    GlobalBrowserCollection::GetInstance()->ForEach(
        [&](BrowserWindowInterface* browser) {
          TabStripModel* tabs = browser->GetTabStripModel();
          for (int i = 0; i < tabs->count(); ++i) {
            content::WebContents* contents =
                tabs->GetTabAtIndex(i)->GetContents();
            if (!text.empty() && contents &&
                contents->GetLastCommittedURL().spec().find(text) !=
                    std::string::npos) {
              found_browser = browser;
              found_index = i;
              return false;
            }
          }
          return true;
        });
    base::DictValue out;
    out.Set("found", found_browser != nullptr);
    if (found_browser) {
      found_browser->GetTabStripModel()->ActivateTabAt(found_index);
      tabs::TabInterface* tab =
          found_browser->GetTabStripModel()->GetTabAtIndex(found_index);
      *target = tab->GetWeakPtr();
      if (!AssistancePanelView::Live().contains(tab)) {
        ToggleAssistancePanel(found_browser);
      }
      out.Set("available", CanAssist(tab));
    }
    return base::Value(std::move(out));
  }

  tabs::TabInterface* tab = target->get();
  AssistancePanelView* panel = nullptr;
  if (tab) {
    auto it = AssistancePanelView::Live().find(tab);
    panel = it == AssistancePanelView::Live().end() ? nullptr : it->second;
  }
  if (command == "state") {
    base::DictValue out = panel ? panel->StateForTesting() : base::DictValue();
    out.Set("open", panel != nullptr);
    SidePanelUI* side_panel =
        tab && tab->GetBrowserWindowInterface()
            ? SidePanelUI::From(tab->GetBrowserWindowInterface())
            : nullptr;
    out.Set("showing",
            side_panel && side_panel->IsSidePanelEntryShowing(PanelKey()));
    out.Set("available", tab && CanAssist(tab));
    return base::Value(std::move(out));
  }
  if (!panel) {
    return base::Value(false);
  }
  if (command == "setQuestion") {
    panel->SetQuestionForTesting(base::UTF8ToUTF16(text));
  } else if (command == "preview") {
    panel->PressPreview();
  } else if (command == "share") {
    panel->PressAsk();
  } else if (command == "find") {
    panel->PressFind();
  } else if (command == "showMatch") {
    const int index =
        args.size() > 1 && args[1].is_int() ? args[1].GetInt() : 0;
    panel->PressMatch(static_cast<size_t>(index < 0 ? 0 : index));
  } else if (command == "showMe") {
    panel->PressShowMe();
  } else if (command == "pressSend") {
    panel->PressSendForTesting();
  } else if (command == "close") {
    // Close only: the toolbar's toggle would open a closed panel again.
    BrowserWindowInterface* browser = tab->GetBrowserWindowInterface();
    SidePanelUI* side_panel = browser ? SidePanelUI::From(browser) : nullptr;
    if (side_panel && side_panel->IsSidePanelEntryShowing(PanelKey())) {
      side_panel->Close(SidePanelEntryHideReason::kSidePanelClosed,
                        /*suppress_animations=*/true);
    }
  } else {
    return base::Value(false);
  }
  return base::Value(true);
}

}  // namespace boring
