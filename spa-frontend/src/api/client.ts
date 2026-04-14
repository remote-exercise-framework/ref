// Tiny fetch wrapper for the SPA.
//
// Every request goes to a relative path; Vite's dev/preview proxy
// forwards /api, /static and /student/download to the Flask `web`
// container. Non-2xx responses throw an ApiError that carries the
// `{error: {form, fields}}` envelope so pages can surface per-field
// validation messages on the right input.

export type FieldErrors = Record<string, string[]>;

export class ApiError extends Error {
  status: number;
  form: string;
  fields: FieldErrors;

  constructor(status: number, form: string, fields: FieldErrors = {}) {
    super(form);
    this.status = status;
    this.form = form;
    this.fields = fields;
  }
}

async function parseError(res: Response): Promise<ApiError> {
  let form = `HTTP ${res.status}`;
  let fields: FieldErrors = {};
  try {
    const body = await res.json();
    if (body && typeof body === 'object' && body.error) {
      if (typeof body.error === 'string') {
        form = body.error;
      } else if (typeof body.error === 'object') {
        if (typeof body.error.form === 'string') form = body.error.form;
        if (body.error.fields && typeof body.error.fields === 'object') {
          fields = body.error.fields as FieldErrors;
        }
      }
    }
  } catch {
    /* leave defaults */
  }
  return new ApiError(res.status, form, fields);
}

async function request<T>(
  path: string,
  init: RequestInit = {},
): Promise<T> {
  const res = await fetch(path, {
    ...init,
    headers: {
      Accept: 'application/json',
      ...(init.body ? { 'Content-Type': 'application/json' } : {}),
      ...(init.headers || {}),
    },
  });
  if (!res.ok) throw await parseError(res);
  return (await res.json()) as T;
}

export function apiGet<T>(path: string): Promise<T> {
  return request<T>(path, { method: 'GET' });
}

export function apiPost<T>(path: string, body: unknown): Promise<T> {
  return request<T>(path, { method: 'POST', body: JSON.stringify(body) });
}
