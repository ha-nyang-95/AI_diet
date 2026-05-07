/**
 * Story 5.1 AC4 — 건강 프로필 수정 화면 (settings).
 *
 * 진입 가드 ①: ``consentStatus === null`` → 스피너(bootstrap).
 * 진입 가드 ②: ``!basic_consents_complete`` → disclaimer redirect (이론상 (tabs) 가드
 *   통과한 사용자는 미진입 — direct deep link 안전망).
 * 진입 가드 ③ (loading/error): ``useHealthProfileQuery`` 로딩/에러 분기.
 * 진입 가드 ④: ``data.profile_completed_at === null`` → onboarding profile redirect
 *   (수정 진입 차단, POST 흐름 강제 — 미입력 사용자는 *최초 입력*부터). AC4 SOT —
 *   ``useHealthProfileQuery`` ``data``를 single source(``useAuth().user``는 invalidate→
 *   refetch race 가능, GET ``/me/profile``이 정합).
 *
 * Prefill: ``useHealthProfileQuery``(Story 1.5 SOT) → ``data`` arrival 후 폼 mount.
 *
 * 저장 성공 UX: PATCH 성공 → 인라인 토스트 1.5s 가시화 → ``router.back()``(설정 메뉴 복귀).
 * 작성자 mountedRef 가드로 사용자가 1.5s 내 수동 뒤로가기 시 timer no-op.
 * onboarding flow의 ``router.replace("/(tabs)")`` 분기와 분리.
 */
import { Stack, router } from 'expo-router';
import { useEffect, useRef, useState } from 'react';
import {
  ActivityIndicator,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  View,
} from 'react-native';

import { HealthProfileEditForm } from '@/features/settings/HealthProfileEditForm';
import { useHealthProfileQuery } from '@/features/onboarding/useHealthProfile';
import { useAuth } from '@/lib/auth';

export default function SettingsProfileScreen() {
  const { consentStatus } = useAuth();
  const profileQuery = useHealthProfileQuery();
  const [savedAt, setSavedAt] = useState<number | null>(null);
  const mountedRef = useRef(true);
  const backTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    return () => {
      mountedRef.current = false;
      if (backTimerRef.current !== null) {
        clearTimeout(backTimerRef.current);
      }
    };
  }, []);

  // 진입 가드 ①: bootstrap 미완료.
  if (consentStatus === null) {
    return (
      <View style={styles.center}>
        <Stack.Screen options={{ title: '프로필 수정' }} />
        <ActivityIndicator />
      </View>
    );
  }

  // 진입 가드 ②: basic 동의 미통과 (이론상 (tabs) 가드 통과한 사용자는 미진입).
  if (!consentStatus.basic_consents_complete) {
    return (
      <View style={styles.center}>
        <Stack.Screen options={{ title: '프로필 수정' }} />
        <Text style={styles.note}>필수 동의가 필요합니다.</Text>
        <Pressable
          style={styles.linkButton}
          onPress={() => router.replace('/(auth)/onboarding/disclaimer')}
        >
          <Text style={styles.linkButtonText}>동의 화면으로 이동</Text>
        </Pressable>
      </View>
    );
  }

  // 진입 가드 ③ — Prefill 로딩 — query loading 상태(query에 invalidate 후 refetch 동안에도 진입).
  if (profileQuery.isLoading || profileQuery.data === undefined) {
    return (
      <View style={styles.center}>
        <Stack.Screen options={{ title: '프로필 수정' }} />
        <ActivityIndicator />
      </View>
    );
  }

  if (profileQuery.isError) {
    return (
      <View style={styles.center}>
        <Stack.Screen options={{ title: '프로필 수정' }} />
        <Text style={styles.note}>프로필을 불러오지 못했습니다. 잠시 후 다시 시도해 주세요.</Text>
        <Pressable style={styles.linkButton} onPress={() => router.back()}>
          <Text style={styles.linkButtonText}>뒤로</Text>
        </Pressable>
      </View>
    );
  }

  // 진입 가드 ④: 미입력 사용자(``data.profile_completed_at IS NULL``) — 수정 진입 차단.
  // AC4 SOT — ``useHealthProfileQuery`` ``data``가 GET ``/me/profile`` 정합(``useAuth().user``는
  // invalidate→refetch race 가능 → 갓 온보딩한 사용자가 reBounce되는 회귀 차단).
  if (profileQuery.data.profile_completed_at === null) {
    return (
      <View style={styles.center}>
        <Stack.Screen options={{ title: '프로필 수정' }} />
        <Text style={styles.note}>먼저 프로필을 입력해 주세요.</Text>
        <Pressable
          style={styles.linkButton}
          onPress={() => router.replace('/(auth)/onboarding/profile')}
        >
          <Text style={styles.linkButtonText}>프로필 입력으로 이동</Text>
        </Pressable>
      </View>
    );
  }

  return (
    <ScrollView contentContainerStyle={styles.container}>
      <Stack.Screen options={{ title: '프로필 수정' }} />
      <Text style={styles.title}>건강 프로필 수정</Text>
      <Text style={styles.caption}>
        나이·체중·신장·활동 수준·건강 목표·알레르기를 수정하면 다음 분석부터 반영됩니다.
      </Text>

      {savedAt !== null && (
        <View style={styles.toast}>
          <Text style={styles.toastText}>
            프로필이 저장되었습니다. 다음 분석부터 반영됩니다.
          </Text>
        </View>
      )}

      <HealthProfileEditForm
        initial={profileQuery.data}
        mode="edit"
        submitLabel="프로필 저장"
        onSuccess={() => {
          setSavedAt(Date.now());
          // 토스트 가시화 후 1.5s 자연 복귀. 사용자가 1.5s 내 수동 뒤로 시 unmount →
          // mountedRef 가드로 timer no-op(double-back 차단).
          backTimerRef.current = setTimeout(() => {
            if (mountedRef.current) {
              router.back();
            }
          }, 1500);
        }}
      />
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  center: { flex: 1, alignItems: 'center', justifyContent: 'center', padding: 24 },
  container: { padding: 24, paddingBottom: 48, backgroundColor: '#fff' },
  title: { fontSize: 22, fontWeight: '700', marginBottom: 4 },
  caption: { fontSize: 13, color: '#666', marginBottom: 16 },
  note: { fontSize: 14, color: '#444', textAlign: 'center', marginBottom: 12 },
  linkButton: {
    paddingVertical: 12,
    paddingHorizontal: 20,
    borderRadius: 8,
    backgroundColor: '#1a73e8',
    alignSelf: 'center',
  },
  linkButtonText: { color: '#fff', fontSize: 15, fontWeight: '600' },
  toast: {
    backgroundColor: '#e6f4ea',
    borderColor: '#34a853',
    borderWidth: 1,
    borderRadius: 8,
    padding: 12,
    marginBottom: 12,
  },
  toastText: { color: '#1f6f3c', fontSize: 13 },
});
