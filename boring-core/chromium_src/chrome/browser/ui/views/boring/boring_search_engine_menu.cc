// Copyright 2026 boring. BSD style license.

#include "chrome/browser/ui/views/boring/boring_search_engine_menu.h"

#include <algorithm>
#include <memory>
#include <string>
#include <utility>
#include <vector>

#include "base/command_line.h"
#include "base/functional/bind.h"
#include "base/functional/callback_helpers.h"
#include "base/memory/ptr_util.h"
#include "base/no_destructor.h"
#include "base/strings/utf_string_conversions.h"
#include "base/task/sequenced_task_runner.h"
#include "cc/paint/paint_flags.h"
#include "chrome/browser/profiles/profile.h"
#include "chrome/browser/ui/browser.h"
#include "chrome/browser/ui/browser_window/public/browser_window_interface.h"
#include "chrome/browser/ui/browser_window/public/global_browser_collection.h"
#include "chrome/browser/ui/omnibox/omnibox_controller.h"
#include "chrome/browser/ui/omnibox/omnibox_edit_model.h"
#include "chrome/browser/ui/view_ids.h"
#include "chrome/browser/ui/views/controls/hover_button.h"
#include "chrome/browser/ui/views/frame/browser_view.h"
#include "chrome/browser/ui/views/location_bar/location_bar_view.h"
#include "chrome/browser/ui/views/location_bar/location_icon_view.h"
#include "chrome/browser/ui/views/omnibox/omnibox_view_views.h"
#include "chrome/browser/ui/views/page_info/page_info_bubble_view_base.h"
#include "components/boring/newtab/search_engine_menu.h"
#include "components/boring/search/search_engines.h"
#include "components/omnibox/browser/autocomplete_match.h"
#include "components/omnibox/browser/omnibox_client.h"
#include "components/search_engines/template_url.h"
#include "components/search_engines/template_url_service.h"
#include "components/vector_icons/vector_icons.h"
#include "content/public/browser/host_zoom_map.h"
#include "content/public/browser/page_navigator.h"
#include "content/public/browser/render_widget_host_view.h"
#include "content/public/browser/web_contents.h"
#include "third_party/blink/public/common/page/page_zoom.h"
#include "third_party/metrics_proto/omnibox_event.pb.h"
#include "ui/accessibility/ax_enums.mojom.h"
#include "ui/base/models/image_model.h"
#include "ui/base/page_transition_types.h"
#include "ui/base/window_open_disposition.h"
#include "ui/color/color_id.h"
#include "ui/color/color_provider.h"
#include "ui/compositor/layer.h"
#include "ui/compositor/layer_delegate.h"
#include "ui/compositor/paint_recorder.h"
#include "ui/events/event.h"
#include "ui/events/keycodes/keyboard_codes.h"
#include "ui/gfx/animation/tween.h"
#include "ui/gfx/canvas.h"
#include "ui/gfx/color_utils.h"
#include "ui/gfx/geometry/rect_conversions.h"
#include "ui/gfx/geometry/rect_f.h"
#include "ui/gfx/image/image.h"
#include "ui/gfx/skia_paint_util.h"
#include "ui/views/accessibility/view_accessibility.h"
#include "ui/views/animation/ink_drop.h"
#include "ui/views/border.h"
#include "ui/views/bubble/bubble_border.h"
#include "ui/views/bubble/bubble_dialog_delegate_view.h"
#include "ui/views/controls/button/label_button.h"
#include "ui/views/controls/button/md_text_button.h"
#include "ui/views/controls/label.h"
#include "ui/views/controls/scroll_view.h"
#include "ui/views/focus/focus_manager.h"
#include "ui/views/layout/box_layout.h"
#include "ui/views/style/platform_style.h"
#include "ui/views/style/typography.h"
#include "ui/views/view.h"
#include "ui/views/view_tracker.h"
#include "ui/views/view_utils.h"
#include "url/gurl.h"

