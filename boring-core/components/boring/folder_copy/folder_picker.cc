// Copyright 2026 boring. BSD style license.

#include "components/boring/folder_copy/folder_picker.h"

#include <memory>
#include <utility>

#include "chrome/browser/ui/select_file_policy/chrome_select_file_policy.h"
#include "content/public/browser/web_contents.h"
#include "ui/shell_dialogs/selected_file_info.h"

namespace boring::folder_copy {

FolderPicker::FolderPicker(content::WebContents* contents,
                           const base::FilePath& start,
                           Callback callback)
    : callback_(std::move(callback)) {
  dialog_ = ui::SelectFileDialog::Create(
      this, std::make_unique<ChromeSelectFilePolicy>(contents));
  ui::SelectFileDialog::FileTypeInfo info;
  info.allowed_paths = ui::SelectFileDialog::FileTypeInfo::NATIVE_PATH;
  dialog_->SelectFile(ui::SelectFileDialog::SELECT_FOLDER,
                      u"Choose a folder", start, &info, 0,
                      base::FilePath::StringType(),
                      contents->GetTopLevelNativeWindow(), nullptr);
}

FolderPicker::~FolderPicker() {
  if (dialog_) {
    dialog_->ListenerDestroyed();
  }
}

void FolderPicker::FileSelected(const ui::SelectedFileInfo& file, int index) {
  dialog_ = nullptr;
  std::move(callback_).Run(file.path());
}

void FolderPicker::FileSelectionCanceled() {
  dialog_ = nullptr;
  std::move(callback_).Run(base::FilePath());
}

}  // namespace boring::folder_copy
