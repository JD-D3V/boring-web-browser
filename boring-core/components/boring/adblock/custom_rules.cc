// Copyright 2026 boring. BSD style license.

#include "components/boring/adblock/custom_rules.h"

#include <algorithm>
#include <deque>
#include <memory>
#include <optional>
#include <set>
#include <string>
#include <utility>

#include "base/command_line.h"
#include "base/files/file_path.h"
#include "base/files/file_util.h"
#include "base/files/important_file_writer.h"
#include "base/functional/bind.h"
#include "base/functional/callback_helpers.h"
#include "base/json/json_reader.h"
#include "base/memory/raw_ptr.h"
#include "base/memory/weak_ptr.h"
#include "base/strings/strcat.h"
#include "base/strings/string_number_conversions.h"
#include "base/strings/string_split.h"
#include "base/strings/string_util.h"
#include "base/supports_user_data.h"
#include "base/task/thread_pool.h"
#include "base/time/time.h"
#include "base/values.h"
#include "components/boring/adblock/adblock_ffi.h"
#include "components/boring/adblock/adblock_service.h"
#include "components/boring/core/boring_prefs.h"
#include "components/prefs/pref_service.h"
#include "components/prefs/scoped_user_pref_update.h"
#include "components/user_prefs/user_prefs.h"
#include "content/public/browser/browser_context.h"
#include "content/public/browser/storage_partition.h"
#include "crypto/sha2.h"
#include "net/base/load_flags.h"
#include "net/base/net_errors.h"
#include "net/base/url_util.h"
#include "net/traffic_annotation/network_traffic_annotation.h"
#include "net/url_request/referrer_policy.h"
#include "services/network/public/cpp/resource_request.h"
#include "services/network/public/cpp/shared_url_loader_factory.h"
#include "services/network/public/cpp/simple_url_loader.h"
#include "services/network/public/mojom/fetch_api.mojom.h"
#include "url/gurl.h"
#include "url/url_constants.h"

