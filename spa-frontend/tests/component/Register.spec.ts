import { afterEach, describe, expect, it, vi } from 'vitest';
import { flushPromises, type VueWrapper } from '@vue/test-utils';
import Register from '../../src/pages/Register.vue';
import KeyDownloadCard from '../../src/components/KeyDownloadCard.vue';
import type { RegistrationMeta } from '../../src/api/registration';
import { mountInApp } from '../helpers/mount';

const KEY_RESULT = {
  signed_mat: 'sig',
  pubkey: 'ssh-ed25519 AAAAC3Nzaexample',
  privkey: '-----BEGIN OPENSSH PRIVATE KEY-----\nx\n-----END OPENSSH PRIVATE KEY-----',
  pubkey_url: '/pub',
  privkey_url: '/priv',
};

function meta(over: Partial<RegistrationMeta> = {}): RegistrationMeta {
  return {
    course_name: 'OS-Security',
    registration_enabled: true,
    groups_enabled: false,
    max_group_size: 1,
    groups: [],
    password_rules: { min_length: 12, min_classes: 3 },
    mat_num_regex: '^[0-9]{7}$',
    ...over,
  };
}

function json(status: number, body: unknown) {
  return { ok: status >= 200 && status < 300, status, json: () => Promise.resolve(body) };
}

/**
 * Register.vue fetches its metadata on mount and posts on submit, so each
 * test scripts the two responses in order.
 */
function mockFetch(
  metaResponse: ReturnType<typeof json> | Error,
  postResponse?: ReturnType<typeof json> | Error,
) {
  const f = vi.fn();
  const queue = [metaResponse, postResponse];
  f.mockImplementation(() => {
    const next = queue.shift();
    return next instanceof Error ? Promise.reject(next) : Promise.resolve(next);
  });
  globalThis.fetch = f as never;
  return f;
}

