// Copyright 2026 boring. BSD style license.

#include "components/boring/guards/download_guard.h"

#include <string>
#include <utility>

#include "base/functional/bind.h"
#include "base/memory/raw_ptr.h"
#include "base/memory/weak_ptr.h"
#include "components/boring/guards/guard_infobar.h"
#include "components/boring/guards/guards_policy.h"
#include "components/boring/guards/remote_access_tools.h"
#include "components/boring/scam/takeover/takeover_tab_helper.h"
#include "components/download/public/common/download_item.h"
#include "components/infobars/content/content_infobar_manager.h"
#include "content/public/browser/download_item_utils.h"
#include "content/public/browser/web_contents.h"
#include "net/base/filename_util.h"
#include "url/gurl.h"

namespace boring {
namespace guards {

namespace {

using download::DownloadItem;

constexpr char16_t kQuestion[] =
    u"Scammers ask people to install this so they can control the "
    u"computer. Only continue if you started this yourself.";
constexpr char16_t kStrongQuestion[] =
    u"This tab looked like a scam. Scammers ask people to install this so "
    u"they can control the computer. Do not continue.";
constexpr char16_t kStop[] = u"Don't download";
constexpr char16_t kGoOn[] = u"Download anyway";

// A download waiting for an answer to its bar. It owns itself and ends
// with the answer, or when the download ends some other way.
class HeldDownload : public DownloadItem::Observer {
 public:
  explicit HeldDownload(DownloadItem* item) : item_(item) {
    item_->AddObserver(this);
  }

  ~HeldDownload() override {
    if (item_) {
      item_->RemoveObserver(this);
    }
  }

  // Puts the bar up. False if it could not be.
  bool Ask(content::WebContents* web_contents, bool strong) {
    showing_ = true;
    bar_ = GuardInfoBarDelegate::Show(
        web_contents,
        {.message = strong ? kStrongQuestion : kQuestion,
         .safe_label = kStop,
         .risk_label = kGoOn},
        base::BindOnce(&HeldDownload::OnAnswer, weak_factory_.GetWeakPtr()));
    showing_ = false;
    return !!bar_;
  }

  void set_proceed(base::OnceClosure proceed) { proceed_ = std::move(proceed); }

  // DownloadItem::Observer:
  void OnDownloadUpdated(DownloadItem* download) override {
    // Finished, failed or cancelled from somewhere else: nothing is left
    // to ask about.
    if (download->GetState() != DownloadItem::IN_PROGRESS) {
      Release();
    }
  }

  void OnDownloadDestroyed(DownloadItem* download) override {
    download->RemoveObserver(this);
    item_ = nullptr;
    Release();
  }

 private:
  void OnAnswer(BarAnswer answer) {
    // A bar that is refused unanswered reports itself as dismissed
    // before Ask() has returned.
    if (showing_ || done_) {
      return;
    }
    done_ = true;
    if (answer == BarAnswer::kRisk && proceed_) {
      std::move(proceed_).Run();
    } else {
      // The safe button, or a tab closed with no answer.
      item_->Cancel(/*user_cancel=*/true);
    }
    delete this;
  }

  void Release() {
    if (done_) {
      return;
    }
    done_ = true;
    if (bar_) {
      bar_->Close();
    }
    delete this;
  }

  raw_ptr<DownloadItem> item_;
  base::OnceClosure proceed_;
  base::WeakPtr<GuardInfoBarDelegate> bar_;
  bool showing_ = false;
  bool done_ = false;
  base::WeakPtrFactory<HeldDownload> weak_factory_{this};
};

}  // namespace

bool HoldRemoteAccessDownload(DownloadItem* item, base::OnceClosure* proceed) {
  // Only a download that has not chosen a place yet: not one being
  // resumed, and not one the browser makes for itself.
  if (!item->GetTargetFilePath().empty() || item->IsTransient() ||
      item->IsSavePackageDownload()) {
    return false;
  }
  content::WebContents* web_contents =
      content::DownloadItemUtils::GetWebContents(item);
  // With no tab there is nowhere to show the bar, so it goes on as it was.
  if (!web_contents || !IsEnabled(web_contents->GetBrowserContext()) ||
      !infobars::ContentInfoBarManager::FromWebContents(web_contents)) {
    return false;
  }
  // The name Chromium would save it under, without the type lookup that
  // is not allowed on this thread.
  const std::string file_name =
      net::GenerateFileName(item->GetURL(), item->GetContentDisposition(),
                            std::string(), item->GetSuggestedFilename(),
                            std::string(), "download")
          .AsUTF8Unsafe();
  if (MatchRemoteAccessTool(file_name, item->GetURL().host()).empty()) {
    return false;
  }

  auto* held = new HeldDownload(item);
  if (!held->Ask(web_contents, TakeoverTabHelper::LooksLikeScam(web_contents))) {
    delete held;
    return false;
  }
  held->set_proceed(std::move(*proceed));
  return true;
}

}  // namespace guards
}  // namespace boring