namespace {

// The list stays one comfortable column; a long list scrolls.
constexpr int kMenuWidth = 300;
constexpr int kMaxListHeight = 360;
constexpr int kIconSize = 16;
// How tall the rolled edge is while the menu unrolls.
constexpr int kCurlHeight = 10;

std::unique_ptr<BoringSearchEngineMenu>& CurrentMenu() {
  static base::NoDestructor<std::unique_ptr<BoringSearchEngineMenu>> menu;
  return *menu;
}

LocationBarView* BarFor(views::View* icon) {
  return icon ? views::AsViewClass<LocationBarView>(icon->parent()) : nullptr;
}

// The address bar of the window `page` is in, found through its Browser
// rather than the view tree: `page`'s own native view is detached while
// its tab sits in the background, so a lookup rooted at GetNativeView()
// finds nothing once the tab is not the one showing.
LocationBarView* BarForPage(content::WebContents* page) {
  if (!page) {
    return nullptr;
  }
  BrowserWindowInterface* window =
      GlobalBrowserCollection::GetInstance()->FindBrowserWithTab(page);
  Browser* browser = window ? window->GetBrowserForMigrationOnly() : nullptr;
  BrowserView* view =
      browser ? BrowserView::GetBrowserViewForBrowser(browser) : nullptr;
  return view ? view->GetLocationBarView() : nullptr;
}

TemplateURLService* ServiceFor(LocationBarView* bar) {
  return bar ? bar->GetOmniboxController()->client()->GetTemplateURLService()
             : nullptr;
}

// The address a search for `query` with `engine` goes to, or an empty
// GURL for anything that is not a web address.
GURL SearchUrl(const TemplateURLService* service,
               const TemplateURL* engine,
               const std::u16string& query) {
  GURL url(engine->url_ref().ReplaceSearchTerms(
      TemplateURLRef::SearchTermsArgs(query), service->search_terms_data()));
  return url.is_valid() && url.SchemeIsHTTPOrHTTPS() ? url : GURL();
}

// A choice made from the address bar. With words typed, search for them
// with that engine now; with none, put the address bar in that engine's
// keyword mode, so the next search goes to it. Either way it is this
// once: the default is not touched.
void PickFromLocationBar(views::ViewTracker* tracker,
                         const std::u16string& query,
                         const std::u16string& keyword) {
  LocationBarView* bar = views::AsViewClass<LocationBarView>(tracker->view());
  TemplateURLService* service = ServiceFor(bar);
  const TemplateURL* engine =
      service ? service->GetTemplateURLForKeyword(keyword) : nullptr;
  if (!engine) {
    return;
  }
  if (query.empty()) {
    bar->FocusLocation(/*is_user_initiated=*/true,
                       /*clear_focus_if_failed=*/false);
    bar->GetOmniboxController()->edit_model()->EnterKeywordMode(
        metrics::OmniboxEventProto::CLICK_HINT_VIEW, engine, std::u16string());
    return;
  }
  const GURL url = SearchUrl(service, engine, query);
  content::WebContents* contents = bar->GetWebContents();
  if (!url.is_valid() || !contents) {
    return;
  }
  bar->omnibox_view()->RevertAll();
  contents->OpenURL(
      content::OpenURLParams(
          url, content::Referrer(), WindowOpenDisposition::CURRENT_TAB,
          ui::PageTransitionFromInt(ui::PAGE_TRANSITION_GENERATED |
                                    ui::PAGE_TRANSITION_FROM_ADDRESS_BAR),
          /*is_renderer_initiated=*/false),
      /*navigation_handle_callback=*/{});
  contents->Focus();
}

std::u16string DefaultEngineName(LocationBarView* bar) {
  TemplateURLService* service = ServiceFor(bar);
  const TemplateURL* engine =
      service ? service->GetDefaultSearchProvider() : nullptr;
  return engine ? engine->short_name() : std::u16string();
}

}  // namespace

// The rolled paper edge. A band across the card at the edge being
// unrolled: shade under the fold, a highlight across the roll and a
// darker foot, so it reads as a curl without drawing attention.
class BoringSearchEngineMenu::Curl : public ui::LayerDelegate {
 public:
  Curl(SkColor paper, bool dark)
      : layer_(ui::Layer::Create(ui::LAYER_TEXTURED)) {
    layer_->set_delegate(this);
    layer_->SetFillsBoundsOpaquely(false);
    layer_->SetName("BoringScrollCurl");
    shade_ =
        color_utils::AlphaBlend(SK_ColorBLACK, paper, dark ? 0.35f : 0.14f);
    highlight_ =
        color_utils::AlphaBlend(SK_ColorWHITE, paper, dark ? 0.10f : 0.55f);
    paper_ = paper;
  }

  Curl(const Curl&) = delete;
  Curl& operator=(const Curl&) = delete;

  ~Curl() override { layer_->set_delegate(nullptr); }

  ui::Layer* layer() { return layer_.get(); }

