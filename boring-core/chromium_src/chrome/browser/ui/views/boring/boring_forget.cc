// Copyright 2026 boring. BSD style license.

#include "chrome/browser/ui/views/boring/boring_forget.h"

#include <memory>
#include <utility>

#include "base/files/file_path.h"
#include "base/functional/bind.h"
#include "base/functional/callback.h"
#include "base/functional/callback_helpers.h"
#include "base/logging.h"
#include "base/memory/raw_ptr.h"
#include "base/memory/weak_ptr.h"
#include "base/process/process.h"
#include "base/scoped_observation.h"
#include "base/task/single_thread_task_runner.h"
#include "base/time/time.h"
#include "chrome/browser/browsing_data/chrome_browsing_data_remover_constants.h"
#include "chrome/browser/content_settings/host_content_settings_map_factory.h"
#include "chrome/browser/lifetime/application_lifetime_desktop.h"
#include "chrome/browser/profiles/keep_alive/profile_keep_alive_types.h"
#include "chrome/browser/profiles/keep_alive/scoped_profile_keep_alive.h"
#include "chrome/browser/profiles/profile.h"
#include "chrome/browser/sessions/session_service.h"
#include "chrome/browser/sessions/session_service_factory.h"
#include "chrome/browser/sessions/tab_restore_service_factory.h"
#include "chrome/browser/ui/browser_window/public/browser_window_interface.h"
#include "chrome/browser/ui/browser_commands.h"
#include "chrome/browser/ui/browser_window/public/global_browser_collection.h"
#include "components/boring/scam/lookalike_blocking_page.h"
#include "components/boring/scam/scam_service.h"
#include "components/constrained_window/constrained_window_views.h"
#include "components/content_settings/core/browser/content_settings_info.h"
#include "components/content_settings/core/browser/host_content_settings_map.h"
#include "components/content_settings/core/browser/permission_settings_registry.h"
#include "components/content_settings/core/browser/website_settings_info.h"
#include "components/content_settings/core/common/content_settings_pattern.h"
#include "components/keep_alive_registry/keep_alive_types.h"
#include "components/keep_alive_registry/scoped_keep_alive.h"
#include "components/sessions/core/tab_restore_service.h"
#include "content/public/browser/browsing_data_filter_builder.h"
#include "content/public/browser/browsing_data_remover.h"
#include "content/public/browser/navigation_controller.h"
#include "content/public/browser/reload_type.h"
#include "content/public/browser/web_contents.h"
#include "ui/base/base_window.h"
#include "ui/base/models/dialog_model.h"
#include "ui/base/mojom/dialog_button.mojom.h"
#include "url/gurl.h"

namespace boring {

namespace {

namespace remover = chrome_browsing_data_remover;
using content::BrowsingDataRemover;

// Everything a site keeps about a visit: cookies and storage, and the
// cache.
constexpr uint64_t kSiteData =
    remover::DATA_TYPE_SITE_DATA | BrowsingDataRemover::DATA_TYPE_CACHE;
// What the person browsed this session: the history too.
constexpr uint64_t kSessionData = kSiteData | remover::DATA_TYPE_HISTORY;
constexpr uint64_t kOrigins = BrowsingDataRemover::ORIGIN_TYPE_UNPROTECTED_WEB |
                              BrowsingDataRemover::ORIGIN_TYPE_PROTECTED_WEB;

// One run of the browsing data remover. Keeps the profile and the
// browser alive until it is done, tells `done` and goes away. It owns
// itself, since nothing else outlives the dialog or the panel that
// started it.
class RemovalJob : public BrowsingDataRemover::Observer {
 public:
  RemovalJob(Profile* profile, base::OnceClosure done)
      : profile_keep_alive_(
            profile,
            ProfileKeepAliveOrigin::kClearingBrowsingData),
        done_(std::move(done)),
        remover_(profile->GetBrowsingDataRemover()) {
    observation_.Observe(remover_);
  }

  // `filter` is null to match every site.
  void Start(base::Time begin,
             uint64_t mask,
             std::unique_ptr<content::BrowsingDataFilterBuilder> filter) {
    if (filter) {
      remover_->RemoveWithFilterAndReply(begin, base::Time::Max(), mask,
                                         kOrigins, std::move(filter), this);
    } else {
      remover_->RemoveAndReply(begin, base::Time::Max(), mask, kOrigins, this);
    }
  }

