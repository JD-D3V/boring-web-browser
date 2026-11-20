// Copyright 2026 boring. BSD style license.

/**
 * @fileoverview
 * 'boring-accounts-page' is Settings, Accounts (ledger item 11): the list
 * of accounts the toolbar's "Your accounts" panel and the new tab page
 * show, with what the panel cannot do: rename, remove, reorder and add an
 * Other account by its addresses. Accounts are shortcuts to each company's
 * own pages; nothing here signs in to anything.
 *
 * Every check is made in the browser (components/boring/accounts, see
 * accounts_handler.h). This page sends what was typed and shows what comes
 * back; it never keeps a list of its own. Names are the person's own text
 * and only ever go in as text.
 */
import 'chrome://resources/cr_elements/cr_button/cr_button.js';
import 'chrome://resources/cr_elements/cr_input/cr_input.js';
import 'chrome://resources/cr_elements/cr_shared_style.css.js';
import '../settings_page/settings_section.js';
import '../settings_shared.css.js';

import {WebUiListenerMixin} from 'chrome://resources/cr_elements/web_ui_listener_mixin.js';
import {sendWithPromise} from 'chrome://resources/js/cr.js';
import {PolymerElement} from 'chrome://resources/polymer/v3_0/polymer/polymer_bundled.min.js';

import type {Route} from '../router.js';
import {RouteObserverMixin, Router} from '../router.js';
import {getSearchManager} from '../search_settings.js';
import type {SettingsPlugin} from '../settings_main/settings_plugin.js';

import {getTemplate} from './boring_accounts_page.html.js';

interface BoringAccount {
  id: string;
  initial: string;
  name: string;
  providerLine: string;
}

interface BoringAccountsAnswer {
  accounts: BoringAccount[];
  full: boolean;
  ok: boolean;
  field?: string;
  error?: string;
}

// The companies' keys, as the browser stores them, and their names.
const PROVIDERS = [
  {key: 'google', name: 'Google'},
  {key: 'proton', name: 'Proton'},
  {key: 'outlook', name: 'Outlook'},
  {key: 'icloud', name: 'iCloud'},
  {key: 'yahoo', name: 'Yahoo'},
];

// Circles by position, as on the toolbar and the new tab page: the accent,
// then the tab group colours, the drawn teal first.
const GROUP_COLOURS = [
  'cyan',
  'blue',
  'red',
  'yellow',
  'green',
  'pink',
  'purple',
  'orange',
];

const BoringAccountsPageElementBase =
    RouteObserverMixin(WebUiListenerMixin(PolymerElement));