  // ui::LayerDelegate:
  void OnPaintLayer(const ui::PaintContext& context) override {
    const gfx::Size size = layer_->size();
    ui::PaintRecorder recorder(context, size);
    gfx::Canvas* canvas = recorder.canvas();
    const int fold = size.height() / 2;
    cc::PaintFlags flags;
    flags.setAntiAlias(true);
    flags.setShader(gfx::CreateGradientShader(
        gfx::Point(0, 0), gfx::Point(0, fold), paper_, shade_));
    canvas->DrawRect(gfx::Rect(0, 0, size.width(), fold), flags);
    flags.setShader(gfx::CreateGradientShader(
        gfx::Point(0, fold), gfx::Point(0, size.height()), highlight_, shade_));
    canvas->DrawRoundRect(
        gfx::Rect(0, fold, size.width(), size.height() - fold),
        (size.height() - fold) / 2, flags);
  }
  void OnDeviceScaleFactorChanged(float old_device_scale_factor,
                                  float new_device_scale_factor) override {}

 private:
  std::unique_ptr<ui::Layer> layer_;
  SkColor paper_;
  SkColor shade_;
  SkColor highlight_;
};

BoringSearchEngineMenu::Row::Row() = default;
BoringSearchEngineMenu::Row::Row(Row&&) = default;
BoringSearchEngineMenu::Row& BoringSearchEngineMenu::Row::operator=(Row&&) =
    default;
BoringSearchEngineMenu::Row::~Row() = default;

// static
bool BoringSearchEngineMenu::IsAvailableFor(LocationIconView* icon) {
  LocationBarView* bar = BarFor(icon);
  if (!bar || !bar->browser() || !bar->omnibox_view() ||
      !bar->IsEditingOrEmpty()) {
    return false;
  }
  const OmniboxEditModel* model = bar->GetOmniboxController()->edit_model();
  // The same test OmniboxView::GetIcon() makes: while the page's own
  // icon is shown, the icon is about the page, and it stays page info.
  if (model->ShouldShowCurrentPageIcon() || model->is_keyword_selected()) {
    return false;
  }
  // Empty is the new tab page. With text, only a search: a typed address
  // shows that site's icon, not an engine.
  return bar->omnibox_view()->GetText().empty() ||
         AutocompleteMatch::IsSearchType(model->CurrentMatch().type);
}

// static
bool BoringSearchEngineMenu::ShowForLocationIcon(LocationIconView* icon) {
  if (!IsAvailableFor(icon)) {
    return false;
  }
  LocationBarView* bar = BarFor(icon);
  const bool typing =
      bar->GetOmniboxController()->edit_model()->user_input_in_progress();
  const std::u16string query =
      typing ? bar->omnibox_view()->GetText() : std::u16string();
  return Show(
      bar, icon, gfx::Rect(),
      base::BindRepeating(
          &PickFromLocationBar,
          base::Owned(std::make_unique<views::ViewTracker>(bar)), query),
      base::DoNothing(), base::DoNothing());
}

// static
bool BoringSearchEngineMenu::IsShowingFor(const LocationIconView* icon) {
  BoringSearchEngineMenu* menu = GetShowing();
  return menu && menu->anchor_view_ == icon;
}

// static
void BoringSearchEngineMenu::UpdateLocationIcon(LocationIconView* icon) {
  views::ViewAccessibility& accessibility = icon->GetViewAccessibility();
  if (!IsAvailableFor(icon)) {
    accessibility.SetHasPopup(ax::mojom::HasPopup::kFalse);
    LocationBarView* bar = BarFor(icon);
    // Chromium leaves the icon inert while editing; give that back if
    // this was the engine button a moment ago (a query became an
    // address as it was typed).
    if (bar && bar->IsEditingOrEmpty() &&
        icon->GetFocusBehavior() != views::View::FocusBehavior::NEVER) {
      views::InkDrop::Get(icon)->SetMode(views::InkDropHost::InkDropMode::OFF);
      icon->SetFocusBehavior(views::View::FocusBehavior::NEVER);
    }
    return;
  }
  // Only on a change: setting the mode rebuilds the ink drop.
  if (icon->GetFocusBehavior() == views::View::FocusBehavior::NEVER) {
    views::InkDrop::Get(icon)->SetMode(views::InkDropHost::InkDropMode::ON);
    icon->SetFocusBehavior(views::PlatformStyle::kDefaultFocusBehavior);
  }
  const std::u16string name = DefaultEngineName(BarFor(icon));
  accessibility.SetRole(ax::mojom::Role::kButton);
  accessibility.SetName(name.empty() ? u"Search engines"
                                     : u"Search engine: " + name);
  accessibility.SetHasPopup(ax::mojom::HasPopup::kDialog);
  icon->SetTooltipText(u"Choose a search engine");
}

