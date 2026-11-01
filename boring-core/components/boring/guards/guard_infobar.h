// Copyright 2026 boring. BSD style license.

#ifndef COMPONENTS_BORING_GUARDS_GUARD_INFOBAR_H_
#define COMPONENTS_BORING_GUARDS_GUARD_INFOBAR_H_

#include <string>

#include "base/functional/callback.h"
#include "base/memory/weak_ptr.h"
#include "components/infobars/core/confirm_infobar_delegate.h"

namespace content {
class WebContents;
}

namespace boring {
namespace guards {

// What the person chose on a bar with two buttons.
enum class BarAnswer {
  kSafe,       // The main button.
  kRisk,       // The other one.
  kDismissed,  // The bar went away unanswered: the tab closed.
};

// The bar both scam guards show, above the page of the tab they are
// about. It belongs to the browser, not the page, and the page cannot
// click it.
//
// Two shapes. With `safe_label` and `risk_label` empty it is a notice
// with a close button and nothing to answer. With both set it is a
// question: the safe action is the main button, and the bar stays until it
// is answered, through navigations too, because a scam page can navigate
// away the moment its download starts.
class GuardInfoBarDelegate : public ConfirmInfoBarDelegate {
 public:
  using Answered = base::OnceCallback<void(BarAnswer)>;

  struct Text {
    std::u16string message;
    std::u16string safe_label;
    std::u16string risk_label;
  };

  // Puts the bar on `web_contents`. Returns null when it could not (no
  // bar manager, or an equal notice is already up). `answered` runs once.
  static base::WeakPtr<GuardInfoBarDelegate> Show(
      content::WebContents* web_contents,
      Text text,
      Answered answered);

  ~GuardInfoBarDelegate() override;

  // Takes the bar down without an answer (the thing it asked about is
  // gone). `answered` does not run.
  void Close();

  // infobars::InfoBarDelegate:
  infobars::InfoBarDelegate::InfoBarIdentifier GetIdentifier() const override;
  infobars::InfoBarDelegate::InfobarPriority GetPriority() const override;
  const gfx::VectorIcon& GetVectorIcon() const override;
  bool ShouldExpire(const NavigationDetails& details) const override;
  bool EqualsDelegate(infobars::InfoBarDelegate* delegate) const override;
  bool IsCloseable() const override;

  // ConfirmInfoBarDelegate:
  std::u16string GetMessageText() const override;
  int GetButtons() const override;
  std::u16string GetButtonLabel(InfoBarButton button) const override;
  bool Accept() override;
  bool Cancel() override;

 private:
  GuardInfoBarDelegate(Text text, Answered answered);

  bool is_question() const { return !text_.safe_label.empty(); }
  void Answer(BarAnswer answer);

  const Text text_;
  Answered answered_;
  base::WeakPtrFactory<GuardInfoBarDelegate> weak_factory_{this};
};

}  // namespace guards
}  // namespace boring

#endif  // COMPONENTS_BORING_GUARDS_GUARD_INFOBAR_H_
