// Copyright 2026 boring. BSD style license.

#ifndef COMPONENTS_BORING_FOLDER_COPY_FOLDER_PICKER_H_
#define COMPONENTS_BORING_FOLDER_COPY_FOLDER_PICKER_H_

#include "base/files/file_path.h"
#include "base/functional/callback.h"
#include "base/memory/scoped_refptr.h"
#include "ui/shell_dialogs/select_file_dialog.h"

namespace content {
class WebContents;
}

namespace boring::folder_copy {

// Chromium's own folder picker. The callback gets the folder, or an empty
// path when the person closed the dialog. It may delete the picker.
class FolderPicker : public ui::SelectFileDialog::Listener {
 public:
  using Callback = base::OnceCallback<void(const base::FilePath&)>;

  FolderPicker(content::WebContents* contents,
               const base::FilePath& start,
               Callback callback);
  FolderPicker(const FolderPicker&) = delete;
  FolderPicker& operator=(const FolderPicker&) = delete;
  ~FolderPicker() override;

 private:
  // ui::SelectFileDialog::Listener:
  void FileSelected(const ui::SelectedFileInfo& file, int index) override;
  void FileSelectionCanceled() override;

  scoped_refptr<ui::SelectFileDialog> dialog_;
  Callback callback_;
};

}  // namespace boring::folder_copy

#endif  // COMPONENTS_BORING_FOLDER_COPY_FOLDER_PICKER_H_