// static
bool BoringSearchEngineMenu::Show(LocationBarView* bar,
                                  views::View* anchor_view,
                                  const gfx::Rect& anchor_rect,
                                  PickCallback on_pick,
                                  base::RepeatingClosure on_default_changed,
                                  base::OnceClosure on_closed) {
  if (!bar || !bar->GetWidget()) {
    return false;
  }
  // One at a time. A menu still rolling up goes at once.
  CurrentMenu().reset();
  auto menu = base::WrapUnique(new BoringSearchEngineMenu(
      bar, std::move(on_pick), std::move(on_default_changed),
      std::move(on_closed)));
  if (!menu->LoadRows()) {
    return false;
  }
  CurrentMenu() = std::move(menu);
  CurrentMenu()->Open(anchor_view, anchor_rect);
  return true;
}

// static
BoringSearchEngineMenu* BoringSearchEngineMenu::GetShowing() {
  BoringSearchEngineMenu* menu = CurrentMenu().get();
  return menu && menu->widget_ ? menu : nullptr;
}

BoringSearchEngineMenu::BoringSearchEngineMenu(
    LocationBarView* bar,
    PickCallback on_pick,
    base::RepeatingClosure on_default_changed,
    base::OnceClosure on_closed)
    : bar_(bar),
      on_pick_(std::move(on_pick)),
      on_default_changed_(std::move(on_default_changed)),
      on_closed_(std::move(on_closed)) {}

BoringSearchEngineMenu::~BoringSearchEngineMenu() {
  motion_.Detach();
  widget_observation_.Reset();
  rows_.clear();
  list_ = nullptr;
  contents_ = nullptr;
  curl_.reset();
  widget_.reset();
}

Profile* BoringSearchEngineMenu::profile() const {
  return bar_->GetProfile();
}

bool BoringSearchEngineMenu::LoadRows() {
  rows_.clear();
  // The same list, and the same rules about what counts as an engine, as
  // our new tab page and the settings bridge use.
  for (const boring::SearchEngine& engine :
       boring::GetSearchEngines(profile())) {
    Row row;
    row.id = engine.id;
    row.keyword = base::UTF8ToUTF16(engine.keyword);
    row.name = base::UTF8ToUTF16(engine.name);
    row.is_default = engine.is_default;
    row.can_be_default = engine.can_be_default && !profile()->IsOffTheRecord();
    rows_.push_back(std::move(row));
  }
  return !rows_.empty();
}

void BoringSearchEngineMenu::BuildContents(
    views::View* list,
    const std::u16string& focus_keyword) {
  list->RemoveAllChildViews();
  TemplateURLService* service = ServiceFor(bar_);
  OmniboxClient* client = bar_->GetOmniboxController()->client();
  views::View* focus = nullptr;
  for (size_t i = 0; i < rows_.size(); ++i) {
    Row& row = rows_[i];
    auto* line = list->AddChildView(std::make_unique<views::View>());
    auto* line_layout =
        line->SetLayoutManager(std::make_unique<views::BoxLayout>(
            views::BoxLayout::Orientation::kHorizontal, gfx::Insets::VH(0, 4),
            4));
    line_layout->set_cross_axis_alignment(
        views::BoxLayout::CrossAxisAlignment::kCenter);

    // The icon: the engine's own favicon when the browser has it, a plain
    // search glyph until then.
    ui::ImageModel icon = ui::ImageModel::FromVectorIcon(
        vector_icons::kSearchIcon, ui::kColorIcon, kIconSize);
    const TemplateURL* engine =
        service ? service->GetTemplateURLForKeyword(row.keyword) : nullptr;
    if (engine && client) {
      gfx::Image favicon = client->GetFaviconForKeywordSearchProvider(
          engine, base::BindOnce(&BoringSearchEngineMenu::OnFaviconFetched,
                                 weak_factory_.GetWeakPtr(), row.keyword));
      if (!favicon.IsEmpty()) {
        icon = ui::ImageModel::FromImage(client->GetSizedIcon(favicon));
      }
    }
    auto* pick = line->AddChildView(std::make_unique<HoverButton>(
        base::BindRepeating(&BoringSearchEngineMenu::OnPick,
                            base::Unretained(this), i),
        icon, row.name));
    pick->SetTooltipText(u"Search with " + row.name);
    if (row.is_default) {
      pick->GetViewAccessibility().SetDescription(u"Default");
    }
    line_layout->SetFlexForView(pick, 1);
    row.pick = pick;
    row.make_default = nullptr;

    if (row.is_default) {
      auto* label = line->AddChildView(std::make_unique<views::Label>(
          u"Default", views::style::CONTEXT_LABEL,
          views::style::STYLE_SECONDARY));
      label->SetBorder(views::CreateEmptyBorder(gfx::Insets::VH(0, 12)));
    } else if (row.can_be_default) {
      auto* make_default =
          line->AddChildView(std::make_unique<views::MdTextButton>(
              base::BindRepeating(&BoringSearchEngineMenu::OnMakeDefault,
                                  base::Unretained(this), i),
              u"Make default"));
      make_default->SetStyle(ui::ButtonStyle::kText);
      make_default->GetViewAccessibility().SetName(u"Make " + row.name +
                                                   u" the default");
      row.make_default = make_default;
    }
    if ((!focus_keyword.empty() && row.keyword == focus_keyword) ||
        (focus_keyword.empty() && row.is_default)) {
      focus = pick;
    }
  }
  if (!focus && !rows_.empty()) {
    focus = rows_.front().pick;
  }
  if (delegate_) {
    delegate_->SetInitiallyFocusedView(focus);
  }
  if (focus && list->GetWidget()) {
    focus->RequestFocus();
  }
}

