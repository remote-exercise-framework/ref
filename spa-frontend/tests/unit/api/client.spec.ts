import { beforeEach, describe, expect, it, vi } from 'vitest';
import { ApiError, apiGet, apiPost } from '../../../src/api/client';

/** A Response-alike good enough for the client's narrow usage. */
function res(
  status: number,
  body: unknown,
  opts: { jsonThrows?: boolean } = {},
): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: opts.jsonThrows
      ? () => Promise.reject(new SyntaxError('Unexpected end of JSON input'))
      : () => Promise.resolve(body),
  } as unknown as Response;
}

function mockFetch(response: Response) {
  const f = vi.fn().mockResolvedValue(response);
  globalThis.fetch = f as never;
  return f;
}

/** The init object the client passed to fetch. */
function initOf(f: ReturnType<typeof vi.fn>): RequestInit {
  return f.mock.calls[0][1] as RequestInit;
}

function headersOf(f: ReturnType<typeof vi.fn>): Record<string, string> {
  return initOf(f).headers as Record<string, string>;
}

/** Await a rejection and narrow it to ApiError, failing loudly otherwise. */
async function expectApiError(promise: Promise<unknown>): Promise<ApiError> {
  try {
    await promise;
  } catch (e) {
    if (e instanceof ApiError) return e;
    throw new Error(`expected an ApiError, got ${String(e)}`);
  }
  throw new Error('expected the request to reject, but it resolved');
}

/** Await a rejection without constraining its type. */
async function expectRejection(promise: Promise<unknown>): Promise<unknown> {
  try {
    await promise;
  } catch (e) {
    return e;
  }
  throw new Error('expected the request to reject, but it resolved');
}

describe('api client request assembly', () => {
  beforeEach(() => {
    mockFetch(res(200, { ok: true }));
  });

  it('sends the path and method unchanged on GET', async () => {
    const f = mockFetch(res(200, { ok: true }));

    await apiGet('/api/v2/thing');

    expect(f).toHaveBeenCalledTimes(1);
    expect(f.mock.calls[0][0]).toBe('/api/v2/thing');
    expect(initOf(f).method).toBe('GET');
  });

  it('asks for JSON but sets no Content-Type when there is no body', async () => {
    const f = mockFetch(res(200, {}));

    await apiGet('/x');

    expect(headersOf(f).Accept).toBe('application/json');
    expect('Content-Type' in headersOf(f)).toBe(false);
  });

  it('sets Content-Type and serialises the body on POST', async () => {
    const f = mockFetch(res(200, {}));

    await apiPost('/x', { a: 1, b: 'two' });

    expect(initOf(f).method).toBe('POST');
    expect(headersOf(f)['Content-Type']).toBe('application/json');
    expect(initOf(f).body).toBe('{"a":1,"b":"two"}');
  });

  it('omits Content-Type when the serialised body is falsy', async () => {
    // JSON.stringify(undefined) is undefined, so the `init.body ?` guard
    // sees nothing to describe.
    const f = mockFetch(res(200, {}));

    await apiPost('/x', undefined);

    expect('Content-Type' in headersOf(f)).toBe(false);
  });

  it('does not set credentials, relying on the same-origin default', async () => {
    // Correct for the current Caddy-fronted deployment, where the SPA and
    // the API share an origin. Pinned because a cross-origin move would
    // silently stop sending the session cookie.
    const f = mockFetch(res(200, {}));

    await apiGet('/x');

    expect('credentials' in initOf(f)).toBe(false);
  });

  it('returns the parsed JSON body on success', async () => {
    mockFetch(res(200, { value: 42 }));

    await expect(apiGet<{ value: number }>('/x')).resolves.toEqual({ value: 42 });
  });
});

describe('api client error envelope', () => {
  it('reads a string error as the form message', async () => {
    mockFetch(res(400, { error: 'boom' }));

    const err = await expectApiError(apiGet('/x'));

    expect(err).toBeInstanceOf(ApiError);
    expect(err.form).toBe('boom');
    expect(err.fields).toEqual({});
    expect(err.status).toBe(400);
  });

  it('reads form and fields from an object error', async () => {
    mockFetch(res(400, { error: { form: 'Validation failed', fields: { a: ['bad'] } } }));

    const err = await expectApiError(apiGet('/x'));

    expect(err.form).toBe('Validation failed');
    expect(err.fields).toEqual({ a: ['bad'] });
  });

  it('ignores a non-string form and falls back to the status', async () => {
    mockFetch(res(400, { error: { form: 42 } }));

    const err = await expectApiError(apiGet('/x'));

    expect(err.form).toBe('HTTP 400');
  });

  it('ignores a null fields value', async () => {
    mockFetch(res(400, { error: { form: 'x', fields: null } }));

    const err = await expectApiError(apiGet('/x'));

    expect(err.fields).toEqual({});
  });

  it('passes a malformed fields value through unvalidated', async () => {
    // The declared type is Record<string, string[]>, but nothing enforces
    // it. A bare string reaches Vuetify's :error-messages, which renders
    // it character by character. Pinned so the footgun is visible.
    mockFetch(res(400, { error: { fields: { a: 'not-an-array' } } }));

    const err = await expectApiError(apiGet('/x'));

    expect(err.fields).toEqual({ a: 'not-an-array' });
  });

  it('falls back to the status when the body has no error key', async () => {
    mockFetch(res(422, { detail: 'something else' }));

    const err = await expectApiError(apiGet('/x'));

    expect(err.form).toBe('HTTP 422');
    expect(err.fields).toEqual({});
  });

  it('falls back to the status when the error body is unparseable', async () => {
    mockFetch(res(500, null, { jsonThrows: true }));

    const err = await expectApiError(apiGet('/x'));

    expect(err).toBeInstanceOf(ApiError);
    expect(err.form).toBe('HTTP 500');
    expect(err.fields).toEqual({});
  });

  it('produces a real Error whose message is the form text', async () => {
    mockFetch(res(400, { error: 'nope' }));

    const err = await expectApiError(apiGet('/x'));

    expect(err).toBeInstanceOf(Error);
    expect(err.message).toBe('nope');
  });

  it('throws a raw SyntaxError when a 2xx body is empty', async () => {
    // KNOWN BUG, pinned rather than fixed: a success response with no body
    // escapes the ApiError path entirely, so a caller reading `e.form` or
    // `e.status` gets undefined. Scoreboard.vue is such a caller, and a
    // 204 there surfaces "Unexpected end of JSON input" in the UI.
    mockFetch(res(204, null, { jsonThrows: true }));

    const err = await expectRejection(apiGet('/x'));

    expect(err).toBeInstanceOf(SyntaxError);
    expect(err).not.toBeInstanceOf(ApiError);
  });
});
