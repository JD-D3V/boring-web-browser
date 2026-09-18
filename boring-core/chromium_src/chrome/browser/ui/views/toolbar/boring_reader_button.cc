// Copyright 2026 boring. BSD style license.

#include "chrome/browser/ui/views/toolbar/boring_reader_button.h"

#include <optional>
#include <string>

#include "base/functional/bind.h"
#include "base/functional/callback_helpers.h"
#include "base/strings/utf_string_conversions.h"
#include "base/values.h"
#include "chrome/app/vector_icons/vector_icons.h"
#include "chrome/browser/dom_distiller/tab_utils.h"
#include "chrome/browser/ui/browser_window/public/browser_window_interface.h"
#include "chrome/common/chrome_isolated_world_ids.h"
#include "components/boring/reader/reader_scroll_keeper.h"
#include "components/tabs/public/tab_interface.h"
#include "content/public/browser/page.h"
#include "content/public/browser/render_frame_host.h"
#include "content/public/browser/web_contents.h"
#include "ui/base/metadata/metadata_impl_macros.h"
#include "ui/views/accessibility/view_accessibility.h"

BoringReaderButton::BoringReaderButton(BrowserWindowInterface* browser)
    : ToolbarButton(base::BindRepeating(&BoringReaderButton::OnPressed,
                                        base::Unretained(this))),
      browser_(browser) {
  SetVectorIcon(kMenuBookIcon);
  SetTooltipText(u"Read this page without the clutter");
  GetViewAccessibility().SetName(u"Reader view");
  // Nothing is worth reading until a page says so.
  SetVisible(false);

  // ToolbarView::Update never reaches us with a tab, so follow the
  // window's own active tab signal instead.
  tab_changed_ = browser_->RegisterActiveTabDidChange(base::BindRepeating(
      [](BoringReaderButton* self, BrowserWindowInterface*) {
        self->FollowActiveTab();
      },
      base::Unretained(this)));
  FollowActiveTab();
}

BoringReaderButton::~BoringReaderButton() {
  StopWatching();
}

void BoringReaderButton::StopWatching() {
  if (tab_) {
    dom_distiller::RemoveObserver(tab_.get(), this);
  }
  tab_ = nullptr;
}

void BoringReaderButton::FollowActiveTab() {
  tabs::TabInterface* active = browser_->GetActiveTabInterface();
  content::WebContents* tab = active ? active->GetContents() : nullptr;
  if (tab_.get() == tab) {
    ShowIfArticle();
    return;
  }
  StopWatching();
  if (tab) {
    tab_ = tab->GetWeakPtr();
    dom_distiller::AddObserver(tab, this);
  }
  Observe(tab);
  ShowIfArticle();
}

void BoringReaderButton::PrimaryPageChanged(content::Page& page) {
  ShowIfArticle();
}

void BoringReaderButton::OnResult(
    const dom_distiller::DistillabilityResult& result) {
  ShowIfArticle();
}

void BoringReaderButton::ShowIfArticle() {
  bool article = false;
  if (tab_) {
    const std::optional<dom_distiller::DistillabilityResult> result =
        dom_distiller::GetLatestResult(tab_.get());
    // A page that produces no verdict of its own, like chrome://version,
    // leaves the last page's verdict sitting there, so check the answer
    // is about the page we are actually on before believing it.
    if (result.has_value() && result->url == tab_->GetLastCommittedURL()) {
      // The classifier is strict about what it calls distillable, and
      // says no to plenty of things worth reading: a long Wikipedia
      // article comes back distillable 0, long article 1. Offer reader
      // view for either, since a long page is exactly where it helps.
      article = result->is_distillable || result->is_long_article;
    }
  }
  if (GetVisible() != article) {
    SetVisible(article);
    PreferredSizeChanged();
  }
}

void BoringReaderButton::OnPressed() {
  if (!tab_) {
    return;
  }
  content::WebContents* contents = tab_.get();
  content::RenderFrameHost* frame = contents->GetPrimaryMainFrame();
  if (!frame) {
    DistillCurrentPageAndViewIfSuccessful(contents, base::DoNothing());
    return;
  }
  // Ask the live page which paragraph has been reached, then open reader
  // view there instead of back at the top of the article. The same thing
  // the right click entry does, so both ways in behave alike.
  base::WeakPtr<content::WebContents> weak = contents->GetWeakPtr();
  frame->ExecuteJavaScriptInIsolatedWorld(
      base::UTF8ToUTF16(std::string(boring::kReaderAnchorScript)),
      base::BindOnce(
          [](base::WeakPtr<content::WebContents> contents, base::Value result) {
            if (!contents) {
              return;
            }
            boring::ReaderScrollKeeper::Remember(contents.get(), result);
            DistillCurrentPageAndViewIfSuccessful(contents.get(),
                                                  base::DoNothing());
          },
          weak),
      ISOLATED_WORLD_ID_CHROME_INTERNAL);
}

BEGIN_METADATA(BoringReaderButton)
END_METADATA