void BoringSearchEngineMenu::Open(views::View* anchor_view,
                                  const gfx::Rect& anchor_rect) {
  anchor_view_ = anchor_view;
  anchor_bounds_ = anchor_view ? anchor_view->GetBoundsInScreen() : anchor_rect;

  delegate_ = std::make_unique<views::BubbleDialogDelegate>(
      anchor_view, views::BubbleBorder::TOP_LEFT);
  if (!anchor_view) {
    delegate_->SetAnchorRect(anchor_rect);
    delegate_->set_parent_window(bar_->GetWidget()->GetNativeView());
  }
  delegate_->SetTitle(u"Search with");
  delegate_->SetShowTitle(true);
  delegate_->SetAccessibleTitle(u"Search engines");
  delegate_->SetButtons(static_cast<int>(ui::mojom::DialogButton::kNone));
  delegate_->SetEnableArrowKeyTraversal(true);
  delegate_->set_margins(gfx::Insets::TLBR(4, 0, 12, 0));
  delegate_->set_highlight_button_when_shown(true);

  auto contents = std::make_unique<views::View>();
  contents->SetLayoutManager(std::make_unique<views::BoxLayout>(
      views::BoxLayout::Orientation::kVertical, gfx::Insets::VH(0, 8), 4));
  auto* scroll = contents->AddChildView(std::make_unique<views::ScrollView>());
  scroll->SetHorizontalScrollBarMode(
      views::ScrollView::ScrollBarMode::kDisabled);
  scroll->ClipHeightTo(0, kMaxListHeight);
  scroll->SetDrawOverflowIndicator(false);
  auto list_view = std::make_unique<views::View>();
  list_view->SetLayoutManager(std::make_unique<views::BoxLayout>(
      views::BoxLayout::Orientation::kVertical));
  list_ = scroll->SetContents(std::move(list_view));
  BuildContents(list_);

  if (profile()->IsOffTheRecord()) {
    auto* note = contents->AddChildView(std::make_unique<views::Label>(
        u"Change the default in a normal window.", views::style::CONTEXT_LABEL,
        views::style::STYLE_SECONDARY));
    note->SetHorizontalAlignment(gfx::ALIGN_LEFT);
    note->SetBorder(views::CreateEmptyBorder(gfx::Insets::VH(4, 12)));
  }

  auto* done_row = contents->AddChildView(std::make_unique<views::View>());
  auto* done_layout =
      done_row->SetLayoutManager(std::make_unique<views::BoxLayout>(
          views::BoxLayout::Orientation::kHorizontal, gfx::Insets::VH(4, 8)));
  done_layout->set_main_axis_alignment(
      views::BoxLayout::MainAxisAlignment::kEnd);
  done_row->AddChildView(std::make_unique<views::MdTextButton>(
      base::BindRepeating(&BoringSearchEngineMenu::RollUp,
                          base::Unretained(this)),
      u"Done"));

  delegate_->set_fixed_width(kMenuWidth);
  contents_ = delegate_->SetContentsView(std::move(contents));

  widget_ = views::BubbleDialogDelegate::CreateBubble(
      delegate_.get(), base::BindOnce(&BoringSearchEngineMenu::OnCloseRequested,
                                      weak_factory_.GetWeakPtr()));
  widget_observation_.Observe(widget_.get());

  // The curl only belongs to the unroll; a plain fade has none.
  if (boring_ui::UseRichMotion() && widget_->GetLayer()) {
    const ui::ColorProvider* colors = contents_->GetColorProvider();
    const SkColor paper =
        colors ? colors->GetColor(ui::kColorBubbleBackground) : SK_ColorWHITE;
    curl_ = std::make_unique<Curl>(paper, color_utils::IsDark(paper));
    widget_->GetLayer()->Add(curl_->layer());
    widget_->GetLayer()->StackAtTop(curl_->layer());
  }
  motion_.set_progress_callback(base::BindRepeating(
      &BoringSearchEngineMenu::OnMotionProgress, base::Unretained(this)));
  motion_.Open(widget_.get());
  widget_->Show();
}

