/**
 * Story 5.2 — 회원 탈퇴 mutation 훅 (DELETE /v1/users/me).
 *
 * Story 5.1 ``ProfileSubmitError`` / ``useUpdateHealthProfile`` 패턴 1:1 정합 — typed
 * status + code + detail 노출.
 *
 * 본 훅은 *서버 mutation*만 담당 — ``signOut`` / ``queryClient.clear`` / ``router.replace``
 * 호출은 화면 측 책임. CR P8 — onSuccess에서 ``clear()`` 먼저 호출하면 활성 쿼리들이
 * 401로 refetch + authFetch refresh race가 발생 → 화면에서 ``signOut → clear → replace``
 * 순서로 정렬해 일관 처리. PIPA Art.35 정합.
 */
import { useMutation } from '@tanstack/react-query';

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
 * const queryClient = useQueryClient();
 * await mutation.mutateAsync({ reason });
 * await signOut();           // 1) 로컬 토큰/세션 클리어
 * queryClient.clear();        // 2) stale 쿼리 정리(이미 인증 끊긴 후)
 * router.replace('/(auth)/login');
 * ```
 *
 * CR P8 — onSuccess에서 ``clear()`` 호출하면 활성 쿼리들이 401로 즉시 refetch +
 * authFetch refresh race가 발생. 순서 책임은 화면 측에 위임 — ``signOut`` 후 토큰이
 * 클리어된 상태에서 ``clear()`` 호출하면 race 없이 안전.
 */
export function useAccountDelete() {
  return useMutation({
    mutationFn: deleteAccount,
  });
}
