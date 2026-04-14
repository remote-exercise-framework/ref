import { apiGet, apiPost } from './client';

export interface GroupChoice {
  name: string;
  count: number;
  max: number;
  full: boolean;
}

export interface RegistrationMeta {
  course_name: string;
  registration_enabled: boolean;
  groups_enabled: boolean;
  max_group_size: number;
  groups: GroupChoice[];
  password_rules: {
    min_length: number;
    min_classes: number;
  };
  mat_num_regex: string;
}

export interface KeyResult {
  signed_mat: string;
  pubkey: string;
  privkey: string | null;
  pubkey_url: string;
  privkey_url: string | null;
}

export interface RegistrationPayload {
  mat_num: string;
  firstname: string;
  surname: string;
  password: string;
  password_rep: string;
  pubkey?: string;
  group_name?: string;
}

export function getRegistrationMeta(): Promise<RegistrationMeta> {
  return apiGet<RegistrationMeta>('/api/v2/registration/meta');
}

export function submitRegistration(
  payload: RegistrationPayload,
): Promise<KeyResult> {
  return apiPost<KeyResult>('/api/v2/registration', payload);
}