void BoringSearchEngineMenu::OnMotionProgress(double progress, bool rich) {
  if (!curl_ || !widget_ || !widget_->GetLayer() || !rich) {
    return;
  }
  const gfx::Size size = widget_->GetLayer()->bounds().size();
  const gfx::Rect card =
      contents_ ? contents_->ConvertRectToWidget(contents_->GetLocalBounds())
                : gfx::Rect(size);
  const int edge = gfx::Tween::IntValueBetween(progress, 0, size.height());
  const int top = std::clamp(edge - kCurlHeight, 0, size.height());
  curl_->layer()->SetBounds(gfx::Rect(card.x(), top, card.width(),
                                      std::min(kCurlHeight, edge - top)));
  // The curl flattens out as the paper lands.
  curl_->layer()->SetOpacity(
      progress < 0.8 ? 1.0f : static_cast<float>((1.0 - progress) / 0.2));
  curl_->layer()->SchedulePaint(gfx::Rect(curl_->layer()->size()));
}

void BoringSearchEngineMenu::RollUp() {
  if (widget_ && !motion_.closing()) {
    widget_->CloseWithReason(views::Widget::ClosedReason::kUnspecified);
  }
}

void BoringSearchEngineMenu::OnCloseRequested(
    views::Widget::ClosedReason reason) {
  motion_.Close(base::BindOnce(&BoringSearchEngineMenu::OnRolledUp,
                               weak_factory_.GetWeakPtr()));
}

void BoringSearchEngineMenu::OnRolledUp() {
  widget_observation_.Reset();
  rows_.clear();
  list_ = nullptr;
  contents_ = nullptr;
  curl_.reset();
  widget_.reset();
  if (on_closed_) {
    std::move(on_closed_).Run();
  }
  // Last: this deletes `this`.
  if (CurrentMenu().get() == this) {
    CurrentMenu().reset();
  }
}

void BoringSearchEngineMenu::OnWidgetDestroying(views::Widget* widget) {
  // Closed from underneath, with its window: nothing left to animate.
  motion_.Detach();
  widget_observation_.Reset();
  rows_.clear();
  list_ = nullptr;
  contents_ = nullptr;
  curl_.reset();
  base::SequencedTaskRunner::GetCurrentDefault()->PostTask(
      FROM_HERE, base::BindOnce(&BoringSearchEngineMenu::OnRolledUp,
                                weak_factory_.GetWeakPtr()));
}

void BoringSearchEngineMenu::OnPick(size_t index) {
  if (index >= rows_.size() || motion_.closing()) {
    return;
  }
  const std::u16string keyword = rows_[index].keyword;
  RollUp();
  on_pick_.Run(keyword);
}

void BoringSearchEngineMenu::OnMakeDefault(size_t index) {
  if (index >= rows_.size() || !list_) {
    return;
  }
  const std::u16string keyword = rows_[index].keyword;
  const std::u16string name = rows_[index].name;
  if (!boring::SetDefaultSearchEngine(profile(), rows_[index].id)) {
    return;
  }
  // The address bar follows by itself: it watches the same service. The
  // list is rebuilt after this press returns, since the pressed button
  // is one of the views it replaces.
  base::SequencedTaskRunner::GetCurrentDefault()->PostTask(
      FROM_HERE, base::BindOnce(&BoringSearchEngineMenu::OnDefaultChanged,
                                weak_factory_.GetWeakPtr(), keyword, name));
}

