// Copyright 2026 boring. BSD style license.

#ifndef COMPONENTS_BORING_PERFORMANCE_TAB_ACTIVITY_H_
#define COMPONENTS_BORING_PERFORMANCE_TAB_ACTIVITY_H_

namespace content {
class WebContents;
}

namespace boring::performance {

// True while a tab is doing something the person is using even when it
// is not in front, which Chromium's own freezing and discarding rules
// do not already look for: a video playing, or a download the tab
// started that has not finished. Sound, calls, screen sharing and the
// camera are Chromium's own checks and are not repeated here.
bool IsBusyInBackground(content::WebContents* contents);

}  // namespace boring::performance

#endif  // COMPONENTS_BORING_PERFORMANCE_TAB_ACTIVITY_H_