 private:
  // content::BrowsingDataRemover::Observer:
  void OnBrowsingDataRemoverDone(uint64_t failed_data_types) override {
    VLOG(1) << "boring_forget: data removed, failed types " << failed_data_types;
    // The remover is still walking its observers, so the job goes once it
    // has finished.
    base::SingleThreadTaskRunner::GetCurrentDefault()->DeleteSoon(FROM_HERE,
                                                                  this);
    std::move(done_).Run();
  }

  ScopedProfileKeepAlive profile_keep_alive_;
  base::OnceClosure done_;
  raw_ptr<BrowsingDataRemover> remover_;
  base::ScopedObservation<BrowsingDataRemover, BrowsingDataRemover::Observer>
      observation_{this};
};

// What the person allowed or blocked for the page (camera, location,
// notifications and the rest of the permissions Chromium lists on its
// site settings page), as Chromium's own "clear site settings" walks
// them, but only the rules that name this site. A rule for every site
// is not about this one and stays.
void ResetPermissions(Profile* profile, const GURL& url) {
  HostContentSettingsMap* map =
      HostContentSettingsMapFactory::GetForProfile(profile);
  if (!map || !url.is_valid()) {
    return;
  }
  for (const content_settings::PermissionSettingsInfo* info :
       *content_settings::PermissionSettingsRegistry::GetInstance()) {
    map->ClearSettingsForOneTypeWithPredicate(
        info->website_settings_info()->type(),
        [&url](const ContentSettingPatternSource& setting) {
          return !setting.primary_pattern.MatchesAllHosts() &&
                 setting.primary_pattern.Matches(url);
        });
  }
}

void ReloadTab(base::WeakPtr<content::WebContents> tab) {
  if (tab) {
    tab->GetController().Reload(content::ReloadType::NORMAL,
                                /*check_for_repost=*/true);
  }
}

// How many windows of the profile are still open, an incognito window
// of it included.
size_t OpenWindows(Profile* profile) {
  size_t count = 0;
  GlobalBrowserCollection::GetInstance()->ForEach(
      [&](BrowserWindowInterface* browser) {
        if (browser->GetProfile()->GetOriginalProfile() ==
            profile->GetOriginalProfile()) {
          ++count;
        }
        return true;
      });
  return count;
}

// Throws away what the session service and the tab restore service kept of
// the windows that just closed. A window opened while none is open counts as
// a fresh start, and by default a start continues where the last session
// ended, so without this the old tabs come straight back, and Ctrl+Shift+T
// would still reopen them. Closing every window of a profile shuts its
// session service down, which saves the windows as the last session. That
// is what a new service reads next, so one is made now, for the session
// restore variant of the lookup, and the last session it finds is deleted.
void DiscardSavedSession(Profile* profile) {
  if (SessionService* session_service =
          SessionServiceFactory::GetForProfileForSessionRestore(profile)) {
    session_service->DeleteLastSession();
    VLOG(1) << "boring_forget: last session deleted";
  } else {
    VLOG(1) << "boring_forget: no session service";
  }
  if (sessions::TabRestoreService* tab_restore =
          TabRestoreServiceFactory::GetForProfile(profile)) {
    const size_t before = tab_restore->entries().size();
    tab_restore->ClearEntries();
    tab_restore->DeleteLastSession();
    VLOG(1) << "boring_forget: recently closed entries were " << before
            << ", now " << tab_restore->entries().size();
  }
}

// The steps of "Forget this session", in the order they have to happen:
// the windows go first so nothing writes history or storage again while it
// is being deleted, then the data, then one new tab. Holds the browser
// open meanwhile, because with no window left it would quit.
class SessionJob {
 public:
  explicit SessionJob(Profile* profile)
      : profile_(profile),
        keep_alive_(KeepAliveOrigin::BROWSER,
                    KeepAliveRestartOption::DISABLED),
        profile_keep_alive_(profile,
                            ProfileKeepAliveOrigin::kClearingBrowsingData) {}

  void Start() {
    chrome::CloseAllBrowsersWithProfile(
        profile_, /*skip_beforeunload=*/true,
        base::BindRepeating(&SessionJob::OnClosed, weak_factory_.GetWeakPtr()),
        base::BindRepeating(&SessionJob::OnAborted,
                            weak_factory_.GetWeakPtr()));
  }

 private:
  // Every window agreed to close. They are only asked to, right after this
  // returns, so look until they are gone.
  void OnClosed(const base::FilePath& profile_dir) {
    VLOG(1) << "boring_forget: windows agreed to close, open "
            << OpenWindows(profile_) << ", first call " << !closed_;
    if (!closed_) {
      closed_ = true;
      WaitForWindows(kWindowChecks);
    }
  }