void BoringSearchEngineMenu::OnDefaultChanged(const std::u16string& keyword,
                                              const std::u16string& name) {
  if (!list_) {
    return;
  }
  LoadRows();
  BuildContents(list_, keyword);
  list_->InvalidateLayout();
  list_->GetViewAccessibility().AnnouncePolitely(name +
                                                 u" is now the default.");
  on_default_changed_.Run();
}

void BoringSearchEngineMenu::OnFaviconFetched(const std::u16string& keyword,
                                              const gfx::Image& icon) {
  if (icon.IsEmpty()) {
    return;
  }
  OmniboxClient* client = bar_->GetOmniboxController()->client();
  for (Row& row : rows_) {
    if (row.keyword == keyword && row.pick) {
      row.pick->SetImageModel(
          views::Button::STATE_NORMAL,
          ui::ImageModel::FromImage(client->GetSizedIcon(icon)));
    }
  }
}

base::DictValue BoringSearchEngineMenu::StateForTesting() const {
  base::ListValue engines;
  for (const Row& row : rows_) {
    engines.Append(base::DictValue()
                       .Set("name", row.name)
                       .Set("keyword", row.keyword)
                       .Set("isDefault", row.is_default)
                       .Set("canBeDefault", row.can_be_default)
                       .Set("hasMakeDefault", !!row.make_default));
  }
  const gfx::Rect bounds =
      widget_ ? widget_->GetWindowBoundsInScreen() : gfx::Rect();
  return base::DictValue()
      .Set("open", !!widget_)
      .Set("closing", motion_.closing())
      .Set("rich", motion_.rich())
      .Set("progress", motion_.progress())
      .Set("engines", std::move(engines))
      .Set("anchor", base::DictValue()
                         .Set("x", anchor_bounds_.x())
                         .Set("y", anchor_bounds_.y())
                         .Set("width", anchor_bounds_.width())
                         .Set("height", anchor_bounds_.height()))
      .Set("bounds", base::DictValue()
                         .Set("x", bounds.x())
                         .Set("y", bounds.y())
                         .Set("width", bounds.width())
                         .Set("height", bounds.height()));
}

void BoringSearchEngineMenu::PickForTesting(size_t index) {
  OnPick(index);
}

void BoringSearchEngineMenu::MakeDefaultForTesting(size_t index) {
  if (index < rows_.size() && rows_[index].make_default) {
    OnMakeDefault(index);
  }
}

void BoringSearchEngineMenu::PressEscapeForTesting() {
  // Through the widget's own accelerator, the path a real Escape takes
  // after the OS delivers it. Nothing is sent to the OS.
  if (widget_ && widget_->GetFocusManager()) {
    widget_->GetFocusManager()->ProcessAccelerator(
        ui::Accelerator(ui::VKEY_ESCAPE, ui::EF_NONE));
  }
}

