import { afterEach, describe, expect, it, vi } from 'vitest';
import { flushPromises, type VueWrapper } from '@vue/test-utils';
import RestoreKey from '../../src/pages/RestoreKey.vue';
import KeyDownloadCard from '../../src/components/KeyDownloadCard.vue';
import { mountInApp } from '../helpers/mount';

const KEY_RESULT = {
  signed_mat: 'sig',
  pubkey: 'ssh-ed25519 AAAAC3Nzaexample',
  privkey: '-----BEGIN OPENSSH PRIVATE KEY-----\nx\n-----END OPENSSH PRIVATE KEY-----',
  pubkey_url: '/pub',
  privkey_url: '/priv',
};

function jsonResponse(status: number, body: unknown) {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: () => Promise.resolve(body),
  };
}

function mockFetch(status: number, body: unknown) {
  const f = vi.fn().mockResolvedValue(jsonResponse(status, body));
  globalThis.fetch = f as never;
  return f;
}

describe('RestoreKey page', () => {
  let wrapper: VueWrapper | undefined;

  afterEach(() => {
    wrapper?.unmount();
    wrapper = undefined;
  });

  async function fillAndSubmit(matNum = '1234567', password = 'secret') {
    wrapper = mountInApp(RestoreKey);
    await wrapper.vm.$nextTick();

    await wrapper.find('[data-test="restore-mat-num"] input').setValue(matNum);
    await wrapper.find('[data-test="restore-password"] input').setValue(password);
    await wrapper.find('[data-test="restore-form"]').trigger('submit');
    await flushPromises();
    await wrapper.vm.$nextTick();
  }

  it('renders both fields and the submit button', () => {
    wrapper = mountInApp(RestoreKey);

    expect(wrapper.find('[data-test="restore-mat-num"] input').exists()).toBe(true);
    expect(
      wrapper.find('[data-test="restore-password"] input').attributes('type'),
    ).toBe('password');
    expect(wrapper.find('[data-test="restore-submit"]').exists()).toBe(true);
  });

  it('posts exactly the matriculation number and password', async () => {
    const f = mockFetch(200, KEY_RESULT);

    await fillAndSubmit('7654321', 'hunter2');

    expect(f.mock.calls[0][0]).toBe('/api/v2/restore-key');
    expect(JSON.parse(f.mock.calls[0][1].body as string)).toEqual({
      mat_num: '7654321',
      password: 'hunter2',
    });
  });

  it('swaps the form for the key card on success', async () => {
    mockFetch(200, KEY_RESULT);

    await fillAndSubmit();

    expect(wrapper!.findComponent(KeyDownloadCard).exists()).toBe(true);
    expect(wrapper!.find('[data-test="restore-form"]').exists()).toBe(false);
  });

  it('passes the restore variant to the key card', async () => {
    // This is the only place `variant` is set, and the restore-specific
    // alert wording hangs off it.
    mockFetch(200, KEY_RESULT);

    await fillAndSubmit();

    const card = wrapper!.findComponent(KeyDownloadCard);
    expect(card.props('variant')).toBe('restore');
    expect(card.find('[data-test="variant-alert"]').text()).toContain(
      'Your stored keypair is shown below',
    );
  });

  it('shows a form-level banner for an error with no field detail', async () => {
    mockFetch(400, { error: { form: 'Invalid matriculation number or password.' } });

    await fillAndSubmit();

    expect(wrapper!.find('[data-test="form-error"]').text()).toContain(
      'Invalid matriculation number or password.',
    );
    expect(wrapper!.find('[data-test="restore-form"]').exists()).toBe(true);
  });

  it('puts field errors on their inputs and suppresses the banner', async () => {
    mockFetch(400, {
      error: { form: 'Validation failed', fields: { mat_num: ['Not a valid number.'] } },
    });

    await fillAndSubmit();

    expect(wrapper!.find('[data-test="restore-mat-num"]').text()).toContain(
      'Not a valid number.',
    );
    // The banner is deliberately hidden once any field error exists, so
    // the message is not shown twice.
    expect(wrapper!.find('[data-test="form-error"]').exists()).toBe(false);
  });

  it('surfaces a non-ApiError rejection as the banner text', async () => {
    globalThis.fetch = vi.fn().mockRejectedValue(new Error('network down')) as never;

    await fillAndSubmit();

    expect(wrapper!.find('[data-test="form-error"]').text()).toContain('network down');
  });

  it('disables the fields and loads the button while submitting', async () => {
    let release: (v: unknown) => void = () => {};
    globalThis.fetch = vi.fn(
      () => new Promise((resolve) => { release = resolve; }),
    ) as never;

    wrapper = mountInApp(RestoreKey);
    await wrapper.vm.$nextTick();
    await wrapper.find('[data-test="restore-mat-num"] input').setValue('1234567');
    await wrapper.find('[data-test="restore-form"]').trigger('submit');
    await wrapper.vm.$nextTick();

    expect(
      wrapper.find('[data-test="restore-mat-num"] input').attributes('disabled'),
    ).toBeDefined();
    expect(wrapper.find('[data-test="restore-submit"]').classes()).toContain(
      'v-btn--loading',
    );

    release(jsonResponse(200, KEY_RESULT));
    await flushPromises();
  });

  it('clears a previous error when resubmitting', async () => {
    mockFetch(400, { error: { form: 'Wrong password.' } });
    await fillAndSubmit();
    expect(wrapper!.find('[data-test="form-error"]').exists()).toBe(true);

    mockFetch(200, KEY_RESULT);
    await wrapper!.find('[data-test="restore-form"]').trigger('submit');
    await flushPromises();
    await wrapper!.vm.$nextTick();

    expect(wrapper!.find('[data-test="form-error"]').exists()).toBe(false);
    expect(wrapper!.findComponent(KeyDownloadCard).exists()).toBe(true);
  });
});