  void OnAborted(const base::FilePath& profile_dir) {
    VLOG(1) << "boring_forget: closing the windows was stopped";
    delete this;
  }

  void WaitForWindows(int checks_left) {
    if (OpenWindows(profile_) > 0 && checks_left > 0) {
      base::SingleThreadTaskRunner::GetCurrentDefault()->PostDelayedTask(
          FROM_HERE,
          base::BindOnce(&SessionJob::WaitForWindows,
                         weak_factory_.GetWeakPtr(), checks_left - 1),
          kWindowCheckEvery);
      return;
    }
    VLOG(1) << "boring_forget: deleting, windows still open "
            << OpenWindows(profile_) << ", checks left " << checks_left;
    // Since the browser started, as far as the process says. If it does
    // not say, the time stays null, which deletes from the beginning:
    // all of it, the conservative reading of "forget".
    base::Time since;
    const base::Process self = base::Process::Current();
    if (self.IsValid()) {
      since = self.CreationTime();
    }
    // Owns itself, see RemovalJob.
    (new RemovalJob(profile_, base::BindOnce(&SessionJob::OnRemoved,
                                             weak_factory_.GetWeakPtr())))
        ->Start(since, kSessionData, nullptr);
  }

  void OnRemoved() {
    VLOG(1) << "boring_forget: opening the new window, open now "
            << OpenWindows(profile_);
    DiscardSavedSession(profile_);
    chrome::NewEmptyWindow(profile_, /*should_trigger_session_restore=*/false);
    delete this;
  }

  // Ten seconds, which is far more than closing windows takes.
  static constexpr int kWindowChecks = 100;
  static constexpr base::TimeDelta kWindowCheckEvery = base::Milliseconds(100);

  const raw_ptr<Profile> profile_;
  bool closed_ = false;
  ScopedKeepAlive keep_alive_;
  ScopedProfileKeepAlive profile_keep_alive_;
  base::WeakPtrFactory<SessionJob> weak_factory_{this};
};

}  // namespace

void ForgetSite(Profile* profile,
                const std::string& site,
                const GURL& url,
                base::WeakPtr<content::WebContents> tab) {
  if (site.empty()) {
    return;
  }
  ResetPermissions(profile, url);
  // A remembered "Continue anyway" on the look-alike warning goes too.
  ForgetLookalike(profile, site);
  // And so does a "Continue anyway" on the scam warning, kept until restart.
  ScamService::GetInstance()->ForgetSiteForSession(profile, site);
  auto filter = content::BrowsingDataFilterBuilder::Create(
      content::BrowsingDataFilterBuilder::Mode::kDelete);
  filter->AddRegisterableDomain(site);
  // Owns itself, see RemovalJob.
  (new RemovalJob(profile, base::BindOnce(&ReloadTab, std::move(tab))))
      ->Start(base::Time(), kSiteData, std::move(filter));
}

void ShowForgetSessionDialog(BrowserWindowInterface* browser) {
  // The original profile: from an incognito window too, the question is
  // about the person's browsing, and the window that is left is a plain one.
  Profile* profile = browser->GetProfile()->GetOriginalProfile();
  auto accept = base::BindOnce(
      [](base::WeakPtr<Profile> weak_profile) {
        if (Profile* p = weak_profile.get()) {
          // Owns itself, see SessionJob.
          (new SessionJob(p))->Start();
        }
      },
      profile->GetWeakPtr());
  auto model =
      ui::DialogModel::Builder()
          .SetTitle(u"Forget this session?")
          .AddParagraph(ui::DialogModelLabel(
              u"This closes every tab and window and clears the history, "
              u"cookies, site data and cache from this session. Bookmarks, "
              u"passwords and sign-ins from before this session stay."))
          .AddOkButton(std::move(accept),
                       ui::DialogModel::Button::Params().SetLabel(u"Forget"))
          .AddCancelButton(
              base::DoNothing(),
              ui::DialogModel::Button::Params().SetLabel(u"Cancel"))
          // Enter keeps everything; deleting takes a deliberate choice.
          .OverrideDefaultButton(ui::mojom::DialogButton::kCancel)
          .Build();
  constrained_window::ShowBrowserModal(
      std::move(model), browser->GetWindow()->GetNativeWindow());
}

}  // namespace boring