namespace boring {

std::vector<CustomRuleProblem> CheckCustomRules(std::string_view text) {
  std::vector<CustomRuleProblem> problems;
  const BoringLibrary* lib = GetBoringLibrary();
  if (!lib) {
    return problems;
  }
  char* json = lib->adblock_check_rules(
      reinterpret_cast<const unsigned char*>(text.data()), text.size());
  if (!json) {
    return problems;
  }
  std::optional<base::ListValue> list =
      base::JSONReader::ReadList(json, base::JSON_PARSE_RFC);
  lib->adblock_string_free(json);
  if (!list) {
    return problems;
  }
  for (const base::Value& item : *list) {
    const base::DictValue* entry = item.GetIfDict();
    if (!entry) {
      continue;
    }
    const std::optional<int> line = entry->FindInt("line");
    const std::string* rule = entry->FindString("rule");
    const std::string* error = entry->FindString("error");
    if (!line || *line < 1 || !rule || !error) {
      continue;
    }
    problems.push_back({static_cast<size_t>(*line), *rule, *error});
  }
  return problems;
}

bool AddCustomRule(content::BrowserContext* context, std::string_view rule) {
  const std::string_view trimmed =
      base::TrimWhitespaceASCII(rule, base::TRIM_ALL);
  if (trimmed.empty() || trimmed.find_first_of("\r\n") != std::string::npos) {
    return false;
  }
  PrefService* prefs = user_prefs::UserPrefs::Get(context);
  if (!prefs) {
    return false;
  }
  std::string text = prefs->GetString(prefs::kBoringCustomRules);
  const std::vector<std::string_view> lines = base::SplitStringPiece(
      text, "\n", base::TRIM_WHITESPACE, base::SPLIT_WANT_NONEMPTY);
  if (std::ranges::find(lines, trimmed) == lines.end()) {
    if (!text.empty() && !text.ends_with('\n')) {
      text.push_back('\n');
    }
    text.append(trimmed);
    text.push_back('\n');
    prefs->SetString(prefs::kBoringCustomRules, text);
  }
  ApplyCustomRules(context);
  return true;
}

void ApplyCustomRules(content::BrowserContext* context) {
  // Reads the prefs and starts a build when the rules changed.
  ProfileLists::ForContext(context);
}

// ---- Filter lists added by address ----

namespace {

// What a list may be and how often it is fetched. Rules from the design:
// https only, weekly, 5 MB, no catalog.
constexpr size_t kMaxUserListBytes = 5 * 1024 * 1024;
constexpr size_t kMaxUserLists = 20;
constexpr size_t kMaxAddressLength = 2048;
constexpr base::TimeDelta kUserListInterval = base::Days(7);
constexpr base::TimeDelta kUserListRetry = base::Days(1);

// Lets a list on this machine be plain http, which is how the smoke test
// serves one: HTTPS-Only mode has no certificate to trust for it. Never
// for any other host.
constexpr char kAllowLocalHttpSwitch[] = "boring-user-lists-allow-http";

constexpr char kUserListFetcherKey[] = "boring.user_list_fetcher";
constexpr base::FilePath::CharType kUserListsDir[] =
    FILE_PATH_LITERAL("Boring User Lists");

constexpr char kNotAListMessage[] =
    "That address did not return a filter list.";

base::FilePath UserListFile(const base::FilePath& profile_dir,
                            std::string_view url) {
  const std::string name =
      base::HexEncodeLower(crypto::SHA256HashString(url)).substr(0, 16);
  return profile_dir.Append(kUserListsDir).AppendASCII(name + ".txt");
}

base::Time TimeField(const base::DictValue& entry, std::string_view key) {
  const std::optional<double> seconds = entry.FindDouble(key);
  return seconds && *seconds > 0 ? base::Time::FromSecondsSinceUnixEpoch(*seconds)
                                 : base::Time();
}

// Empty when `address` can be added, else a plain sentence on why not.
// On success `*out` is the address to fetch, without a fragment.
std::string CheckAddress(std::string_view address, GURL* out) {
  const std::string trimmed(
      base::TrimWhitespaceASCII(address, base::TRIM_ALL));
  if (trimmed.empty()) {
    return "Type the address of a filter list.";
  }
  if (trimmed.size() > kMaxAddressLength) {
    return "That address is too long.";
  }
  GURL url(trimmed);
  const bool local_http =
      url.is_valid() && url.SchemeIs(url::kHttpScheme) &&
      net::IsLocalhost(url) &&
      base::CommandLine::ForCurrentProcess()->HasSwitch(
          kAllowLocalHttpSwitch);
  if (!url.is_valid() || !url.has_host() ||
      (!url.SchemeIs(url::kHttpsScheme) && !local_http)) {
    return "Only addresses that start with https:// can be added.";
  }
  if (url.has_username() || url.has_password()) {
    return "Leave the user name and password out of the address.";
  }
  GURL::Replacements without_fragment;
  without_fragment.ClearRef();
  *out = url.ReplaceComponents(without_fragment);
  return std::string();
}

// A request that carries nothing about the person: no cookies, no
// credentials, no referrer, no cached answer for a weekly refresh, and a
// redirect is an error so it can never leave https.
std::unique_ptr<network::SimpleURLLoader> MakeUserListLoader(const GURL& url) {
  net::NetworkTrafficAnnotationTag annotation =
      net::DefineNetworkTrafficAnnotation("boring_user_filter_list", R"(
        semantics {
          sender: "boring filter lists added by the user"
          description:
            "Downloads a filter list from an address the user typed in, "
            "so its rules can block ads and trackers."
          trigger:
            "When the user adds the list, and then about once a week."
          data:
            "Nothing about the user or the pages they visit. A plain "
            "request for the file, with no cookies and no identifier."
          destination: OTHER
          destination_other: "The address the user typed in."
        }
        policy {
          cookies_allowed: NO
          setting:
            "Only happens for lists the user added. Weekly refresh stops "
            "with Keep blocking lists up to date, on the Protection page."
          policy_exception_justification: "Not implemented yet."
        })");
  auto request = std::make_unique<network::ResourceRequest>();
  request->url = url;
  request->method = "GET";
  request->credentials_mode = network::mojom::CredentialsMode::kOmit;
  request->referrer_policy = net::ReferrerPolicy::NO_REFERRER;
  request->redirect_mode = network::mojom::RedirectMode::kError;
  request->load_flags = net::LOAD_DISABLE_CACHE;
  return network::SimpleURLLoader::Create(std::move(request), annotation);
}

// On a pool thread: checks the text with the same parser as My filters
// and, if it is a list, puts it in place. Returns the reason it was not
// used, empty when it is saved.
std::string CheckAndSave(base::FilePath path, std::string body) {
  if (!base::IsStringUTF8(body)) {
    return kNotAListMessage;
  }
  size_t rule_lines = 0;
  for (std::string_view line : base::SplitStringPiece(
           body, "\n", base::TRIM_WHITESPACE, base::SPLIT_WANT_NONEMPTY)) {
    if (line.front() != '!' && line.front() != '[') {
      ++rule_lines;
    }
  }
  if (rule_lines == 0) {
    return "The list has no rules in it.";
  }
  if (base::TrimWhitespaceASCII(body, base::TRIM_LEADING).front() == '<') {
    return kNotAListMessage;
  }
  // More than half the rules refused means it is not a list in this
  // syntax at all, and a few refused ones are ordinary.
  if (CheckCustomRules(body).size() * 2 > rule_lines) {
    return kNotAListMessage;
  }
  if (!base::CreateDirectory(path.DirName()) ||
      !base::ImportantFileWriter::WriteFileAtomically(path, body)) {
    return "The list could not be saved.";
  }
  return std::string();
}

void DeleteFileInBackground(const base::FilePath& path) {
  base::ThreadPool::PostTask(
      FROM_HERE, {base::MayBlock(), base::TaskPriority::BEST_EFFORT},
      base::BindOnce(base::IgnoreResult(&base::DeleteFile), path));
}

// Sets the outcome of the last try on a list's entry. False when the
// person removed the list in the meantime.
bool NoteTry(PrefService* prefs, const std::string& url,
             const std::string& error) {
  ScopedListPrefUpdate update(prefs, prefs::kBoringUserLists);
  for (base::Value& item : *update) {
    base::DictValue* entry = item.GetIfDict();
    const std::string* entry_url = entry ? entry->FindString("url") : nullptr;
    if (!entry_url || *entry_url != url) {
      continue;
    }
    const double now = base::Time::Now().InSecondsFSinceUnixEpoch();
    entry->Set("tried", now);
    if (error.empty()) {
      entry->Set("updated", now);
      entry->Remove("error");
    } else {
      entry->Set("error", error);
    }
    return true;
  }
  return false;
}

// Downloads the lists one at a time for one profile. Lives with the
// profile, so closing it stops whatever is running.
class UserListFetcher : public base::SupportsUserData::Data {
 public:
  explicit UserListFetcher(content::BrowserContext* context)
      : context_(context) {}

