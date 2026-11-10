// Copyright 2026 boring. BSD style license.

#include "components/boring/guards/guard_infobar.h"

#include <memory>
#include <utility>

#include "base/command_line.h"
#include "base/functional/bind.h"
#include "base/logging.h"
#include "base/strings/utf_string_conversions.h"
#include "base/task/single_thread_task_runner.h"
#include "base/time/time.h"
#include "chrome/browser/infobars/confirm_infobar_creator.h"  // nogncheck
#include "components/infobars/content/content_infobar_manager.h"
#include "components/infobars/core/infobar.h"
#include "components/vector_icons/vector_icons.h"
#include "content/public/browser/web_contents.h"

namespace boring {
namespace guards {

namespace {

// Test hook, like --boring-open-app-menu: answers a question bar by
// itself two seconds after it appears, so a smoke test can follow both
// answers without sending input to the desktop. "safe" or "risk". Does
// nothing unless the switch is given.
constexpr char kTestAnswerSwitch[] = "boring-guards-test-answer";
constexpr base::TimeDelta kTestAnswerDelay = base::Seconds(2);

void AnswerForTest(base::WeakPtr<GuardInfoBarDelegate> bar, BarAnswer answer) {
  if (!bar) {
    return;
  }
  // Same as pressing the button: answer, then the bar goes.
  if (answer == BarAnswer::kSafe) {
    bar->Accept();
  } else {
    bar->Cancel();
  }
  bar->Close();
}

}  // namespace

// static
base::WeakPtr<GuardInfoBarDelegate> GuardInfoBarDelegate::Show(
    content::WebContents* web_contents,
    Text text,
    Answered answered) {
  infobars::ContentInfoBarManager* manager =
      web_contents
          ? infobars::ContentInfoBarManager::FromWebContents(web_contents)
          : nullptr;
  if (!manager) {
    return nullptr;
  }
  // Said in the log, when logging is on, so a test can read the wording.
  LOG(INFO) << "boring-guards: bar: " << base::UTF16ToUTF8(text.message);

  std::unique_ptr<GuardInfoBarDelegate> delegate(
      new GuardInfoBarDelegate(std::move(text), std::move(answered)));
  base::WeakPtr<GuardInfoBarDelegate> weak = delegate->weak_factory_.GetWeakPtr();
  const bool question = delegate->is_question();
  manager->AddInfoBar(CreateConfirmInfoBar(std::move(delegate)));

  const base::CommandLine* command_line = base::CommandLine::ForCurrentProcess();
  if (weak && question && command_line->HasSwitch(kTestAnswerSwitch)) {
    const bool safe =
        command_line->GetSwitchValueASCII(kTestAnswerSwitch) != "risk";
    base::SingleThreadTaskRunner::GetCurrentDefault()->PostDelayedTask(
        FROM_HERE,
        base::BindOnce(&AnswerForTest, weak,
                       safe ? BarAnswer::kSafe : BarAnswer::kRisk),
        kTestAnswerDelay);
  }
  return weak;
}

GuardInfoBarDelegate::GuardInfoBarDelegate(Text text, Answered answered)
    : text_(std::move(text)), answered_(std::move(answered)) {}

GuardInfoBarDelegate::~GuardInfoBarDelegate() {
  // Closed without an answer: the tab went away.
  Answer(BarAnswer::kDismissed);
}

void GuardInfoBarDelegate::Close() {
  answered_.Reset();
  if (infobars::InfoBar* bar = infobar()) {
    bar->RemoveSelf();
  }
}

void GuardInfoBarDelegate::Answer(BarAnswer answer) {
  if (answered_) {
    std::move(answered_).Run(answer);
  }
}

infobars::InfoBarDelegate::InfoBarIdentifier
GuardInfoBarDelegate::GetIdentifier() const {
  // The identifier list is in a header every infobar includes, so this
  // borrows the one meant for tests rather than touching it.
  return TEST_INFOBAR;
}

infobars::InfoBarDelegate::InfobarPriority GuardInfoBarDelegate::GetPriority()
    const {
  return InfobarPriority::kCriticalSecurity;
}

const gfx::VectorIcon& GuardInfoBarDelegate::GetVectorIcon() const {
  return vector_icons::kErrorFilledIcon;
}

bool GuardInfoBarDelegate::ShouldExpire(const NavigationDetails& details) const {
  // A question is about a download that a navigation does not cancel.
  return !is_question() && ConfirmInfoBarDelegate::ShouldExpire(details);
}

bool GuardInfoBarDelegate::EqualsDelegate(
    infobars::InfoBarDelegate* delegate) const {
  // A page that tries again does not stack a second notice. Two
  // questions are two downloads and both stay.
  return !is_question() && ConfirmInfoBarDelegate::EqualsDelegate(delegate);
}

bool GuardInfoBarDelegate::IsCloseable() const {
  return !is_question();
}

std::u16string GuardInfoBarDelegate::GetMessageText() const {
  return text_.message;
}

int GuardInfoBarDelegate::GetButtons() const {
  return is_question() ? (BUTTON_OK | BUTTON_CANCEL) : BUTTON_NONE;
}

std::u16string GuardInfoBarDelegate::GetButtonLabel(
    InfoBarButton button) const {
  // OK is the main button in a bar, so it is the safe answer.
  return button == BUTTON_OK ? text_.safe_label : text_.risk_label;
}

bool GuardInfoBarDelegate::Accept() {
  Answer(BarAnswer::kSafe);
  return true;
}

bool GuardInfoBarDelegate::Cancel() {
  Answer(BarAnswer::kRisk);
  return true;
}

}  // namespace guards
}  // namespace boring
