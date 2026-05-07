/**
 * Story 5.3 — 데이터 내보내기 mutation 훅 (GET /v1/users/me/export?format=...).
 *
 * RN 표준 다운로드 패턴 — 브라우저 anchor `download`처럼 직접 OS save dialog가 없는
 * 대신 (1) ``authFetch`` body 가져옴 → (2) ``FileSystem.documentDirectory`` 임시 write →
 * (3) ``Sharing.shareAsync`` OS share sheet으로 사용자가 *Files/Drive/메일* 등 선택.
 *
 * Story 5.2 ``AccountDeleteError`` 패턴 1:1 정합 — typed status + code + detail. ``authFetch``
 * 는 cookie httpOnly 자동 첨부 + 401 시 refresh 재시도(Story 1.2/4.2 SOT).
 *
 * 의존성:
 * - ``expo-file-system ~19.0.x``: ``FileSystem.documentDirectory`` + ``writeAsStringAsync``
 *   (Legacy API SOT — SDK 54의 *next* API는 polish 스토리 forward).
 * - ``expo-sharing ~14.0.x``: ``Sharing.shareAsync(uri)`` iOS UIActivityViewController +
 *   Android Intent.ACTION_SEND 추상화. ``Sharing.isAvailableAsync`` 미가용 시 fallback alert.
 */
import { useMutation } from '@tanstack/react-query';
// expo-file-system SDK 54는 *next* API가 top-level인데, ``documentDirectory``/
// ``writeAsStringAsync``/``EncodingType``는 Legacy SOT로 폴더 분리됨. 본 스토리는 Legacy
// API SOT 채택(spec 명시 — *next* API는 polish 스토리 forward).
import * as FileSystem from 'expo-file-system/legacy';
import * as Sharing from 'expo-sharing';
import { Alert } from 'react-native';

import { authFetch } from '@/lib/auth';

export type DataExportFormat = 'json' | 'csv';

export class DataExportError extends Error {
  status: number;
  code?: string;
  detail?: string;

  constructor(status: number, code?: string, detail?: string) {
    super(detail ?? `data export failed (${status})`);
    this.name = 'DataExportError';
    this.status = status;
    this.code = code;
    this.detail = detail;
  }
}

export interface DataExportRequest {
  format: DataExportFormat;
}

/** KST 기준 ``yyyy-mm-dd`` 문자열. server filename masking과 1:1 동일하지 않으나(server는 user_id
 *  마스킹 prefix 추가) — 모바일 로컬 다운로드는 *생성 일자*가 더 직관적인 식별자. */
function _kstDateString(): string {
  return new Intl.DateTimeFormat('en-CA', { timeZone: 'Asia/Seoul' }).format(new Date());
}

/** KST ``HHmmss`` — 같은 일자 + format 재export 시 silent overwrite 회피용 suffix.
 *  ``balancenote_export_2026-05-08_143205.json`` 형태로 1초 단위 unique. */
function _kstTimeStamp(): string {
  const parts = new Intl.DateTimeFormat('en-GB', {
    timeZone: 'Asia/Seoul',
    hour12: false,
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  }).formatToParts(new Date());
  const get = (type: string): string => parts.find((p) => p.type === type)?.value ?? '00';
  return `${get('hour')}${get('minute')}${get('second')}`;
}

async function exportUserData({ format }: DataExportRequest): Promise<void> {
  const response = await authFetch(`/v1/users/me/export?format=${format}`, {
    method: 'GET',
  });
  if (!response.ok) {
    let code: string | undefined;
    let detail: string | undefined;
    try {
      const problem = (await response.json()) as { code?: string; detail?: string };
      code = problem.code;
      detail = problem.detail;
    } catch {
      // RFC 7807 본문 아니면 status만 사용.
    }
    throw new DataExportError(response.status, code, detail);
  }

  let body = await response.text();

  // 모바일 RN의 Blob 호환성 회피 — string body로 통일(JSON/CSV 둘 다 텍스트 처리).
  // CSV의 BOM은 server 측 첫 chunk에 prefix됨. 단 일부 RN/Hermes 런타임의 ``response.text()``
  // TextDecoder가 leading ``﻿``를 strip할 수 있어 → 누락 시 client에서 prepend 복원
  // (Excel Windows 한국어 헤더 자동 인식 보장).
  if (format === 'csv' && body.charCodeAt(0) !== 0xfeff) {
    body = '﻿' + body;
  }
  // ``HHmmss`` suffix — 같은 일자 + format 재export 시 silent overwrite 회피.
  const filename = `balancenote_export_${_kstDateString()}_${_kstTimeStamp()}.${format}`;

  // documentDirectory는 SDK 54 Legacy API path SOT — *next* API는 polish forward.
  const dir = FileSystem.documentDirectory;
  if (!dir) {
    throw new DataExportError(500, 'mobile.export.no_doc_dir', '내부 저장소에 접근할 수 없습니다.');
  }
  const uri = dir + filename;
  await FileSystem.writeAsStringAsync(uri, body, {
    encoding: FileSystem.EncodingType.UTF8,
  });

  const sharingAvailable = await Sharing.isAvailableAsync();
  if (!sharingAvailable) {
    // 일부 시뮬레이터/Web target에서 미지원 — 사용자에게 위치 안내.
    Alert.alert(
      '공유 기능 미지원',
      `이 기기는 공유 메뉴를 지원하지 않습니다.\n데이터가 앱 임시 저장소에 저장되었습니다:\n${uri}`,
    );
    return;
  }
  await Sharing.shareAsync(uri, {
    mimeType: format === 'json' ? 'application/json' : 'text/csv',
    dialogTitle: '데이터 내보내기',
  });
}

/**
 * Story 5.3 — 데이터 내보내기 mutation 훅.
 *
 * 사용 예 (settings/data-export.tsx):
 * ```tsx
 * const mutation = useDataExport();
 * await mutation.mutateAsync({ format: 'json' });
 * // 성공 시 OS share sheet이 mutationFn 안에서 자동 노출됨.
 * ```
 */
export function useDataExport() {
  return useMutation({
    mutationFn: exportUserData,
  });
}
