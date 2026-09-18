// Copyright 2026 boring. BSD style license.

#ifndef CHROME_BROWSER_UI_VIEWS_TOOLBAR_BORING_READER_BUTTON_H_
#define CHROME_BROWSER_UI_VIEWS_TOOLBAR_BORING_READER_BUTTON_H_

#include "base/callback_list.h"
#include "base/memory/raw_ptr.h"
#include "base/memory/weak_ptr.h"
#include "chrome/browser/ui/views/toolbar/toolbar_button.h"
#include "components/dom_distiller/content/browser/distillable_page_utils.h"
#include "content/public/browser/web_contents_observer.h"
#include "ui/base/metadata/metadata_header_macros.h"

class BrowserWindowInterface;

namespace content {
class WebContents;
}

// Opens reader view on pages that have an article in them. Until now the
// only way in was the right click menu, which people do not find. The
// button shows itself only where it would do something, so it is not a
// dead control on every other page.
class BoringReaderButton : public ToolbarButton,
                           public content::WebContentsObserver,
                           public dom_distiller::DistillabilityObserver {
  METADATA_HEADER(BoringReaderButton, ToolbarButton)

 public:
  explicit BoringReaderButton(BrowserWindowInterface* browser);

  BoringReaderButton(const BoringReaderButton&) = delete;
  BoringReaderButton& operator=(const BoringReaderButton&) = delete;

  ~BoringReaderButton() override;

  // content::WebContentsObserver:
  // A page that produces no verdict of its own leaves the last one
  // standing, so the button has to be told a new page arrived.
  void PrimaryPageChanged(content::Page& page) override;

  // dom_distiller::DistillabilityObserver:
  void OnResult(const dom_distiller::DistillabilityResult& result) override;

 private:
  // Points us at whichever tab the window is showing now.
  void FollowActiveTab();

  // Whether the page in `tab_` is worth reading in reader view. The
  // answer arrives after the page loads, which is why we observe.
  void ShowIfArticle();

  void OnPressed();

  // Stops listening to whatever tab we were following.
  void StopWatching();

  const raw_ptr<BrowserWindowInterface> browser_;
  base::WeakPtr<content::WebContents> tab_;
  base::CallbackListSubscription tab_changed_;
};

#endif  // CHROME_BROWSER_UI_VIEWS_TOOLBAR_BORING_READER_BUTTON_H_