  static UserListFetcher* ForContext(content::BrowserContext* context) {
    auto* fetcher = static_cast<UserListFetcher*>(
        context->GetUserData(kUserListFetcherKey));
    if (!fetcher) {
      auto owned = std::make_unique<UserListFetcher>(context);
      fetcher = owned.get();
      context->SetUserData(kUserListFetcherKey, std::move(owned));
    }
    return fetcher;
  }

  static bool IsPending(content::BrowserContext* context,
                        const std::string& url) {
    auto* fetcher = static_cast<UserListFetcher*>(
        context->GetUserData(kUserListFetcherKey));
    return fetcher && fetcher->pending_.contains(url);
  }

  void Queue(const std::string& url) {
    if (pending_.insert(url).second) {
      queue_.push_back(url);
      StartNext();
    }
  }

  // The person removed the list: stop it if it is running.
  void Forget(const std::string& url) {
    if (!pending_.erase(url)) {
      return;
    }
    std::erase(queue_, url);
    if (url == current_) {
      loader_.reset();
      weak_factory_.InvalidateWeakPtrs();
      current_.clear();
      StartNext();
    }
  }

 private:
  void StartNext() {
    if (!current_.empty() || queue_.empty()) {
      return;
    }
    current_ = queue_.front();
    queue_.pop_front();
    loader_ = MakeUserListLoader(GURL(current_));
    loader_->DownloadToString(
        context_->GetDefaultStoragePartition()
            ->GetURLLoaderFactoryForBrowserProcess()
            .get(),
        base::BindOnce(&UserListFetcher::OnDownloaded,
                       weak_factory_.GetWeakPtr()),
        kMaxUserListBytes);
  }

  void OnDownloaded(std::optional<std::string> body) {
    const int net_error = loader_->NetError();
    loader_.reset();
    if (!body) {
      Finish(net_error == net::ERR_INSUFFICIENT_RESOURCES
                 ? "The list is bigger than 5 MB."
                 : "The list could not be downloaded.");
      return;
    }
    base::ThreadPool::PostTaskAndReplyWithResult(
        FROM_HERE, {base::MayBlock(), base::TaskPriority::USER_VISIBLE},
        base::BindOnce(&CheckAndSave, UserListFile(context_->GetPath(), current_),
                       std::move(*body)),
        base::BindOnce(&UserListFetcher::Finish, weak_factory_.GetWeakPtr()));
  }

  void Finish(std::string error) {
    const std::string url = std::move(current_);
    current_.clear();
    pending_.erase(url);
    PrefService* prefs = user_prefs::UserPrefs::Get(context_);
    if (!prefs || !NoteTry(prefs, url, error)) {
      // Removed while it was being fetched: leave nothing behind.
      DeleteFileInBackground(UserListFile(context_->GetPath(), url));
    }
    ApplyCustomRules(context_);
    StartNext();
  }

