// Copyright 2026 boring. BSD style license.

#ifndef COMPONENTS_BORING_GUARDS_DOWNLOAD_GUARD_H_
#define COMPONENTS_BORING_GUARDS_DOWNLOAD_GUARD_H_

#include "base/functional/callback.h"

namespace download {
class DownloadItem;
}

namespace boring {
namespace guards {

// The remote access guard. Called from
// ChromeDownloadManagerDelegate::DetermineDownloadTarget() for a download
// that is about to choose where to be saved, with what to run to carry on
// (`proceed`, which this takes only when it keeps the download).
//
// When the download is a remote access tool (see remote_access_tools.h),
// this holds it, the way a Save As prompt does, and puts a bar on the tab
// that started it: the safe action, "Don't download", is the main button,
// "Download anyway" the other. The bytes keep arriving into the temporary
// file meanwhile and nothing is kept until the person answers. Don't
// download cancels it. Download anyway runs `proceed`. A tab closed with
// no answer cancels it. The wording is stronger when that tab has tripped
// the takeover detector.
//
// Returns true when it holds the download, false for every other
// download: then `proceed` is untouched and the caller runs it.
bool HoldRemoteAccessDownload(download::DownloadItem* item,
                              base::OnceClosure* proceed);

}  // namespace guards
}  // namespace boring

#endif  // COMPONENTS_BORING_GUARDS_DOWNLOAD_GUARD_H_
