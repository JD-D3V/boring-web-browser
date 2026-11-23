// Copyright 2026 boring. BSD style license.

#include "chrome/browser/ui/views/boring/boring_bar_test.h"

#include <optional>
#include <string>
#include <utility>

#include "base/command_line.h"
#include "base/files/file_path.h"
#include "base/files/file_util.h"
#include "base/functional/bind.h"
#include "base/location.h"
#include "base/memory/raw_ptr.h"
#include "base/strings/strcat.h"
#include "base/strings/string_split.h"
#include "base/strings/string_util.h"
#include "base/strings/utf_string_conversions.h"
#include "base/task/single_thread_task_runner.h"
#include "base/task/thread_pool.h"
#include "base/time/time.h"
#include "chrome/browser/profiles/profile.h"
#include "chrome/browser/ui/omnibox/omnibox_controller.h"
#include "chrome/browser/ui/omnibox/omnibox_edit_model.h"
#include "chrome/browser/ui/views/location_bar/location_bar_view.h"
#include "chrome/browser/ui/views/omnibox/omnibox_view_views.h"
#include "components/omnibox/browser/autocomplete_controller.h"
#include "components/omnibox/browser/autocomplete_match.h"
#include "components/omnibox/browser/autocomplete_result.h"
#include "components/omnibox/browser/omnibox_popup_selection.h"
#include "content/public/browser/web_contents.h"
#include "ui/base/accelerators/accelerator.h"
#include "ui/base/window_open_disposition.h"
#include "ui/events/event_constants.h"
#include "ui/events/keycodes/keyboard_codes.h"
#include "ui/views/focus/focus_manager.h"
#include "ui/views/view_tracker.h"

namespace {

constexpr char kSwitch[] = "boring-bar-test";

// Page text (tab and history titles) goes into the report on one line.
std::string OneLine(const std::u16string& text) {
  std::string out = base::UTF16ToUTF8(text);
  base::ReplaceChars(out, "\t\r\n", " ", &out);
  return out;
}

const char* YesNo(bool value) {
  return value ? "yes" : "no";
}

// Works the Bar step by step on the UI thread and deletes itself when the
// report is written, or when the window has gone.
class BarTest {
 public:
  BarTest(LocationBarView* bar, const std::string& spec)
      : report_path_(
            bar->GetProfile()->GetPath().AppendASCII("boring-bar-test.txt")) {
    tracker_.SetView(bar);
    for (const std::string& part : base::SplitString(
             spec, ";", base::TRIM_WHITESPACE, base::SPLIT_WANT_NONEMPTY)) {
      if (part == "enter") {
        enter_ = true;
      } else if (part.starts_with("open=")) {
        open_header_ = base::UTF8ToUTF16(part.substr(5));
      } else if (text_.empty()) {
        text_ = base::UTF8ToUTF16(part);
      }
    }
  }
  BarTest(const BarTest&) = delete;
  BarTest& operator=(const BarTest&) = delete;

  void Start() { Post(&BarTest::Begin, base::Seconds(4)); }

 private:
  LocationBarView* bar() {
    return static_cast<LocationBarView*>(tracker_.view());
  }

  void Post(void (BarTest::*step)(), base::TimeDelta delay) {
    base::SingleThreadTaskRunner::GetCurrentDefault()->PostDelayedTask(
        FROM_HERE, base::BindOnce(step, base::Unretained(this)), delay);
  }

  // True, and the test is over, when the window has gone.
  bool Gone() {
    if (bar()) {
      return false;
    }
    delete this;
    return true;
  }

  void Finish() {
    base::StrAppend(&report_, {"end\n"});
    base::ThreadPool::PostTask(
        FROM_HERE, {base::MayBlock()},
        base::BindOnce(
            [](const base::FilePath& path, const std::string& text) {
              base::WriteFile(path, text);
            },
            report_path_, std::move(report_)));
    delete this;
  }

  OmniboxEditModel* model() {
    return bar()->GetOmniboxController()->edit_model();
  }

  void State(const char* label) {
    OmniboxViewViews* field = bar()->omnibox_view();
    base::StrAppend(
        &report_,
        {"state\t", label, "\tfocused=", YesNo(field->HasFocus()),
         "\tall_selected=", YesNo(field->IsSelectAll()),
         "\tkeyword=", YesNo(model()->is_keyword_selected()),
         "\ttext=", OneLine(field->GetText()),
         "\thint=", OneLine(bar()->boring_bar_hint_text()), "\n"});
  }