// The new tab page's half: components/boring/newtab/search_engine_menu.h.
namespace boring {

namespace {

// The tab the test hook opened, so it can close it again.
base::WeakPtr<content::WebContents>& TestTab() {
  static base::NoDestructor<base::WeakPtr<content::WebContents>> tab;
  return *tab;
}

}  // namespace

bool ShowSearchEngineMenuForPage(
    content::WebContents* page,
    const gfx::Rect& anchor_in_page,
    base::RepeatingCallback<void(const std::string&)> on_pick,
    base::RepeatingClosure on_default_changed,
    base::OnceClosure on_closed) {
  LocationBarView* bar = BarForPage(page);
  content::RenderWidgetHostView* view =
      page ? page->GetRenderWidgetHostView() : nullptr;
  if (!bar || !view) {
    return false;
  }
  // CSS pixels to screen DIP: the page's zoom, then where it sits.
  const double zoom =
      blink::ZoomLevelToZoomFactor(content::HostZoomMap::GetZoomLevel(page));
  gfx::Rect anchor = gfx::ToEnclosingRect(
      gfx::ScaleRect(gfx::RectF(anchor_in_page), static_cast<float>(zoom)));
  anchor.Offset(view->GetViewBounds().OffsetFromOrigin());
  return BoringSearchEngineMenu::Show(
      bar, /*anchor_view=*/nullptr, anchor,
      base::BindRepeating(
          [](const base::RepeatingCallback<void(const std::string&)>& pick,
             const std::u16string& keyword) {
            pick.Run(base::UTF16ToUTF8(keyword));
          },
          std::move(on_pick)),
      std::move(on_default_changed), std::move(on_closed));
}

base::Value RunSearchEngineMenuTestCommand(content::WebContents* page,
                                           const base::ListValue& args) {
  if (!base::CommandLine::ForCurrentProcess()->HasSwitch(
          kSearchMenuTestSwitch) ||
      args.empty() || !args[0].is_string()) {
    return base::Value();
  }
  const std::string& command = args[0].GetString();
  const int index = args.size() > 1 && args[1].is_int() ? args[1].GetInt() : -1;
  LocationBarView* bar = BarForPage(page);
  BoringSearchEngineMenu* menu = BoringSearchEngineMenu::GetShowing();
  base::DictValue out;

  if (command == "openFromOmnibox" && bar) {
    // Type into the address bar the way a person would see it, then
    // press the icon through the same entry point its press uses.
    const std::u16string text = args.size() > 1 && args[1].is_string()
                                    ? base::UTF8ToUTF16(args[1].GetString())
                                    : std::u16string();
    if (!text.empty()) {
      bar->omnibox_view()->SetUserText(text, /*update_popup=*/true);
    }
    LocationIconView* icon = bar->location_icon_view();
    out.Set("available", BoringSearchEngineMenu::IsAvailableFor(icon));
    out.Set("shown", BoringSearchEngineMenu::ShowForLocationIcon(icon));
  } else if (command == "iconState" && bar) {
    LocationIconView* icon = bar->location_icon_view();
    content::WebContents* active = bar->GetWebContents();
    out.Set("url", active ? active->GetVisibleURL().spec() : std::string());
    out.Set("editingOrEmpty", bar->IsEditingOrEmpty());
    out.Set("available", BoringSearchEngineMenu::IsAvailableFor(icon));
    out.Set("focusable",
            icon->GetFocusBehavior() != views::View::FocusBehavior::NEVER);
    out.Set("placeholder",
            std::u16string(bar->omnibox_view()->GetPlaceholderText()));
    out.Set("pageInfoShowing", PageInfoBubbleViewBase::GetShownBubbleType() !=
                                   PageInfoBubbleViewBase::BUBBLE_NONE);
    out.Set("menuShowing", !!menu);
  } else if (command == "pressIcon" && bar) {
    // What a keyboard press on the icon does, on whatever page is there.
    const ui::KeyEvent press(ui::EventType::kKeyPressed, ui::VKEY_RETURN,
                             ui::EF_NONE);
    out.Set("handled", bar->location_icon_view()->ShowBubble(press));
    out.Set("pageInfoShowing", PageInfoBubbleViewBase::GetShownBubbleType() !=
                                   PageInfoBubbleViewBase::BUBBLE_NONE);
    out.Set("menuShowing", !!BoringSearchEngineMenu::GetShowing());
  } else if (command == "closePageInfo") {
    if (views::BubbleDialogDelegateView* bubble =
            PageInfoBubbleViewBase::GetPageInfoBubbleForTesting()) {
      bubble->GetWidget()->CloseNow();
    }
  } else if (command == "openTab" && page && args.size() > 1 &&
             args[1].is_string()) {
    content::WebContents* tab = page->OpenURL(
        content::OpenURLParams(GURL(args[1].GetString()), content::Referrer(),
                               WindowOpenDisposition::NEW_FOREGROUND_TAB,
                               ui::PAGE_TRANSITION_TYPED,
                               /*is_renderer_initiated=*/false),
        /*navigation_handle_callback=*/{});
    TestTab() = tab ? tab->GetWeakPtr() : base::WeakPtr<content::WebContents>();
    out.Set("opened", !!tab);
  } else if (command == "closeTab") {
    if (content::WebContents* tab = TestTab().get()) {
      tab->Close();
    }
  } else if (command == "state") {
    if (menu) {
      out = menu->StateForTesting();
    } else {
      out.Set("open", false);
    }
    if (bar) {
      out.Set("placeholder",
              std::u16string(bar->omnibox_view()->GetPlaceholderText()));
      content::WebContents* active = bar->GetWebContents();
      out.Set("activeUrl",
              active ? active->GetVisibleURL().spec() : std::string());
    }
  } else if (command == "pick" && menu && index >= 0) {
    menu->PickForTesting(static_cast<size_t>(index));
  } else if (command == "makeDefault" && menu && index >= 0) {
    menu->MakeDefaultForTesting(static_cast<size_t>(index));
  } else if (command == "escape" && menu) {
    menu->PressEscapeForTesting();
  } else if (command == "done" && menu) {
    menu->RollUp();
  } else {
    out.Set("error", "unknown command or nothing to act on");
  }
  return base::Value(std::move(out));
}

}  // namespace boring
