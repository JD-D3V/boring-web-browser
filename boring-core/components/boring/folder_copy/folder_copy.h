// Copyright 2026 boring. BSD style license.

#ifndef COMPONENTS_BORING_FOLDER_COPY_FOLDER_COPY_H_
#define COMPONENTS_BORING_FOLDER_COPY_FOLDER_COPY_H_

#include <string>
#include <vector>

#include "base/callback_list.h"
#include "base/files/file_path.h"
#include "base/functional/callback.h"
#include "base/memory/raw_ptr.h"
#include "base/memory/weak_ptr.h"
#include "base/scoped_observation.h"
#include "base/supports_user_data.h"
#include "base/time/time.h"
#include "base/timer/timer.h"
#include "base/values.h"
#include "chrome/browser/bookmarks/bookmark_html_writer.h"
#include "components/bookmarks/browser/base_bookmark_model_observer.h"
#include "components/boring/folder_copy/folder_copy_settings.h"
#include "components/prefs/pref_change_registrar.h"

class PrefService;
class Profile;

namespace bookmarks {
class BookmarkModel;
}

namespace boring::folder_copy {

// Test only: the folder to copy into, in place of the picker, which a
// test cannot drive. Used for one run, and only for a folder under the
// system temp directory. Not saved.
inline constexpr char kFolderCopyDirSwitch[] = "boring-folder-copy-dir";

inline constexpr char kBookmarksFileName[] = "bookmarks.html";
inline constexpr char kSettingsFileName[] = "boring-settings.json";

// What a look at the folder found, read off the UI thread.
struct FolderFiles {
  bool dir_ok = false;
  bool has_bookmarks = false;
  bool has_settings = false;
  bool settings_read = false;
  std::string settings;
};

// "Keep a copy in a folder". One per profile, owned by it. With no folder
// picked it does nothing. With one, it writes bookmarks.html (Chromium's
// own export) and boring-settings.json there at startup and a few seconds
// after a change. The person's cloud app moves the files; the browser
// never contacts a server for this. One way: the folder is only read when
// the person clicks "Load from folder", and then bookmarks are only added.
class FolderCopy : public base::SupportsUserData::Data,
                   public bookmarks::BaseBookmarkModelObserver {
 public:
  // Called as a tab opens. Starts the copy for the profile the first time;
  // does nothing for a private window.
  static void Start(Profile* profile);
  static FolderCopy* Get(Profile* profile);

  FolderCopy(const FolderCopy&) = delete;
  FolderCopy& operator=(const FolderCopy&) = delete;
  ~FolderCopy() override;

  // What the Protection page shows.
  base::DictValue UiState() const;
  // Told when UiState() changed.
  base::CallbackListSubscription Subscribe(base::RepeatingClosure callback);

  base::FilePath Dir() const;
  // Empty turns the copy off.
  void SetDir(const base::FilePath& dir);
  // Adds the bookmarks from the folder that are not here yet and lists the
  // settings that differ. Nothing else changes.
  void Load();
  // Applies the settings Load() listed.
  void ApplyPending();
  // Leaves them.
  void DropPending();
  // A folder that already holds a copy: replace it with this browser's.
  void SaveOver();

 private:
  explicit FolderCopy(Profile* profile);

  void Init();
  void Notify();
  bool Armed() const;
  void Arm();
  void SetArmed(bool armed);
  // Starts the copy for dir, whether it came from the page or the switch.
  void Restart(const base::FilePath& dir);
  void ScheduleWrite(base::TimeDelta delay);
  void OnSettingChanged();
  void WriteNow();
  void OnSettingsWritten(bool ok);
  void OnExported(bookmark_html_writer::Result result);
  void OnExportCopied(bool ok);
  void FinishWrite(bool ok);
  void OnChecked(const base::FilePath& dir, bool has_copy);
  void OnFolderRead(const base::FilePath& dir, FolderFiles files);
  void OnBookmarksLoaded(bool had_file, int added);

  // bookmarks::BaseBookmarkModelObserver:
  void BookmarkModelChanged() override;
  void BookmarkModelBeingDeleted() override;

  const raw_ptr<Profile> profile_;
  const raw_ptr<PrefService> prefs_;
  PrefChangeRegistrar registrar_;
  base::ScopedObservation<bookmarks::BookmarkModel,
                          bookmarks::BookmarkModelObserver>
      model_observation_{this};
  base::OneShotTimer write_timer_;
  base::RepeatingCallbackList<void()> changed_;

  bool checking_ = false;
  bool writing_ = false;
  bool write_again_ = false;
  bool loading_ = false;
  base::Time saved_at_;
  std::string error_;
  std::string message_;
  // What Load() found, waiting for the person to agree.
  std::vector<SettingChange> changes_;
  base::DictValue pending_;
  std::string settings_note_;
  base::FilePath loading_dir_;
  // From the test switch, for this run only. Never written to prefs.
  base::FilePath test_dir_;
  bool test_armed_ = false;

  base::WeakPtrFactory<FolderCopy> weak_factory_{this};
};

}  // namespace boring::folder_copy

#endif  // COMPONENTS_BORING_FOLDER_COPY_FOLDER_COPY_H_
