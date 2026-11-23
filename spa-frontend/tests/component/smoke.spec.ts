import { afterEach, describe, expect, it } from 'vitest';
import type { VueWrapper } from '@vue/test-utils';
import KeyDownloadCard from '../../src/components/KeyDownloadCard.vue';
import type { KeyResult } from '../../src/api/registration';
import { mountBare, mountInApp } from '../helpers/mount';

/**
 * The gate for the whole vitest layer: proves Vuetify components resolve
 * without vite-plugin-vuetify's autoImport. If these fail with "Failed to
 * resolve component: v-card", nothing else in tests/component can work and
 * the harness in tests/helpers/vuetify.ts is what needs fixing.
 */

const result: KeyResult = {
  signed_mat: 'sig',
  pubkey: 'ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIexample',
  privkey: '-----BEGIN OPENSSH PRIVATE KEY-----\nabc\n-----END OPENSSH PRIVATE KEY-----',
  pubkey_url: '/pub',
  privkey_url: '/priv',
};

describe('vuetify test harness', () => {
  let wrapper: VueWrapper | undefined;

  afterEach(() => {
    wrapper?.unmount();
    wrapper = undefined;
  });

  it('resolves Vuetify components in a bare mount', () => {
    wrapper = mountBare(KeyDownloadCard, { props: { result } });

    expect(wrapper.find('.v-card').exists()).toBe(true);
    expect(wrapper.text()).toContain('ACCESS GRANTED');
    // No unresolved custom element left in the output.
    expect(wrapper.html()).not.toContain('<v-card');
  });

  it('resolves Vuetify components inside a v-app', () => {
    wrapper = mountInApp(KeyDownloadCard, { props: { result } });

    expect(document.querySelector('.v-application')).not.toBeNull();
    expect(document.querySelector('.v-card')).not.toBeNull();
    expect(wrapper.findComponent(KeyDownloadCard).exists()).toBe(true);
  });

  it('applies the shared Vuetify defaults', () => {
    // VCard: { variant: 'outlined' } from src/plugins/vuetify.ts. If the
    // defaults block in tests/helpers/vuetify.ts drifts from production,
    // this is the test that notices.
    wrapper = mountBare(KeyDownloadCard, { props: { result } });

    expect(wrapper.find('.v-card').classes()).toContain('v-card--variant-outlined');
  });
});
