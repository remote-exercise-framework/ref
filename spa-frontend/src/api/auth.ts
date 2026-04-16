import { apiGet } from './client';

export interface AuthStatus {
  authenticated: boolean;
  is_admin: boolean;
  is_grading_assistant: boolean;
}

export function getAuthStatus(): Promise<AuthStatus> {
  return apiGet<AuthStatus>('/api/v2/auth/me');
}
