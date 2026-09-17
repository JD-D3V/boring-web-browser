// Copyright 2026 boring. BSD style license.

#include "components/boring/lists/list_updater.h"

#include <algorithm>
#include <string_view>
#include <utility>

#include "base/command_line.h"
#include "base/files/file_path.h"
#include "base/files/file_util.h"
#include "base/functional/bind.h"
#include "base/json/json_reader.h"
#include "base/strings/strcat.h"
#include "base/strings/string_number_conversions.h"
#include "base/strings/string_util.h"
#include "base/task/thread_pool.h"
#include "base/time/time.h"
#include "base/values.h"
#include "components/boring/core/boring_prefs.h"
#include "components/prefs/pref_service.h"
#include "crypto/sha2.h"
#include "net/base/load_flags.h"
#include "net/base/url_util.h"
#include "net/traffic_annotation/network_traffic_annotation.h"
#include "services/network/public/cpp/resource_request.h"
#include "services/network/public/cpp/shared_url_loader_factory.h"
#include "services/network/public/cpp/simple_url_loader.h"
#include "url/url_constants.h"

namespace boring {

namespace {

// Where lists come from. One release tag that is replaced every week,
// so this address never has to change.
constexpr char kDefaultFeedUrl[] =
    "https://github.com/JD-D3V/boring-web-browser/releases/download/lists/";

constexpr char kManifestName[] = "lists.json";

// Read lists from somewhere else, which is how the smoke test drives
// this without touching the real host.
constexpr char kFeedUrlSwitch[] = "boring-list-url";
// Turn updates off for one run, without changing anyone's setting.
constexpr char kDisableSwitch[] = "disable-boring-list-updates";
// Look now, whatever the lists say about their own age. Only the
// smoke test uses this; nothing would ever finish testing if it
// had to wait a week for the real schedule to come round.
constexpr char kCheckNowSwitch[] = "boring-check-lists-now";

// A file whose timestamp is when we last looked and whose contents are
// the version we saw. One plain file rather than a state format, so
// there is nothing that can drift out of step with the lists.
constexpr base::FilePath::CharType kMarkerFile[] =
    FILE_PATH_LITERAL("last-check");
constexpr std::string_view kMarkerVersionKey = "version=";

// While the lists in use are younger than this, nothing is asked for at
// all, so a browser installed this week never says a word.
constexpr base::TimeDelta kFreshEnough = base::Days(7);

// Once they are old enough to be worth replacing, look this often.
constexpr base::TimeDelta kCheckInterval = base::Days(1);

// The manifest is a few hundred bytes and the lists a few megabytes.
// These are what we refuse to read, not what we expect.
constexpr size_t kMaxManifestBytes = 64 * 1024;
constexpr size_t kMaxListBytes = 32 * 1024 * 1024;

std::string HashOfString(std::string_view data) {
  return base::HexEncodeLower(crypto::SHA256HashString(data));
}

std::string HashOfFile(const base::FilePath& path) {
  std::string data;
  if (path.empty() ||
      !base::ReadFileToStringWithMaxSize(path, &data, kMaxListBytes)) {
    return std::string();
  }
  return HashOfString(data);
}

base::FilePath MarkerPath() {
  const base::FilePath dir = GetDownloadedListDir();
  return dir.empty() ? base::FilePath() : dir.Append(kMarkerFile);
}

// The manifest version the last check applied, or 0 when there is none
// on record.
int LastVersionApplied() {
  std::string text;
  const base::FilePath path = MarkerPath();
  if (path.empty() || !base::ReadFileToStringWithMaxSize(path, &text, 1024)) {
    return 0;
  }
  const size_t start = text.find(kMarkerVersionKey);
  if (start == std::string::npos) {
    return 0;
  }
  std::string_view rest =
      std::string_view(text).substr(start + kMarkerVersionKey.size());
  const size_t end = rest.find('\n');
  if (end != std::string_view::npos) {
    rest = rest.substr(0, end);
  }
  int version = 0;
  base::StringToInt(base::TrimWhitespaceASCII(rest, base::TRIM_ALL), &version);
  return version;
}

std::unique_ptr<network::SimpleURLLoader> MakeLoader(const GURL& url,
                                                     bool no_cache) {
  net::NetworkTrafficAnnotationTag annotation =
      net::DefineNetworkTrafficAnnotation("boring_blocking_lists", R"(
        semantics {
          sender: "boring blocking lists"
          description:
            "Downloads the ad, tracker and scam blocking lists the "
            "browser filters with, so that a browser installed months "
            "ago still recognises the scam sites people are being sent "
            "to today."
          trigger:
            "Checked at most once a day, and only once the lists "
            "already in use are more than a week old. A list is "
            "downloaded only when its hash shows it changed."
          data:
            "Nothing about the user or the pages they visit. A plain "
            "request for a fixed file, with no cookies and no "
            "identifier of any kind."
          destination: OTHER
          destination_other: "The project's own release host."
        }
        policy {
          cookies_allowed: NO
          setting:
            "On by default. Turned off with Keep blocking lists up to "
            "date, on the Protection page."
          policy_exception_justification: "Not implemented yet."
        })");

  auto request = std::make_unique<network::ResourceRequest>();
  request->url = url;
  request->method = "GET";
  request->credentials_mode = network::mojom::CredentialsMode::kOmit;
  if (no_cache) {
    // A cached manifest would answer the one question this is asking.
    request->load_flags = net::LOAD_DISABLE_CACHE;
  }
  return network::SimpleURLLoader::Create(std::move(request), annotation);
}

}  // namespace

// static
ListUpdater* ListUpdater::GetInstance() {
  static base::NoDestructor<ListUpdater> instance;
  return instance.get();
}

ListUpdater::ListUpdater() = default;

ListUpdater::~ListUpdater() = default;

// static
GURL ListUpdater::GetFeedUrl() {
  const base::CommandLine* command_line =
      base::CommandLine::ForCurrentProcess();
  GURL url(kDefaultFeedUrl);
  if (command_line->HasSwitch(kFeedUrlSwitch)) {
    url = GURL(command_line->GetSwitchValueASCII(kFeedUrlSwitch));
    // Plain http is allowed only for a server on this machine, which is
    // how the smoke test drives it. Anywhere else these files have to
    // arrive over something nobody on the path can rewrite.
    if (!url.is_valid() ||
        (!url.SchemeIs(url::kHttpsScheme) && !net::IsLocalhost(url))) {
      return GURL();
    }
  }
  // The feed names a folder, so make it read like one before anything
  // is resolved against it.
  std::string spec = url.spec();
  if (!spec.empty() && spec.back() != '/') {
    spec.push_back('/');
    url = GURL(spec);
  }
  return url;
}

// static
bool ListUpdater::IsEnabled(const PrefService* prefs) {
  if (base::CommandLine::ForCurrentProcess()->HasSwitch(kDisableSwitch)) {
    return false;
  }
  // No prefs means nobody has said otherwise, so the default stands.
  return !prefs || prefs->GetBoolean(prefs::kListUpdates);
}

void ListUpdater::MaybeCheck(
    const PrefService* prefs,
    scoped_refptr<network::SharedURLLoaderFactory> factory) {
  DCHECK_CALLED_ON_VALID_SEQUENCE(sequence_checker_);
  if (running_ || !factory || !IsEnabled(prefs) || !GetFeedUrl().is_valid()) {
    return;
  }
  running_ = true;
  asked_ = false;
  all_saved_ = true;
  factory_ = std::move(factory);
  base::ThreadPool::PostTaskAndReplyWithResult(
      FROM_HERE, {base::MayBlock(), base::TaskPriority::BEST_EFFORT},
      base::BindOnce(&ListUpdater::LookAtWhatWeHave),
      base::BindOnce(&ListUpdater::OnLookedAtDisk, weak_factory_.GetWeakPtr()));
}

// static
ListUpdater::Local ListUpdater::LookAtWhatWeHave() {
  Local local;
  if (GetDownloadedListDir().empty()) {
    return local;  // Nowhere to put a list, so nothing worth asking for.
  }

  const base::Time now = base::Time::Now();
  const bool ignore_schedule =
      base::CommandLine::ForCurrentProcess()->HasSwitch(kCheckNowSwitch);

  // While the lists actually in use are still fresh there is nothing to
  // ask about. A missing list has no time at all, which counts as the
  // most urgent case rather than the freshest.
  const base::Time filters_at = GetWrittenAt(GetListPath(ListKind::kFilters));
  const base::Time scam_at = GetWrittenAt(GetListPath(ListKind::kScam));
  if (!ignore_schedule && !filters_at.is_null() && !scam_at.is_null() &&
      now - std::min(filters_at, scam_at) < kFreshEnough) {
    return local;
  }

  // Past that, look no more than once a day.
  const base::Time checked = GetWrittenAt(MarkerPath());
  if (!ignore_schedule && !checked.is_null() &&
      now - checked < kCheckInterval) {
    return local;
  }

  local.worth_asking = true;
  local.version = LastVersionApplied();
  local.filters_sha256 = HashOfFile(GetDownloadedListPath(ListKind::kFilters));
  local.scam_sha256 = HashOfFile(GetDownloadedListPath(ListKind::kScam));
  return local;
}

void ListUpdater::OnLookedAtDisk(Local local) {
  if (!local.worth_asking) {
    Finish();
    return;
  }
  local_ = std::move(local);
  // Until a manifest says otherwise, the version on record is the one
  // already on disk. Without this, giving up part way through would
  // write down version 0 and let a stale manifest back in next time.
  version_ = local_.version;
  asked_ = true;
  loader_ = MakeLoader(GetFeedUrl().Resolve(kManifestName), /*no_cache=*/true);
  loader_->DownloadToString(
      factory_.get(),
      base::BindOnce(&ListUpdater::OnManifest, weak_factory_.GetWeakPtr()),
      kMaxManifestBytes);
}

void ListUpdater::OnManifest(std::optional<std::string> body) {
  loader_.reset();
  // Strict JSON: this file is one we generate ourselves, so there is no
  // reason to accept comments or trailing commas in it.
  std::optional<base::DictValue> parsed;
  if (body) {
    parsed = base::JSONReader::ReadDict(*body, base::JSON_PARSE_RFC);
  }
  if (!parsed) {
    all_saved_ = false;
    Finish();
    return;
  }
  const std::optional<int> version = parsed->FindInt("version");
  const base::ListValue* files = parsed->FindList("files");
  if (!version || !files) {
    all_saved_ = false;
    Finish();
    return;
  }
  // The publisher only ever counts up, so a manifest older than the one
  // already applied is a stale copy and must not walk us backwards.
  if (*version < local_.version) {
    Finish();
    return;
  }
  version_ = *version;

  wanted_.clear();
  next_ = 0;
  for (const base::Value& item : *files) {
    const base::DictValue* entry = item.GetIfDict();
    if (!entry) {
      continue;
    }
    const std::string* name = entry->FindString("name");
    const std::string* sha256 = entry->FindString("sha256");
    const std::optional<int> size = entry->FindInt("size");
    if (!name || !sha256 || !size || *size <= 0 ||
        static_cast<size_t>(*size) > kMaxListBytes) {
      continue;
    }
    const std::optional<ListKind> kind = ListKindFromName(*name);
    if (!kind) {
      continue;  // A list this version of the browser does not know.
    }
    const std::string& have = *kind == ListKind::kFilters
                                  ? local_.filters_sha256
                                  : local_.scam_sha256;
    if (base::EqualsCaseInsensitiveASCII(have, *sha256)) {
      continue;  // Already holding exactly this one.
    }
    wanted_.push_back({*kind, base::ToLowerASCII(*sha256), *size});
  }
  FetchNextList();
}

void ListUpdater::FetchNextList() {
  if (next_ >= wanted_.size()) {
    Finish();
    return;
  }
  const Wanted& wanted = wanted_[next_];
  loader_ = MakeLoader(GetFeedUrl().Resolve(ListFileName(wanted.kind)),
                       /*no_cache=*/false);
  loader_->DownloadToString(factory_.get(),
                            base::BindOnce(&ListUpdater::OnListDownloaded,
                                           weak_factory_.GetWeakPtr()),
                            kMaxListBytes);
}

void ListUpdater::OnListDownloaded(std::optional<std::string> body) {
  loader_.reset();
  if (!body) {
    all_saved_ = false;
    Finish();
    return;
  }
  const Wanted& wanted = wanted_[next_];
  base::ThreadPool::PostTaskAndReplyWithResult(
      FROM_HERE, {base::MayBlock(), base::TaskPriority::BEST_EFFORT},
      base::BindOnce(&ListUpdater::SaveList, wanted.kind, wanted.sha256,
                     wanted.size, std::move(*body)),
      base::BindOnce(&ListUpdater::OnListSaved, weak_factory_.GetWeakPtr()));
}

// static
bool ListUpdater::SaveList(ListKind kind,
                           std::string sha256,
                           int64_t size,
                           std::string body) {
  // What arrived has to be exactly what the manifest promised. Anything
  // else is thrown away and the list in use is left as it is, because a
  // stale list still blocks and a mangled one blocks nothing.
  if (static_cast<int64_t>(body.size()) != size ||
      HashOfString(body) != sha256) {
    return false;
  }
  const base::FilePath dir = GetDownloadedListDir();
  if (dir.empty() || !base::CreateDirectory(dir)) {
    return false;
  }
  const base::FilePath path = dir.AppendASCII(ListFileName(kind));
  const base::FilePath part = path.AddExtensionASCII(".part");
  if (!base::WriteFile(part, body)) {
    return false;
  }
  // Into place in one step, so a browser reading the list never finds
  // half a file there.
  if (!base::ReplaceFile(part, path, nullptr)) {
    base::DeleteFile(part);
    return false;
  }
  return true;
}

void ListUpdater::OnListSaved(bool saved) {
  if (!saved) {
    all_saved_ = false;
    Finish();
    return;
  }
  ++next_;
  FetchNextList();
}

// static
void ListUpdater::RecordCheck(int version) {
  const base::FilePath dir = GetDownloadedListDir();
  if (dir.empty() || !base::CreateDirectory(dir)) {
    return;
  }
  const std::string text = base::StrCat(
      {"# The time on this file is when the browser last looked for newer "
       "lists.\n",
       kMarkerVersionKey, base::NumberToString(version), "\n"});
  base::WriteFile(dir.Append(kMarkerFile), text);
}

void ListUpdater::Finish() {
  // Write down that a check happened even when it did not work, so a
  // host that is down is asked once a day and not on every new tab. The
  // version recorded is the one actually on disk, so a part finished
  // update is picked up again tomorrow.
  if (asked_) {
    base::ThreadPool::PostTask(
        FROM_HERE, {base::MayBlock(), base::TaskPriority::BEST_EFFORT},
        base::BindOnce(&ListUpdater::RecordCheck,
                       all_saved_ ? version_ : local_.version));
  }
  loader_.reset();
  factory_.reset();
  local_ = Local();
  wanted_.clear();
  next_ = 0;
  asked_ = false;
  running_ = false;
}

}  // namespace boring