  void Begin() {
    if (Gone()) {
      return;
    }
    if (text_ == u"keys") {
      State("before");
      bar()->GetFocusManager()->ProcessAccelerator(
          ui::Accelerator(ui::VKEY_K, ui::EF_CONTROL_DOWN));
      Post(&BarTest::AfterCtrlK, base::Milliseconds(500));
      return;
    }
    bar()->FocusLocation(true, false);
    bar()->omnibox_view()->SetUserText(text_);
    Post(&BarTest::WaitForResults, base::Milliseconds(200));
  }

  void AfterCtrlK() {
    if (Gone()) {
      return;
    }
    State("ctrl+k");
    bar()->GetFocusManager()->ProcessAccelerator(
        ui::Accelerator(ui::VKEY_E, ui::EF_CONTROL_DOWN));
    Post(&BarTest::AfterCtrlE, base::Milliseconds(500));
  }

  void AfterCtrlE() {
    if (Gone()) {
      return;
    }
    State("ctrl+e");
    Finish();
  }

  void WaitForResults() {
    if (Gone()) {
      return;
    }
    const AutocompleteController* controller =
        bar()->GetOmniboxController()->autocomplete_controller();
    if (!controller->done() && ++waits_ < 50) {
      Post(&BarTest::WaitForResults, base::Milliseconds(200));
      return;
    }
    const AutocompleteResult& result = controller->result();
    const size_t selected = model()->GetPopupSelection().line;
    std::optional<size_t> open_line;
    for (size_t i = 0; i < result.size(); ++i) {
      const AutocompleteMatch& match = result.match_at(i);
      const std::u16string header =
          match.suggestion_group_id
              ? result.GetHeaderForSuggestionGroup(*match.suggestion_group_id)
              : std::u16string();
      // The row as the popup shows it: the primary text, then the hint at
      // the right (the controller swaps them for rows that are not searches).
      const bool swap = match.swap_contents_and_description;
      const std::u16string& primary = swap ? match.description : match.contents;
      const std::u16string& hint = swap ? match.contents : match.description;
      base::StrAppend(&report_,
                      {"row\t", OneLine(header), "\t", OneLine(primary),
                       "\t", OneLine(hint), "\t",
                       i == selected ? "selected" : "-", "\n"});
      if (!open_line && !open_header_.empty() && header == open_header_) {
        open_line = i;
      }
    }
    if (!open_header_.empty()) {
      if (!open_line) {
        base::StrAppend(&report_, {"open\tno such header\n"});
        Finish();
        return;
      }
      model()->OpenSelection(OmniboxPopupSelection(*open_line),
                             base::TimeTicks::Now(),
                             WindowOpenDisposition::CURRENT_TAB);
    } else if (enter_) {
      model()->OpenSelection(model()->GetPopupSelection(),
                             base::TimeTicks::Now(),
                             WindowOpenDisposition::CURRENT_TAB);
    } else {
      Finish();
      return;
    }
    Post(&BarTest::AfterOpen, base::Seconds(2));
  }

  void AfterOpen() {
    if (Gone()) {
      return;
    }
    content::WebContents* contents = bar()->GetWebContents();
    base::StrAppend(
        &report_,
        {"after\tfield=", OneLine(bar()->omnibox_view()->GetText()), "\turl=",
         contents ? contents->GetVisibleURL().spec() : std::string(), "\n"});
    Finish();
  }

  views::ViewTracker tracker_;
  const base::FilePath report_path_;
  std::u16string text_;
  std::u16string open_header_;
  bool enter_ = false;
  int waits_ = 0;
  std::string report_;
};

}  // namespace

void BoringBarMaybeRunTest(LocationBarView* bar) {
  const base::CommandLine& command_line =
      *base::CommandLine::ForCurrentProcess();
  if (!command_line.HasSwitch(kSwitch) || !bar->GetProfile()) {
    return;
  }
  // Owns itself until its last step.
  (new BarTest(bar, command_line.GetSwitchValueASCII(kSwitch)))->Start();
}
