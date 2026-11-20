// Copyright 2026 boring. BSD style license.

#ifndef CHROME_BROWSER_UI_VIEWS_TABS_COMMON_BORING_SIDE_TAB_HEADING_H_
#define CHROME_BROWSER_UI_VIEWS_TABS_COMMON_BORING_SIDE_TAB_HEADING_H_

#include <string>

#include "ui/base/metadata/metadata_header_macros.h"
#include "ui/views/controls/label.h"

// A section heading in the side tabs list ("Pinned", "Open tabs"), as the
// Shelf draws its headings (screen C09): 12 px 600 in the quiet ink, 8 px in
// from the side, 4 px of room below. The text is ours, never a page's. It
// is a copy of the Shelf's heading in a smaller class because the tab strip
// cannot depend on the side panel code.
class BoringSideTabHeading : public views::Label {
  METADATA_HEADER(BoringSideTabHeading, views::Label)

 public:
  explicit BoringSideTabHeading(const std::u16string& text);
  BoringSideTabHeading(const BoringSideTabHeading&) = delete;
  BoringSideTabHeading& operator=(const BoringSideTabHeading&) = delete;
  ~BoringSideTabHeading() override;
};

#endif  // CHROME_BROWSER_UI_VIEWS_TABS_COMMON_BORING_SIDE_TAB_HEADING_H_
