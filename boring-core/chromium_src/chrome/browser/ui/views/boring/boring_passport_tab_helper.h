// Copyright 2026 boring. BSD style license.

#ifndef CHROME_BROWSER_UI_VIEWS_BORING_BORING_PASSPORT_TAB_HELPER_H_
#define CHROME_BROWSER_UI_VIEWS_BORING_BORING_PASSPORT_TAB_HELPER_H_

#include <string>
#include <vector>

#include "base/memory/weak_ptr.h"
#include "base/task/cancelable_task_tracker.h"
#include "base/time/time.h"
#include "components/autofill/core/browser/foundations/autofill_manager.h"
#include "components/autofill/core/browser/foundations/scoped_autofill_managers_observation.h"
#include "components/autofill/core/common/unique_ids.h"
#include "components/boring/passport/passport_words.h"
#include "components/password_manager/core/browser/password_store/password_store_consumer.h"
#include "components/prefs/pref_change_registrar.h"
#include "content/public/browser/web_contents_observer.h"
#include "content/public/browser/web_contents_user_data.h"
#include "url/gurl.h"

namespace lookalikes {
struct DomainInfo;
}

// The Passport's facts for the page in one tab, all worked out on this
// machine: history, site engagement, the shipped scam list, the person's
// marks and the password store's "is there one" answer. Nothing is sent
// anywhere. Created the first time the tab's address field asks
// (PassportChip), not in tab_helpers.cc: history records a page's visit at
// its committed navigation entry's time, so that time, not the start of the
// navigation, is the "before this page" line, and a helper made late
// answers the same as one made early.
class BoringPassportTabHelper
    : public content::WebContentsObserver,
      public content::WebContentsUserData<BoringPassportTabHelper>,
      public password_manager::PasswordStoreConsumer,
      public autofill::AutofillManager::Observer {
 public:
  struct Facts {
    // The page these facts are for; empty until the first page is seen.
    GURL url;
    // The committed entry's time: visits before it are "before this page".
    base::Time cutoff;
    // Answers still on their way. The chip and the Passport use what is in.
    int pending = 0;
    int visits_before = 0;
    int visits_total = 0;
    int days_before_today = 0;
    base::Time first_visit;
    bool lookalike = false;
    std::string lookalike_of;
    bool lookalike_used_site = false;
    bool asks_card = false;
    bool scam_listed = false;
    bool saved_password = false;
  };

  // Made on first use. Null for a null tab.
  static BoringPassportTabHelper* GetOrCreate(content::WebContents* contents);

  ~BoringPassportTabHelper() override;

  const Facts& facts() const { return facts_; }
  // The facts are this document's: held per origin, since a new document
  // starts them over (PrimaryPageChanged) and a same-document change
  // (history.pushState, replaceState, a fragment) can only keep the origin.
  // Comparing whole addresses let a page drop its own warnings.
  bool FactsAreFor(const GURL& url) const;

  // The page is one the Passport speaks about: http or https, a public
  // name, and the page the address field shows is the committed one.
  bool Eligible() const;
  // Our scam or look-alike warning is showing in this tab.
  bool BlockedPage() const;
  bool MarkedKnown() const;
  // "I know this site" (true) and Forget this site (false).
  void SetMarkedKnown(bool known);

  boring::passport::ChipInputs Inputs(bool editing_or_empty,
                                      bool chromium_text) const;

  // The card fact when autofill does not parse forms for this profile (our
  // defaults turn autofill and password saving off): asks every http or
  // https frame of the page, in an isolated world, one fixed yes or no
  // question. Called at each frame's load and when the Passport opens.
  void AskPageForCardFields();

  // Test only: the facts as a dictionary.
  base::DictValue StateForTesting() const;

 private:
  friend class content::WebContentsUserData<BoringPassportTabHelper>;
  explicit BoringPassportTabHelper(content::WebContents* contents);

  // content::WebContentsObserver:
  void PrimaryPageChanged(content::Page& page) override;
  void DidFinishLoad(content::RenderFrameHost* render_frame_host,
                     const GURL& validated_url) override;

  // password_manager::PasswordStoreConsumer:
  void OnGetPasswordStoreResultsOrErrorFrom(
      password_manager::PasswordStoreInterface* store,
      base::expected<std::vector<password_manager::StoredCredential>,
                     password_manager::PasswordStoreBackendError>
          results_or_error) override;

  // autofill::AutofillManager::Observer: "this page asks for card details".
  // Reads only the predicted type of each field (from the field's
  // autocomplete word or autofill's own guess), never anything typed.
  void OnFieldTypesDetermined(autofill::AutofillManager& manager,
                              autofill::FormGlobalId form,
                              FieldTypeSource source,
                              bool small_forms_were_parsed) override;

  // Whether autofill parses this tab's forms (then OnFieldTypesDetermined
  // gives the card fact and the page is not asked).
  bool AutofillParsesForms() const;
  void AskFrameForCardFields(content::RenderFrameHost* frame);

  void StartQueries();
  void OnEngagedSites(int generation,
                      const std::vector<lookalikes::DomainInfo>& sites);
  void Answered(int generation);
  // Asks the address field to run its icon update again.
  void Changed();

  Facts facts_;
  // Bumped per page so a late answer for an earlier page is dropped.
  int generation_ = 0;
  PrefChangeRegistrar marks_;
  // Every frame's autofill manager of this tab, for the card fact.
  autofill::ScopedAutofillManagersObservation autofill_managers_{this};
  base::CancelableTaskTracker tracker_;
  base::WeakPtrFactory<BoringPassportTabHelper> weak_factory_{this};
  // The password store answers through this; dropped per page.
  base::WeakPtrFactory<password_manager::PasswordStoreConsumer>
      consumer_weak_factory_{this};

  WEB_CONTENTS_USER_DATA_KEY_DECL();
};

#endif  // CHROME_BROWSER_UI_VIEWS_BORING_BORING_PASSPORT_TAB_HELPER_H_
