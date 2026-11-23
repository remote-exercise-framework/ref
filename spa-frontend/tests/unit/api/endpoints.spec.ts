import { beforeEach, describe, expect, it, vi } from 'vitest';
import { getAuthStatus } from '../../../src/api/auth';
import { getRegistrationMeta, submitRegistration } from '../../../src/api/registration';
import { restoreKey } from '../../../src/api/restoreKey';
import {
  getScoreboardConfig,
  getScoreboardSubmissions,
  getScoreboardSubmissionsAdmin,
} from '../../../src/api/scoreboard';

/**
 * One path-and-method assertion per endpoint wrapper. Cheap, and it catches
 * a typo'd URL that would otherwise only surface in the browser tests —
 * minutes later, as an unrelated-looking render failure.
 */
describe('api endpoint wrappers', () => {
  let f: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    f = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: () => Promise.resolve({}),
    });
    globalThis.fetch = f as never;
  });

  function call() {
    return { path: f.mock.calls[0][0] as string, init: f.mock.calls[0][1] as RequestInit };
  }

  it.each([
    ['getAuthStatus', () => getAuthStatus(), '/api/v2/auth/me'],
    ['getRegistrationMeta', () => getRegistrationMeta(), '/api/v2/registration/meta'],
    ['getScoreboardConfig', () => getScoreboardConfig(), '/api/scoreboard/config'],
    [
      'getScoreboardSubmissions',
      () => getScoreboardSubmissions(),
      '/api/scoreboard/submissions',
    ],
    [
      'getScoreboardSubmissionsAdmin',
      () => getScoreboardSubmissionsAdmin(),
      '/api/scoreboard/submissions/admin',
    ],
  ])('%s GETs %s', async (_name, invoke, path) => {
    await invoke();

    expect(call().path).toBe(path);
    expect(call().init.method).toBe('GET');
  });

  it('submitRegistration POSTs the payload to /api/v2/registration', async () => {
    await submitRegistration({
      mat_num: '1234567',
      firstname: 'Ada',
      surname: 'Lovelace',
      password: 'pw',
      password_rep: 'pw',
    });

    expect(call().path).toBe('/api/v2/registration');
    expect(call().init.method).toBe('POST');
    expect(JSON.parse(call().init.body as string)).toEqual({
      mat_num: '1234567',
      firstname: 'Ada',
      surname: 'Lovelace',
      password: 'pw',
      password_rep: 'pw',
    });
  });

  it('restoreKey POSTs only the credentials to /api/v2/restore-key', async () => {
    await restoreKey({ mat_num: '1234567', password: 'pw' });

    expect(call().path).toBe('/api/v2/restore-key');
    expect(call().init.method).toBe('POST');
    expect(JSON.parse(call().init.body as string)).toEqual({
      mat_num: '1234567',
      password: 'pw',
    });
  });
});
