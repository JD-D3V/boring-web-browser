// Copyright 2026 boring. BSD style license.

#include "components/boring/performance/tab_activity.h"

#include "components/download/public/common/download_item.h"
#include "content/public/browser/browser_context.h"
#include "content/public/browser/download_item_utils.h"
#include "content/public/browser/download_manager.h"
#include "content/public/browser/web_contents.h"

namespace boring::performance {

bool IsBusyInBackground(content::WebContents* contents) {
  if (!contents) {
    return false;
  }
  if (contents->GetCurrentlyPlayingVideoCount() > 0) {
    return true;
  }
  content::DownloadManager* downloads =
      contents->GetBrowserContext()->GetDownloadManager();
  // Most of the time nothing is downloading at all, and the count is
  // cheaper than walking every download the profile remembers.
  if (!downloads || downloads->InProgressCount() == 0) {
    return false;
  }
  content::DownloadManager::DownloadVector items;
  downloads->GetAllDownloads(&items);
  for (download::DownloadItem* item : items) {
    if (item->GetState() == download::DownloadItem::IN_PROGRESS &&
        content::DownloadItemUtils::GetWebContents(item) == contents) {
      return true;
    }
  }
  return false;
}

}  // namespace boring::performance
