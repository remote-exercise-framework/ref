import { afterEach, describe, expect, it, vi } from 'vitest';
import { flushPromises, type VueWrapper } from '@vue/test-utils';
import KeyDownloadCard from '../../src/components/KeyDownloadCard.vue';
import type { KeyResult } from '../../src/api/registration';
import { mountBare } from '../helpers/mount';

const PRIVKEY = '-----BEGIN OPENSSH PRIVATE KEY-----\nabc\n-----END OPENSSH PRIVATE KEY-----';

function keyResult(over: Partial<KeyResult> = {}): KeyResult {
  return {
    signed_mat: 'sig',
    pubkey: 'ssh-rsa AAAAB3NzaC1yc2Eexample',
    privkey: PRIVKEY,
    pubkey_url: '/student/download/pubkey',
    privkey_url: '/student/download/privkey',
    ...over,
  };
}

describe('KeyDownloadCard', () => {
  let wrapper: VueWrapper | undefined;

  afterEach(() => {
    wrapper?.unmount();
    wrapper = undefined;
  });

  function mount(result: KeyResult, variant?: 'register' | 'restore') {
    wrapper = mountBare(KeyDownloadCard, {
      props: variant ? { result, variant } : { result },
    });
    return wrapper;
  }

  function downloadAttr(testId: string): string | undefined {
    return wrapper!.find(`[data-test="${testId}"]`).attributes('download');
  }

  describe('download filenames follow the key algorithm', () => {
    it.each([
      ['ssh-ed25519 AAAAC3Nza', 'id_ed25519'],
      ['ecdsa-sha2-nistp256 AAAAE2V', 'id_ecdsa'],
      ['ecdsa-sha2-nistp521 AAAAE2V', 'id_ecdsa'],
      ['ssh-dss AAAAB3Nza', 'id_dsa'],
      ['ssh-rsa AAAAB3Nza', 'id_rsa'],
    ])('maps %s to %s', (pubkey, expected) => {
      mount(keyResult({ pubkey }));

      expect(downloadAttr('privkey-download')).toBe(expected);
      expect(downloadAttr('pubkey-download')).toBe(`${expected}.pub`);
    });

    it.each([
      ['an empty pubkey', ''],
      ['a null pubkey', null],
      ['an undefined pubkey', undefined],
    ])('falls back to id_rsa for %s', (_label, pubkey) => {
      mount(keyResult({ pubkey: pubkey as unknown as string }));

      expect(downloadAttr('privkey-download')).toBe('id_rsa');
    });

    it('falls back to id_rsa for an unrecognised algorithm', () => {
      mount(keyResult({ pubkey: 'ssh-futurecrypto AAAA' }));

      expect(downloadAttr('privkey-download')).toBe('id_rsa');
    });

    it('ignores leading whitespace when reading the algorithm', () => {
      mount(keyResult({ pubkey: '   ssh-ed25519 AAAAC3Nza' }));

      expect(downloadAttr('privkey-download')).toBe('id_ed25519');
    });
  });

  describe('variant alerts', () => {
    it.each([
      ['register', PRIVKEY, 'A keypair was generated for you'],
      ['register', null, 'You provided your own public key'],
      ['restore', PRIVKEY, 'Your stored keypair is shown below'],
      ['restore', null, 'Only your public key is on file'],
    ])('renders exactly one alert for variant=%s privkey=%s', (variant, privkey, text) => {
      mount(
        keyResult({ privkey, privkey_url: privkey ? '/priv' : null }),
        variant as 'register' | 'restore',
      );

      const alerts = wrapper!.findAll('[data-test="variant-alert"]');
      expect(alerts).toHaveLength(1);
      expect(alerts[0].text()).toContain(text);
    });

    it('defaults to the register variant', () => {
      mount(keyResult());

      expect(wrapper!.find('[data-test="variant-alert"]').text()).toContain(
        'A keypair was generated for you',
      );
    });
  });

  describe('private key block', () => {
    it('renders the private key and its download button when both are present', () => {
      mount(keyResult());

      expect(wrapper!.find('[data-test="privkey-block"]').exists()).toBe(true);
      expect(wrapper!.find('[data-test="privkey-download"]').exists()).toBe(true);
    });

    it('omits the download button when privkey_url is null but the key is present', () => {
      mount(keyResult({ privkey_url: null }));

      expect(wrapper!.find('[data-test="privkey-block"]').exists()).toBe(true);
      expect(wrapper!.find('[data-test="privkey-download"]').exists()).toBe(false);
      // The copy button does not depend on the URL.
      expect(wrapper!.find('[data-test="privkey-copy"]').exists()).toBe(true);
    });

    it('omits the whole block when there is no private key', () => {
      mount(keyResult({ privkey: null, privkey_url: null }));

      expect(wrapper!.find('[data-test="privkey-block"]').exists()).toBe(false);
      expect(wrapper!.find('[data-test="privkey-download"]').exists()).toBe(false);
    });

    it('does not react to a private key arriving after mount', async () => {
      // KNOWN BUG, pinned: `hasPrivkey` is computed once in setup from the
      // initial prop rather than as a computed, so a later result object
      // with a private key never reveals the block. Harmless today —
      // Register.vue and RestoreKey.vue both replace the whole card — but
      // it would bite anyone reusing this component with a mutable prop.
      mount(keyResult({ privkey: null, privkey_url: null }));
      expect(wrapper!.find('[data-test="privkey-block"]').exists()).toBe(false);

      await wrapper!.setProps({ result: keyResult() });

      expect(wrapper!.find('[data-test="privkey-block"]').exists()).toBe(false);
      expect(wrapper!.find('[data-test="variant-alert"]').text()).toContain(
        'You provided your own public key',
      );
    });
  });

  describe('copy to clipboard', () => {
    async function clickCopy(testId: string) {
      await wrapper!.find(`[data-test="${testId}"]`).trigger('click');
      await flushPromises();
      await wrapper!.vm.$nextTick();
    }

    function label(testId: string): string {
      return wrapper!.find(`[data-test="${testId}"]`).text();
    }

    it('writes the public key and flips the label back after the timeout', async () => {
      vi.useFakeTimers();
      const result = keyResult();
      mount(result);

      await clickCopy('pubkey-copy');

      expect(navigator.clipboard.writeText).toHaveBeenCalledWith(result.pubkey);
      expect(label('pubkey-copy')).toContain('Copied');

      vi.advanceTimersByTime(1500);
      await wrapper!.vm.$nextTick();

      expect(label('pubkey-copy')).toContain('Copy');
      expect(label('pubkey-copy')).not.toContain('Copied');
    });

    it('writes the private key', async () => {
      mount(keyResult());

      await clickCopy('privkey-copy');

      expect(navigator.clipboard.writeText).toHaveBeenCalledWith(PRIVKEY);
    });

    it('tracks the two copy buttons independently', async () => {
      mount(keyResult());

      await clickCopy('pubkey-copy');

      expect(label('pubkey-copy')).toContain('Copied');
      expect(label('privkey-copy')).not.toContain('Copied');
    });

    it('swallows a clipboard rejection and leaves the label alone', async () => {
      vi.mocked(navigator.clipboard.writeText).mockRejectedValueOnce(
        new Error('denied'),
      );
      mount(keyResult());

      await clickCopy('pubkey-copy');

      // No unhandled rejection, and the optimistic label never flips.
      expect(label('pubkey-copy')).toContain('Copy');
      expect(label('pubkey-copy')).not.toContain('Copied');
    });

    it('does nothing when there is no text to copy', async () => {
      mount(keyResult({ pubkey: '' }));

      await clickCopy('pubkey-copy');

      expect(navigator.clipboard.writeText).not.toHaveBeenCalled();
    });
  });

  it('shows the key material in readonly textareas', () => {
    const result = keyResult();
    mount(result);

    const pub = wrapper!.find('[data-test="pubkey-text"] textarea');
    const priv = wrapper!.find('[data-test="privkey-text"] textarea');

    expect((pub.element as HTMLTextAreaElement).value).toBe(result.pubkey);
    expect((priv.element as HTMLTextAreaElement).value).toBe(PRIVKEY);
    expect(pub.attributes('readonly')).toBeDefined();
    expect(priv.attributes('readonly')).toBeDefined();
  });
});
