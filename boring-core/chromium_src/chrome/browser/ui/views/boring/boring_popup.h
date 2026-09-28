// Copyright 2026 boring. BSD style license.

#ifndef CHROME_BROWSER_UI_VIEWS_BORING_BORING_POPUP_H_
#define CHROME_BROWSER_UI_VIEWS_BORING_BORING_POPUP_H_

// The motion our own popups share: the shield's panel and the search
// engine menu. Header only, so the toolbar and the location bar targets
// can both use it without either depending on the other.

#include <algorithm>
#include <utility>

#include "base/functional/callback.h"
#include "base/location.h"
#include "base/memory/raw_ptr.h"
#include "base/task/sequenced_task_runner.h"
#include "base/time/time.h"
#include "ui/compositor/layer.h"
#include "ui/gfx/animation/animation.h"
#include "ui/gfx/animation/animation_delegate.h"
#include "ui/gfx/animation/slide_animation.h"
#include "ui/gfx/animation/tween.h"
#include "ui/gfx/geometry/rect.h"
#include "ui/gfx/geometry/transform.h"
#include "ui/views/widget/widget.h"

namespace boring_ui {

// True when our popups may move. Windows "Animation effects" off turns
// rich animation off, and Chromium reads the same setting for reduced
// motion, so either one leaves a plain fade.
inline bool UseRichMotion() {
  return gfx::Animation::ShouldRenderRichAnimation() &&
         !gfx::Animation::PrefersReducedMotion();
}

// Plays a popup widget in and out. The widget's root layer is animated,
// so nothing inside the popup has to know.
class PopupMotion : public gfx::AnimationDelegate {
 public:
  enum class Style {
    // Grows downward from its top edge, like paper unrolling.
    kUnroll,
    // Fades in while settling a few DIP downward.
    kDrop,
  };

  // Called on every frame with how far open the popup is, 0 to 1, and
  // whether it is the rich motion or the plain fade.
  using ProgressCallback =
      base::RepeatingCallback<void(double progress, bool rich)>;

  explicit PopupMotion(Style style) : style_(style) {
    animation_.SetTweenType(gfx::Tween::EASE_OUT);
  }

  PopupMotion(const PopupMotion&) = delete;
  PopupMotion& operator=(const PopupMotion&) = delete;

  ~PopupMotion() override = default;

  void set_progress_callback(ProgressCallback callback) {
    progress_ = std::move(callback);
  }

  // Where an unroll starts, in DIP from the widget's top: the top of the
  // card rather than the top of its shadow.
  void set_unroll_from(int top) { unroll_from_ = top; }

  bool rich() const { return rich_; }
  bool closing() const { return closing_; }
  double progress() const { return animation_.GetCurrentValue(); }

  // Call before the widget is shown, so its first frame is the closed one.
  void Open(views::Widget* widget) {
    widget_ = widget;
    rich_ = UseRichMotion();
    closing_ = false;
    // Only ours: Windows' own popup fade would play on top of it.
    widget_->SetVisibilityChangedAnimationsEnabled(false);
    animation_.Reset(0);
    Apply(0);
    animation_.SetSlideDuration(OpenDuration());
    animation_.Show();
  }

  // Plays the popup out, then posts `done`. Posted rather than run, so
  // the owner may delete this object from it.
  void Close(base::OnceClosure done) {
    if (closing_) {
      return;
    }
    closing_ = true;
    done_ = std::move(done);
    if (!widget_ || animation_.GetCurrentValue() == 0) {
      Finish();
      return;
    }
    animation_.SetSlideDuration(CloseDuration());
    animation_.Hide();
  }

  // The widget is going away on its own; stop touching it.
  void Detach() {
    widget_ = nullptr;
    animation_.Stop();
  }

 private:
  // 150 to 250 ms, calm. The fade is the shortest.
  base::TimeDelta OpenDuration() const {
    if (!rich_) {
      return base::Milliseconds(150);
    }
    return style_ == Style::kUnroll ? base::Milliseconds(200)
                                    : base::Milliseconds(180);
  }
  base::TimeDelta CloseDuration() const {
    if (!rich_) {
      return base::Milliseconds(120);
    }
    return style_ == Style::kUnroll ? base::Milliseconds(170)
                                    : base::Milliseconds(150);
  }

  void Apply(double t) {
    ui::Layer* layer = widget_ ? widget_->GetLayer() : nullptr;
    if (!layer) {
      return;
    }
    if (!rich_) {
      layer->SetOpacity(static_cast<float>(t));
    } else if (style_ == Style::kUnroll) {
      const gfx::Size size = layer->bounds().size();
      const int top = std::clamp(unroll_from_, 0, size.height());
      const int height = gfx::Tween::IntValueBetween(t, top, size.height());
      // An empty clip rect means no clip at all, so the fully closed
      // frame is hidden with opacity instead.
      layer->SetOpacity(t > 0 ? 1.0f : 0.0f);
      layer->SetClipRect(
          t >= 1.0 ? gfx::Rect()
                   : gfx::Rect(0, 0, size.width(), std::max(1, height)));
    } else {
      layer->SetOpacity(static_cast<float>(t));
      gfx::Transform transform;
      transform.Translate(0, static_cast<float>((1.0 - t) * -kDropDistance));
      layer->SetTransform(transform);
    }
    if (progress_) {
      progress_.Run(t, rich_);
    }
  }

  void Finish() {
    if (done_) {
      base::SequencedTaskRunner::GetCurrentDefault()->PostTask(
          FROM_HERE, std::move(done_));
    }
  }

  // gfx::AnimationDelegate:
  void AnimationProgressed(const gfx::Animation* animation) override {
    Apply(animation_.GetCurrentValue());
  }
  void AnimationEnded(const gfx::Animation* animation) override {
    Apply(animation_.GetCurrentValue());
    if (closing_) {
      Finish();
    }
  }
  void AnimationCanceled(const gfx::Animation* animation) override {
    if (closing_) {
      Finish();
    }
  }

  static constexpr double kDropDistance = 6;

  const Style style_;
  raw_ptr<views::Widget> widget_ = nullptr;
  bool rich_ = true;
  bool closing_ = false;
  int unroll_from_ = 0;
  ProgressCallback progress_;
  base::OnceClosure done_;
  gfx::SlideAnimation animation_{this};
};

}  // namespace boring_ui

#endif  // CHROME_BROWSER_UI_VIEWS_BORING_BORING_POPUP_H_
