/**
 * Onboarding 5/6 — 사용법 튜토리얼 (Story 1.6 AC1, AC2).
 *
 * 3 슬라이드(사진 분석 → 한국 1차 출처 인용 → 디스클레이머) — 좌→우 swipe 또는
 * *다음* 탭으로 전환. 마지막 슬라이드의 *시작* 또는 모든 슬라이드의 *건너뛰기*
 * 탭 시 AsyncStorage ``tutorial-seen`` flag set + ``/(auth)/onboarding/profile``로
 * ``router.replace`` (history bloat 방지).
 *
 * 본 화면은 *정보 제공 전용* — 데이터 수집 X, 백엔드 endpoint 호출 X. 카피는
 * 인라인 const(NFR-L1 한국어 1차). RN 표준 ScrollView ``horizontal pagingEnabled``로
 * snap — 외부 swiper 라이브러리 없음(yagni).
 *
 * resume 흐름: 진입 시 ``getTutorialSeen()`` 비동기 fetch → seen=true이면 즉시
 * ``<Redirect href="/profile" />`` (slide 1부터 다시 보일 필요 X). seen=false면
 * 3 슬라이드 노출. fetch 완료 전 ``ActivityIndicator`` (Story 1.5 P9 패턴 정합).
 */
import { Redirect, router } from 'expo-router';
import { useEffect, useRef, useState } from 'react';
import {
  ActivityIndicator,
  Dimensions,
  type NativeScrollEvent,
  type NativeSyntheticEvent,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  View,
} from 'react-native';

import { getTutorialSeen, setTutorialSeen } from '@/features/onboarding/tutorialState';

const TUTORIAL_SLIDES: { title: string; subtitle: string }[] = [
  {
    title: '사진 한 장으로 식단 분석',
    subtitle:
      '카메라로 식사 사진을 찍거나 갤러리에서 선택하면 OCR이 음식을 자동 인식합니다',
  },
  {
    title: '한국 1차 출처 인용 피드백',
    subtitle:
      '식약처·KDRIs·대한비만학회 등 한국 1차 자료를 인용한 피드백을 받습니다',
  },
  {
    title: '디스클레이머 — 의학적 진단 아님',
    subtitle:
      '건강 목표 부합도 점수는 의학적 진단·치료를 대체하지 않습니다. 의료 결정은 의사와 상의하세요',
  },
];

// typedRoutes 갱신 전 ``/(auth)/onboarding/profile`` 라우트가 .expo/types/router.d.ts에
// 미등록 — Story 1.5 패턴 정합으로 cast 우회.
const PROFILE_ROUTE = '/(auth)/onboarding/profile' as Parameters<typeof Redirect>[0]['href'];

