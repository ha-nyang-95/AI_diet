/**
 * Story 5.2 — 회원 탈퇴 mutation 훅 (DELETE /v1/users/me).
 *
 * Story 5.1 ``ProfileSubmitError`` / ``useUpdateHealthProfile`` 패턴 1:1 정합 — typed
 * status + code + detail 노출. 성공 시 ``queryClient.clear()`` 호출 — 모든 query cache
 * 초기화로 logout 후 stale 데이터(profile/macro_goal/notifications 등) 잠시 남는 회귀 차단.
 *
 * 본 훅은 *콜백만* 노출 — ``signOut`` / ``router.replace`` 호출은 화면 측 책임(분리된
 * 책임 — hook은 *서버 mutation* 만, 화면은 *navigation flow* 결정). PIPA Art.35 정합.
 */
import { useMutation, useQueryClient } from '@tanstack/react-query';

import { authFetch } from '@/lib/auth';

export class AccountDeleteError extends Error {
  status: number;
  code?: string;
  detail?: string;

  constructor(status: number, code?: string, detail?: string) {
    super(detail ?? `account delete failed (${status})`);
    this.name = 'AccountDeleteError';
    this.status = status;
    this.code = code;
    this.detail = detail;
  }
}

export interface AccountDeleteRequestBody {
  /** 사유(선택). 빈 string 송신은 서버 측 ``_validate_reason``이 None으로 normalize. */
  reason?: string | null;
}

async function deleteAccount(body: AccountDeleteRequestBody): Promise<void> {
  // body 미송신(빈 reason) 시 빈 객체 송신 — 서버 ``AccountDeleteRequest | None`` 정합.
  const hasReason = body.reason !== undefined && body.reason !== null && body.reason !== '';
  const init: RequestInit = hasReason
    ? {
        method: 'DELETE',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ reason: body.reason }),
      }
    : {
        method: 'DELETE',
      };

  const response = await authFetch('/v1/users/me', init);
  if (response.status === 204) {
    return;
  }
  // 204 외 응답은 모두 실패 분기 — 클라이언트는 RFC 7807 detail 노출.
  let code: string | undefined;
  let detail: string | undefined;
  try {
    const problem = (await response.json()) as { code?: string; detail?: string };
    code = problem.code;
    detail = problem.detail;
  } catch {
    // RFC 7807 본문이 아니면 status만 사용.
  }
  throw new AccountDeleteError(response.status, code, detail);
}

/**
 * Story 5.2 — DELETE /v1/users/me mutation 훅.
 *
 * 사용 예 (settings/account-delete.tsx):
 * ```tsx
 * const mutation = useAccountDelete();
 * await mutation.mutateAsync({ reason });
 * await signOut();
 * router.replace('/(auth)/login');
 * ```
 *
 * ``onSuccess``는 화면 측 콜백 *전*에 ``queryClient.clear()`` 호출 — 모든 query cache
 * 무효화로 logout 후 stale 데이터 회귀 차단.
 */
export function useAccountDelete() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: deleteAccount,
    onSuccess: () => {
      // logout 후 stale 데이터(profile/macro_goal/notifications 등) 회귀 방지 —
      // 모든 queryKey 무효화. signOut/router.replace는 화면 측에서 별도 호출.
      queryClient.clear();
    },
  });
}
