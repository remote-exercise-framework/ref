import { apiPost } from './client';
import type { KeyResult } from './registration';

export interface RestoreKeyPayload {
  mat_num: string;
  password: string;
}

export function restoreKey(payload: RestoreKeyPayload): Promise<KeyResult> {
  return apiPost<KeyResult>('/api/v2/restore-key', payload);
}