export default function OnboardingTutorial() {
  const [seenChecked, setSeenChecked] = useState<boolean | null>(null);
  const [currentIndex, setCurrentIndex] = useState(0);
  const scrollRef = useRef<ScrollView>(null);
  const { width } = Dimensions.get('window');

  useEffect(() => {
    let cancelled = false;
    void (async () => {
      const seen = await getTutorialSeen();
      if (!cancelled) setSeenChecked(seen);
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  // bootstrap 미완료(seen 값 fetch 중) 동안 spinner — flicker 차단(Story 1.5 P9 정합).
  if (seenChecked === null) {
    return (
      <View style={styles.center}>
        <ActivityIndicator />
      </View>
    );
  }
  // resume — 명시적으로 통과한 사용자는 즉시 profile로.
  if (seenChecked) {
    return <Redirect href={PROFILE_ROUTE} />;
  }

  const handleNext = () => {
    const next = currentIndex + 1;
    if (next < TUTORIAL_SLIDES.length) {
      scrollRef.current?.scrollTo({ x: next * width, animated: true });
      setCurrentIndex(next);
    }
  };

  const finish = async () => {
    await setTutorialSeen(true);
    router.replace(PROFILE_ROUTE);
  };

  const handleScroll = (event: NativeSyntheticEvent<NativeScrollEvent>) => {
    const index = Math.round(event.nativeEvent.contentOffset.x / width);
    if (index !== currentIndex && index >= 0 && index < TUTORIAL_SLIDES.length) {
      setCurrentIndex(index);
    }
  };

  const isLast = currentIndex === TUTORIAL_SLIDES.length - 1;

  return (
    <View style={styles.container}>
      <View style={styles.header}>
        <Pressable
          onPress={() => {
            void finish();
          }}
          accessibilityRole="button"
          accessibilityLabel="건너뛰기"
          style={styles.skipButton}
        >
          <Text style={styles.skipText}>건너뛰기</Text>
        </Pressable>
      </View>

      <ScrollView
        ref={scrollRef}
        horizontal
        pagingEnabled
        showsHorizontalScrollIndicator={false}
        onMomentumScrollEnd={handleScroll}
        style={styles.scroll}
      >
        {TUTORIAL_SLIDES.map((slide, index) => (
          <View
            key={slide.title}
            style={[styles.slide, { width }]}
            accessibilityRole="text"
            accessibilityLabel={`튜토리얼 슬라이드 ${index + 1}: ${slide.title}`}
          >
            <Text style={styles.title}>{slide.title}</Text>
            <Text style={styles.subtitle}>{slide.subtitle}</Text>
          </View>
        ))}
      </ScrollView>

      <View style={styles.indicators}>
        {TUTORIAL_SLIDES.map((slide, index) => (
          <View
            key={slide.title}
            style={[styles.dot, index === currentIndex && styles.dotActive]}
          />
        ))}
      </View>

      <View style={styles.footer}>
        {isLast ? (
          <Pressable
            onPress={() => {
              void finish();
            }}
            accessibilityRole="button"
            accessibilityLabel="시작"
            style={styles.primaryButton}
          >
            <Text style={styles.primaryButtonText}>시작</Text>
          </Pressable>
        ) : (
          <Pressable
            onPress={handleNext}
            accessibilityRole="button"
            accessibilityLabel="다음"
            style={styles.primaryButton}
          >
            <Text style={styles.primaryButtonText}>다음</Text>
          </Pressable>
        )}
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: '#fff' },
  center: { flex: 1, alignItems: 'center', justifyContent: 'center' },
  header: {
    flexDirection: 'row',
    justifyContent: 'flex-end',
    paddingHorizontal: 16,
    paddingTop: 56,
    paddingBottom: 8,
  },
  skipButton: { paddingVertical: 8, paddingHorizontal: 12 },
  skipText: { fontSize: 14, color: '#666' },
  scroll: { flex: 1 },
  // NFR-A3 폰트 200% 대응 — 수직 배치 + flexShrink로 wrap 보장.
  slide: {
    flex: 1,
    paddingHorizontal: 32,
    alignItems: 'center',
    justifyContent: 'center',
  },
  title: {
    fontSize: 22,
    fontWeight: '700',
    color: '#222',
    textAlign: 'center',
    marginBottom: 16,
    flexShrink: 1,
  },
  subtitle: {
    fontSize: 15,
    color: '#555',
    textAlign: 'center',
    lineHeight: 22,
    flexShrink: 1,
  },
  indicators: {
    flexDirection: 'row',
    justifyContent: 'center',
    paddingVertical: 12,
  },
  dot: {
    width: 8,
    height: 8,
    borderRadius: 4,
    backgroundColor: '#ccc',
    marginHorizontal: 4,
  },
  dotActive: { backgroundColor: '#1a73e8' },
  footer: { paddingHorizontal: 24, paddingBottom: 32 },
  primaryButton: {
    backgroundColor: '#1a73e8',
    paddingVertical: 14,
    borderRadius: 8,
    alignItems: 'center',
  },
  primaryButtonText: { color: '#fff', fontSize: 16, fontWeight: '600' },
});
