// Copyright 2026 boring. BSD style license.

#include "components/boring/webstore/bundled_web_store.h"

#include <optional>
#include <string>

#include "base/base_paths.h"
#include "base/files/file_path.h"
#include "base/files/file_util.h"
#include "base/functional/bind.h"
#include "base/location.h"
#include "base/logging.h"
#include "base/memory/scoped_refptr.h"
#include "base/path_service.h"
#include "base/strings/utf_string_conversions.h"
#include "base/task/thread_pool.h"
#include "base/version.h"
#include "components/boring/webstore/chromium_web_store_version.h"
#include "components/pref_registry/pref_registry_syncable.h"
#include "components/prefs/pref_service.h"
#include "components/user_prefs/user_prefs.h"
#include "content/public/browser/browser_context.h"
#include "content/public/browser/browser_thread.h"
#include "extensions/browser/crx_installer.h"
#include "extensions/browser/extension_registrar.h"
#include "extensions/browser/extension_registry.h"
#include "extensions/browser/extensions_browser_client.h"
#include "extensions/browser/install/crx_install_error.h"
#include "extensions/common/extension.h"
#include "extensions/common/file_util.h"
#include "extensions/common/mojom/manifest.mojom-shared.h"

namespace boring::webstore {

namespace {

// Beside chrome.dll, which is the version folder in an installed copy
// and the one folder of the zip.
constexpr base::FilePath::CharType kBundledDir[] =
    FILE_PATH_LITERAL("boring\\chromium-web-store");

// The installer moves the folder it is given into the profile, so it
// gets a copy, made in the profile's own extension Temp folder. That
// keeps the move on one drive, and Chromium empties that folder on the
// next start if the browser quits halfway.
base::FilePath CopyToTemp(const base::FilePath& source,
                          const base::FilePath& extensions_dir) {
  if (!base::DirectoryExists(source)) {
    LOG(WARNING) << "bundled Chromium Web Store is missing: " << source;
    return base::FilePath();
  }
  base::FilePath temp_root =
      extensions::file_util::GetInstallTempDir(extensions_dir);
  if (temp_root.empty()) {
    return base::FilePath();
  }
  base::FilePath parent;
  if (!base::CreateTemporaryDirInDir(
          temp_root, FILE_PATH_LITERAL("boring_webstore"), &parent)) {
    return base::FilePath();
  }
  base::FilePath copy = parent.Append(source.BaseName());
  if (!base::CopyDirectory(source, copy, /*recursive=*/true)) {
    base::DeletePathRecursively(parent);
    return base::FilePath();
  }
  return copy;
}

void OnInstalled(content::BrowserContext* context,
                 const std::optional<extensions::CrxInstallError>& error) {
  if (error) {
    LOG(WARNING) << "bundled Chromium Web Store did not install: "
                 << base::UTF16ToUTF8(error->message());
    return;
  }
  // The installer holds the profile open until it reports, so on
  // success the profile is still there.
  user_prefs::UserPrefs::Get(context)->SetString(prefs::kBundledVersion,
                                                 kBundledVersion);
}

// `context` is only used if the install succeeds, and a profile that
// went away first never gets that far: the installer lets go of it on
// shutdown and then fails without calling back.
void StartInstall(scoped_refptr<extensions::CrxInstaller> installer,
                  content::BrowserContext* context,
                  const base::FilePath& copy) {
  if (copy.empty()) {
    return;
  }
  installer->AddInstallerCallback(
      base::BindOnce(&OnInstalled, base::Unretained(context)));
  installer->InstallUnpackedCrx(kBundledId, kBundledPublicKey, copy);
}

}  // namespace

void RegisterProfilePrefs(user_prefs::PrefRegistrySyncable* registry) {
  registry->RegisterStringPref(prefs::kBundledVersion, std::string());
}

Action Decide(const std::string& recorded,
              const base::Version* installed,
              bool installed_by_us,
              const base::Version& bundled) {
  if (!installed) {
    // Never given one: install. Given one and it is gone: the person
    // removed it, and it stays removed.
    return recorded.empty() ? Action::kInstall : Action::kNothing;
  }
  if (!installed_by_us) {
    // Their own copy, most likely from GitHub with its own updates.
    // Leave it, and do not put ours in if they remove it later.
    return recorded.empty() ? Action::kRecordOwnCopy : Action::kNothing;
  }
  if (installed->IsValid() && *installed < bundled) {
    return Action::kInstall;
  }
  return recorded == bundled.GetString() ? Action::kNothing
                                         : Action::kRecordBundled;
}

void MaybeInstallBundledWebStore(content::BrowserContext* context) {
  DCHECK_CURRENTLY_ON(content::BrowserThread::UI);
  if (!context || context->IsOffTheRecord() ||
      extensions::ExtensionsBrowserClient::Get()->IsGuestSession(context)) {
    return;
  }
  PrefService* pref_service = user_prefs::UserPrefs::Get(context);
  if (!pref_service) {
    return;
  }

  const extensions::Extension* extension =
      extensions::ExtensionRegistry::Get(context)->GetInstalledExtension(
          kBundledId);
  const bool installed_by_us =
      extension && extension->was_installed_by_default() &&
      extension->location() == extensions::mojom::ManifestLocation::kInternal;
  const base::Version bundled(kBundledVersion);

  switch (Decide(pref_service->GetString(prefs::kBundledVersion),
                 extension ? &extension->version() : nullptr, installed_by_us,
                 bundled)) {
    case Action::kNothing:
      return;
    case Action::kRecordOwnCopy:
      pref_service->SetString(prefs::kBundledVersion, kOwnCopy);
      return;
    case Action::kRecordBundled:
      pref_service->SetString(prefs::kBundledVersion, kBundledVersion);
      return;
    case Action::kInstall:
      break;
  }

  base::FilePath module_dir;
  if (!base::PathService::Get(base::DIR_MODULE, &module_dir)) {
    return;
  }

  // Silent, because the person chose a browser that comes with it; the
  // same way Chromium installs its own default extensions. As an
  // ordinary (kInternal) extension it shows in chrome://extensions and
  // can be turned off or removed there.
  scoped_refptr<extensions::CrxInstaller> installer =
      extensions::CrxInstaller::CreateSilent(context);
  installer->set_install_source(extensions::mojom::ManifestLocation::kInternal);
  installer->set_creation_flags(
      extensions::Extension::WAS_INSTALLED_BY_DEFAULT);
  installer->set_expected_id(kBundledId);
  installer->set_expected_version(bundled,
                                  /*fail_install_if_unexpected=*/true);
  installer->set_delete_source(true);

  base::ThreadPool::PostTaskAndReplyWithResult(
      FROM_HERE,
      {base::MayBlock(), base::TaskPriority::BEST_EFFORT,
       base::TaskShutdownBehavior::SKIP_ON_SHUTDOWN},
      base::BindOnce(
          &CopyToTemp, module_dir.Append(kBundledDir),
          extensions::ExtensionRegistrar::Get(context)->install_directory()),
      base::BindOnce(&StartInstall, installer, base::Unretained(context)));
}

}  // namespace boring::webstore