export class BoringAccountsPageElement extends BoringAccountsPageElementBase
    implements SettingsPlugin {
  static get is() {
    return 'boring-accounts-page';
  }

  static get template() {
    return getTemplate();
  }

  static get properties() {
    return {
      accounts_: {type: Array, value: () => []},
      full_: {type: Boolean, value: false},
      providers_: {type: Array, value: () => PROVIDERS},
      renamingId_: {type: String, value: ''},
      showOther_: {type: Boolean, value: false},
      otherError_: {type: String, value: ''},
      otherField_: {type: String, value: ''},
      renameValue_: {type: String, value: ''},
      otherName_: {type: String, value: ''},
      otherMail_: {type: String, value: ''},
      otherCalendar_: {type: String, value: ''},
      otherFiles_: {type: String, value: ''},
    };
  }

  declare private accounts_: BoringAccount[];
  declare private full_: boolean;
  declare private providers_: typeof PROVIDERS;
  declare private renamingId_: string;
  declare private showOther_: boolean;
  declare private otherError_: string;
  declare private otherField_: string;
  declare private renameValue_: string;
  declare private otherName_: string;
  declare private otherMail_: string;
  declare private otherCalendar_: string;
  declare private otherFiles_: string;

  override connectedCallback() {
    super.connectedCallback();
    this.addWebUiListener(
        'boring-accounts-changed',
        (answer: BoringAccountsAnswer) => this.show_(answer));
    sendWithPromise<BoringAccountsAnswer>('boringAccountsGet')
        .then(answer => this.show_(answer));
  }

  override currentRouteChanged(newRoute: Route, _oldRoute?: Route) {
    // chrome://settings/accounts?add=other, from the panel's Other button.
    if (newRoute === Router.getInstance().getRoutes().ACCOUNTS &&
        Router.getInstance().getQueryParameters().get('add') === 'other') {
      this.showOther_ = true;
    }
  }

  private show_(answer: BoringAccountsAnswer) {
    this.accounts_ = answer.accounts;
    this.full_ = answer.full;
  }

  private circleStyle_(index: number): string {
    if (index === 0) {
      return 'background: var(--color-sys-primary, #4f46e5); ' +
          'color: var(--color-sys-on-primary, var(--boring-circle-ink));';
    }
    const name = GROUP_COLOURS[(index - 1) % GROUP_COLOURS.length];
    return `background: var(--color-tab-group-tab-strip-frame-active-${
        name}, var(--boring-accounts-group));`;
  }

  private isFirst_(index: number): boolean {
    return index === 0;
  }

  private isLast_(index: number, accounts: BoringAccount[]): boolean {
    return index === accounts.length - 1;
  }

  private isRenaming_(id: string, renamingId: string): boolean {
    return id === renamingId;
  }

  private isNotRenaming_(id: string, renamingId: string): boolean {
    return id !== renamingId;
  }

  private onRenameClick_(e: {model: {item: BoringAccount}}) {
    this.renameValue_ = e.model.item.name;
    this.renamingId_ = e.model.item.id;
  }

  private onRenameCancel_() {
    this.renamingId_ = '';
  }

  private onRenameSave_(e: {model: {item: BoringAccount}}) {
    sendWithPromise<BoringAccountsAnswer>(
        'boringAccountsRename', e.model.item.id, this.renameValue_)
        .then(answer => {
          this.renamingId_ = '';
          this.show_(answer);
        });
  }

  private onRemoveClick_(e: {model: {item: BoringAccount}}) {
    sendWithPromise<BoringAccountsAnswer>(
        'boringAccountsRemove', e.model.item.id)
        .then(answer => this.show_(answer));
  }

  private onMoveUp_(e: {model: {item: BoringAccount}}) {
    this.move_(e.model.item.id, -1);
  }

  private onMoveDown_(e: {model: {item: BoringAccount}}) {
    this.move_(e.model.item.id, 1);
  }

  private move_(id: string, delta: number) {
    sendWithPromise<BoringAccountsAnswer>('boringAccountsMove', id, delta)
        .then(answer => this.show_(answer));
  }

  private onAddKnown_(e: {model: {item: {key: string}}}) {
    sendWithPromise<BoringAccountsAnswer>(
        'boringAccountsAddKnown', e.model.item.key)
        .then(answer => this.show_(answer));
  }

  private onAddOtherOpen_() {
    this.showOther_ = true;
    this.otherError_ = '';
    this.otherField_ = '';
  }

  private onOtherCancel_() {
    this.showOther_ = false;
    this.otherError_ = '';
    this.otherField_ = '';
  }

  private onOtherAdd_() {
    sendWithPromise<BoringAccountsAnswer>(
        'boringAccountsAddOther', this.otherName_, this.otherMail_,
        this.otherCalendar_, this.otherFiles_)
        .then(answer => {
          this.show_(answer);
          if (answer.ok) {
            this.onOtherCancel_();
            this.otherName_ = '';
            this.otherMail_ = '';
            this.otherCalendar_ = '';
            this.otherFiles_ = '';
            return;
          }
          this.otherField_ = answer.field || '';
          this.otherError_ = answer.error || '';
        });
  }

  private isField_(field: string, wanted: string): boolean {
    return field === wanted;
  }

  // SettingsPlugin implementation
  async searchContents(query: string) {
    const searchRequest = await getSearchManager().search(query, this);
    return searchRequest.getSearchResult();
  }
}

declare global {
  interface HTMLElementTagNameMap {
    'boring-accounts-page': BoringAccountsPageElement;
  }
}

customElements.define(BoringAccountsPageElement.is, BoringAccountsPageElement);