  raw_ptr<content::BrowserContext> context_;
  std::deque<std::string> queue_;
  std::set<std::string> pending_;  // queued or running
  std::string current_;
  std::unique_ptr<network::SimpleURLLoader> loader_;
  base::WeakPtrFactory<UserListFetcher> weak_factory_{this};
};

}  // namespace

std::vector<UserListInfo> GetUserLists(content::BrowserContext* context) {
  std::vector<UserListInfo> lists;
  const PrefService* prefs = user_prefs::UserPrefs::Get(context);
  if (!prefs) {
    return lists;
  }
  for (const base::Value& item : prefs->GetList(prefs::kBoringUserLists)) {
    const base::DictValue* entry = item.GetIfDict();
    const std::string* url = entry ? entry->FindString("url") : nullptr;
    if (!url) {
      continue;
    }
    UserListInfo info;
    info.url = *url;
    info.host = GURL(*url).host();
    info.updated = TimeField(*entry, "updated");
    if (const std::string* error = entry->FindString("error")) {
      info.error = *error;
    }
    info.busy = UserListFetcher::IsPending(context, *url);
    lists.push_back(std::move(info));
  }
  return lists;
}

std::string AddUserList(content::BrowserContext* context,
                        std::string_view address) {
  PrefService* prefs = user_prefs::UserPrefs::Get(context);
  if (!prefs || context->IsOffTheRecord()) {
    return "Open this page in a normal window to add a list.";
  }
  GURL url;
  const std::string problem = CheckAddress(address, &url);
  if (!problem.empty()) {
    return problem;
  }
  const base::ListValue& existing = prefs->GetList(prefs::kBoringUserLists);
  if (existing.size() >= kMaxUserLists) {
    return "You can add up to 20 lists. Remove one first.";
  }
  for (const base::Value& item : existing) {
    const base::DictValue* entry = item.GetIfDict();
    const std::string* entry_url = entry ? entry->FindString("url") : nullptr;
    if (entry_url && *entry_url == url.spec()) {
      return "That list is already added.";
    }
  }
  {
    ScopedListPrefUpdate update(prefs, prefs::kBoringUserLists);
    base::DictValue entry;
    entry.Set("url", url.spec());
    update->Append(std::move(entry));
  }
  UserListFetcher::ForContext(context)->Queue(url.spec());
  return std::string();
}

void RemoveUserList(content::BrowserContext* context, std::string_view url) {
  PrefService* prefs = user_prefs::UserPrefs::Get(context);
  if (!prefs) {
    return;
  }
  {
    ScopedListPrefUpdate update(prefs, prefs::kBoringUserLists);
    update->EraseIf([&](const base::Value& item) {
      const base::DictValue* entry = item.GetIfDict();
      const std::string* entry_url = entry ? entry->FindString("url") : nullptr;
      return entry_url && *entry_url == url;
    });
  }
  UserListFetcher::ForContext(context)->Forget(std::string(url));
  DeleteFileInBackground(UserListFile(context->GetPath(), url));
  ApplyCustomRules(context);
}

void MaybeRefreshUserLists(content::BrowserContext* context) {
  PrefService* prefs = user_prefs::UserPrefs::Get(context);
  if (!prefs || !prefs->GetBoolean(prefs::kListUpdates)) {
    return;
  }
  const base::Time now = base::Time::Now();
  std::vector<std::string> due;
  for (const base::Value& item : prefs->GetList(prefs::kBoringUserLists)) {
    const base::DictValue* entry = item.GetIfDict();
    const std::string* url = entry ? entry->FindString("url") : nullptr;
    if (!url || UserListFetcher::IsPending(context, *url)) {
      continue;
    }
    const base::Time updated = TimeField(*entry, "updated");
    const base::Time tried = TimeField(*entry, "tried");
    const bool failed = entry->FindString("error") != nullptr;
    if (tried.is_null() || (failed && now - tried > kUserListRetry) ||
        (!failed && now - updated > kUserListInterval)) {
      due.push_back(*url);
    }
  }
  for (const std::string& url : due) {
    UserListFetcher::ForContext(context)->Queue(url);
  }
}

UserListFiles GetUserListFiles(const PrefService* prefs,
                               const base::FilePath& profile_dir) {
  UserListFiles files;
  for (const base::Value& item : prefs->GetList(prefs::kBoringUserLists)) {
    const base::DictValue* entry = item.GetIfDict();
    const std::string* url = entry ? entry->FindString("url") : nullptr;
    const base::Time updated = entry ? TimeField(*entry, "updated") : base::Time();
    if (!url || updated.is_null()) {
      continue;
    }
    files.paths.push_back(UserListFile(profile_dir, *url));
    base::StrAppend(&files.key,
                    {*url, "@", base::NumberToString(
                                    updated.InSecondsFSinceUnixEpoch()), "\n"});
  }
  return files;
}

}  // namespace boring