describe('Register page', () => {
  let wrapper: VueWrapper | undefined;

  afterEach(() => {
    wrapper?.unmount();
    wrapper = undefined;
  });

  async function mountReady() {
    wrapper = mountInApp(Register);
    await flushPromises();
    await wrapper.vm.$nextTick();
    return wrapper;
  }

  async function fill(values: Record<string, string>) {
    for (const [testId, value] of Object.entries(values)) {
      const field = wrapper!.find(`[data-test="${testId}"] input`);
      if (field.exists()) {
        await field.setValue(value);
      } else {
        await wrapper!.find(`[data-test="${testId}"] textarea`).setValue(value);
      }
    }
  }

  /**
   * Open the group v-select's menu. Vuetify activates it from the inner
   * input, not the field wrapper, and needs the mousedown as well as the
   * click.
   */
  async function openGroupMenu() {
    const input = wrapper!.find('[data-test="group-select"] input');
    await input.trigger('mousedown');
    await input.trigger('click');
    await flushPromises();
    await wrapper!.vm.$nextTick();
  }

  async function submit() {
    await wrapper!.find('[data-test="register-form"]').trigger('submit');
    await flushPromises();
    await wrapper!.vm.$nextTick();
  }

  const VALID = {
    'register-mat-num': '1234567',
    'register-firstname': 'Ada',
    'register-surname': 'Lovelace',
    'register-password': 'correct horse battery',
    'register-password-rep': 'correct horse battery',
  };

  describe('metadata loading', () => {
    it('shows a spinner while the metadata request is in flight', async () => {
      globalThis.fetch = vi.fn(() => new Promise(() => {})) as never;

      wrapper = mountInApp(Register);
      await wrapper.vm.$nextTick();

      expect(wrapper.find('.v-progress-circular').exists()).toBe(true);
      expect(wrapper.find('[data-test="register-card"]').exists()).toBe(false);
    });

    it('shows an error and no form when the metadata request fails', async () => {
      mockFetch(json(500, { error: 'backend on fire' }));

      await mountReady();

      expect(wrapper!.find('[data-test="meta-error"]').text()).toContain(
        'backend on fire',
      );
      expect(wrapper!.find('[data-test="register-card"]').exists()).toBe(false);
    });

    it('renders every field once the metadata arrives', async () => {
      mockFetch(json(200, meta()));

      await mountReady();

      for (const id of Object.keys(VALID)) {
        expect(wrapper!.find(`[data-test="${id}"]`).exists()).toBe(true);
      }
      expect(wrapper!.find('[data-test="register-pubkey"]').exists()).toBe(true);
      expect(wrapper!.find('[data-test="register-submit"]').exists()).toBe(true);
    });
  });

  describe('registration disabled', () => {
    it('warns but still renders the form, with every control disabled', async () => {
      // The warning and the card sit in two separate v-if chains — the
      // card's chain starts at `v-if="result"` — so both render together.
      // That is what makes the per-field `:disabled` bindings load-bearing
      // rather than dead code.
      mockFetch(json(200, meta({ registration_enabled: false })));

      await mountReady();

      expect(wrapper!.find('[data-test="registration-disabled"]').text()).toContain(
        'Registration is currently disabled',
      );
      expect(wrapper!.find('[data-test="register-card"]').exists()).toBe(true);

      for (const id of Object.keys(VALID)) {
        expect(
          wrapper!.find(`[data-test="${id}"] input`).attributes('disabled'),
        ).toBeDefined();
      }
      expect(
        wrapper!.find('[data-test="register-pubkey"] textarea').attributes('disabled'),
      ).toBeDefined();
      expect(wrapper!.find('[data-test="register-submit"]').attributes('disabled')).toBeDefined();
    });
  });

  describe('group selection', () => {
    const withGroups = meta({
      groups_enabled: true,
      max_group_size: 2,
      groups: [
        { name: 'Alpha', count: 1, max: 2, full: false },
        { name: 'Beta', count: 2, max: 2, full: true },
      ],
    });

    it('is absent when groups are disabled', async () => {
      mockFetch(json(200, meta({ groups_enabled: false })));

      await mountReady();

      expect(wrapper!.find('[data-test="group-select"]').exists()).toBe(false);
    });

    it('starts on the Auto Assigned sentinel, not clearable', async () => {
      mockFetch(json(200, withGroups));

      await mountReady();

      const select = wrapper!.find('[data-test="group-select"]');
      expect(select.text()).toContain('Auto Assigned');
      // The placeholder class marks the sentinel in the selection slot.
      expect(select.find('.term-placeholder').exists()).toBe(true);
      // Clearing a sentinel makes no sense, so the icon is hidden.
      expect(select.find('.v-field__clearable').exists()).toBe(false);
    });

    it('lists each group with its occupancy and disables the full one', async () => {
      mockFetch(json(200, withGroups));
      await mountReady();

      await openGroupMenu();

      const items = document.querySelectorAll('.v-list-item');
      const texts = [...items].map((i) => i.textContent ?? '');
      expect(texts.some((t) => t.includes('Alpha (1/2)'))).toBe(true);
      expect(texts.some((t) => t.includes('Beta (full 2/2)'))).toBe(true);

      const beta = [...items].find((i) => (i.textContent ?? '').includes('Beta'))!;
      expect(beta.classList.contains('v-list-item--disabled')).toBe(true);
    });

    it('becomes clearable once a real group is picked, and clears back to the sentinel', async () => {
      mockFetch(json(200, withGroups));
      await mountReady();

      await openGroupMenu();

      const alpha = [...document.querySelectorAll('.v-list-item')].find((i) =>
        (i.textContent ?? '').includes('Alpha'),
      )! as HTMLElement;
      alpha.click();
      await flushPromises();
      await wrapper!.vm.$nextTick();

      const select = wrapper!.find('[data-test="group-select"]');
      expect(select.text()).toContain('Alpha');
      expect(select.find('.term-placeholder').exists()).toBe(false);
      // The handler sits on the icon itself, not the wrapper div, and the
      // icon is the configured clear-icon rather than Vuetify's default.
      const clear = select.find('.v-field__clearable .v-icon');
      expect(clear.exists()).toBe(true);
      expect(clear.classes()).toContain('mdi-close');

      await clear.trigger('click');
      await flushPromises();
      await wrapper!.vm.$nextTick();

      // Back to the empty-string sentinel rather than Vuetify's default
      // null, which is what keeps the selection slot renderable.
      expect(wrapper!.find('[data-test="group-select"]').text()).toContain(
        'Auto Assigned',
      );
      expect(
        wrapper!.find('[data-test="group-select"] .term-placeholder').exists(),
      ).toBe(true);
    });
  });

  describe('submitted payload', () => {
    it('sends the filled fields', async () => {
      const f = mockFetch(json(200, meta()), json(200, KEY_RESULT));
      await mountReady();
      await fill(VALID);

      await submit();

      expect(f.mock.calls[1][0]).toBe('/api/v2/registration');
      expect(JSON.parse(f.mock.calls[1][1].body as string)).toEqual({
        mat_num: '1234567',
        firstname: 'Ada',
        surname: 'Lovelace',
        password: 'correct horse battery',
        password_rep: 'correct horse battery',
      });
    });

    it('omits pubkey entirely when the textarea is empty', async () => {
      const f = mockFetch(json(200, meta()), json(200, KEY_RESULT));
      await mountReady();
      await fill(VALID);

      await submit();

      const body = JSON.parse(f.mock.calls[1][1].body as string);
      expect('pubkey' in body).toBe(false);
    });

    it('sends a whitespace-only pubkey untrimmed', async () => {
      // Documents that trimming is the server's job; the client forwards
      // whatever was typed as long as it is truthy.
      const f = mockFetch(json(200, meta()), json(200, KEY_RESULT));
      await mountReady();
      await fill({ ...VALID, 'register-pubkey': '   ' });

      await submit();

      expect(JSON.parse(f.mock.calls[1][1].body as string).pubkey).toBe('   ');
    });

    it('includes group_name when groups are enabled, even unset', async () => {
      const f = mockFetch(
        json(200, meta({ groups_enabled: true })),
        json(200, KEY_RESULT),
      );
      await mountReady();
      await fill(VALID);

      await submit();

      const body = JSON.parse(f.mock.calls[1][1].body as string);
      expect(body.group_name).toBe('');
    });

    it('omits group_name when groups are disabled', async () => {
      const f = mockFetch(json(200, meta()), json(200, KEY_RESULT));
      await mountReady();
      await fill(VALID);

      await submit();

      expect('group_name' in JSON.parse(f.mock.calls[1][1].body as string)).toBe(false);
    });

    it('does no client-side validation before posting', async () => {
      // Deliberately asserts the absence of a feature: mat_num_regex and
      // password_rules are shown to the user as hints only, so garbage
      // still reaches the server, which is the single validator.
      const f = mockFetch(
        json(200, meta()),
        json(400, { error: { form: 'Validation failed' } }),
      );
      await mountReady();
      await fill({ ...VALID, 'register-mat-num': 'not-a-number', 'register-password': 'x' });

      await submit();

      expect(f).toHaveBeenCalledTimes(2);
    });
  });

  describe('outcome rendering', () => {
    it('replaces the form with the key card on success', async () => {
      mockFetch(json(200, meta()), json(200, KEY_RESULT));
      await mountReady();
      await fill(VALID);

      await submit();

      const card = wrapper!.findComponent(KeyDownloadCard);
      expect(card.exists()).toBe(true);
      expect(card.props('variant')).toBe('register');
      expect(wrapper!.find('[data-test="register-card"]').exists()).toBe(false);
    });

    it('puts field errors on their inputs and suppresses the banner', async () => {
      mockFetch(
        json(200, meta()),
        json(400, {
          error: {
            form: 'Validation failed',
            fields: { mat_num: ['Already registered, please use your password.'] },
          },
        }),
      );
      await mountReady();
      await fill(VALID);

      await submit();

      expect(wrapper!.find('[data-test="register-mat-num"]').text()).toContain(
        'Already registered',
      );
      expect(wrapper!.find('[data-test="form-error"]').exists()).toBe(false);
    });

    it('shows the banner when the error carries no field detail', async () => {
      mockFetch(json(200, meta()), json(400, { error: { form: 'Registration closed.' } }));
      await mountReady();
      await fill(VALID);

      await submit();

      expect(wrapper!.find('[data-test="form-error"]').text()).toContain(
        'Registration closed.',
      );
    });

    it('spreads errors across several fields at once', async () => {
      mockFetch(
        json(200, meta()),
        json(400, {
          error: {
            fields: {
              password: ['Password must be at least 12 characters long (got 1).'],
              password_rep: ['Passwords do not match.'],
            },
          },
        }),
      );
      await mountReady();
      await fill(VALID);

      await submit();

      expect(wrapper!.find('[data-test="register-password"]').text()).toContain(
        'at least 12 characters',
      );
      expect(wrapper!.find('[data-test="register-password-rep"]').text()).toContain(
        'do not match',
      );
    });

    it('disables the fields and loads the button while submitting', async () => {
      let release: (v: unknown) => void = () => {};
      const f = vi.fn();
      f.mockResolvedValueOnce(json(200, meta()));
      f.mockImplementationOnce(() => new Promise((r) => { release = r; }));
      globalThis.fetch = f as never;

      await mountReady();
      await fill(VALID);
      await wrapper!.find('[data-test="register-form"]').trigger('submit');
      await wrapper!.vm.$nextTick();

      expect(
        wrapper!.find('[data-test="register-mat-num"] input').attributes('disabled'),
      ).toBeDefined();
      expect(wrapper!.find('[data-test="register-submit"]').classes()).toContain(
        'v-btn--loading',
      );

      release(json(200, KEY_RESULT));
      await flushPromises();
    });

    it('shows the password hint built from the server rules', async () => {
      mockFetch(json(200, meta({ password_rules: { min_length: 16, min_classes: 2 } })));

      await mountReady();

      const text = wrapper!.find('[data-test="register-password"]').text();
      expect(text).toContain('at least 16 characters');
      expect(text).toContain('least 2 of');
    });
  });
});
