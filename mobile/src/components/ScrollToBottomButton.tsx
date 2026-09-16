/**
 * Small floating "jump to the bottom" control, shown while the reader is
 * scrolled up. Fades and rises in when it appears, shrinks under the
 * finger while pressed and springs back — the ChatGPT / Claude feel.
 */
import { Ionicons } from '@expo/vector-icons';
import { useEffect, useRef, useState } from 'react';
import { Animated, Easing, Pressable, StyleSheet } from 'react-native';

import { useColors } from '@/theme/colors';

export function ScrollToBottomButton({ visible, onPress, bottom = 16 }: { visible: boolean; onPress: () => void; bottom?: number }) {
  const c = useColors();
  const [mounted, setMounted] = useState(visible);
  const appear = useRef(new Animated.Value(visible ? 1 : 0)).current;   // 0 = hidden, 1 = shown
  const press = useRef(new Animated.Value(1)).current;                  // scale while pressed

  // Keep it mounted through the exit animation, then drop it.
  useEffect(() => {
    if (visible) setMounted(true);
    Animated.timing(appear, {
      toValue: visible ? 1 : 0,
      duration: visible ? 180 : 140,
      easing: visible ? Easing.out(Easing.cubic) : Easing.in(Easing.cubic),
      useNativeDriver: true,
    }).start(({ finished }) => { if (finished && !visible) setMounted(false); });
  }, [visible, appear]);

  if (!mounted) return null;
  const pressIn = () => Animated.spring(press, { toValue: 0.86, speed: 40, bounciness: 0, useNativeDriver: true }).start();
  const pressOut = () => Animated.spring(press, { toValue: 1, speed: 20, bounciness: 8, useNativeDriver: true }).start();
  return (
    <Animated.View
      style={[
        styles.wrap,
        {
          bottom,
          opacity: appear,
          transform: [
            { translateY: appear.interpolate({ inputRange: [0, 1], outputRange: [10, 0] }) },
            { scale: Animated.multiply(appear.interpolate({ inputRange: [0, 1], outputRange: [0.85, 1] }), press) },
          ],
        },
      ]}
    >
      <Pressable
        onPress={onPress}
        onPressIn={pressIn}
        onPressOut={pressOut}
        hitSlop={8}
        accessibilityLabel="Scroll to bottom"
        style={[styles.btn, { backgroundColor: c.background, borderColor: c.border }]}
      >
        <Ionicons name="arrow-down" size={18} color={c.textPrimary} />
      </Pressable>
    </Animated.View>
  );
}

const styles = StyleSheet.create({
  wrap: { position: 'absolute', alignSelf: 'center' },
  btn: {
    width: 36,
    height: 36,
    borderRadius: 18,
    borderWidth: StyleSheet.hairlineWidth,
    alignItems: 'center',
    justifyContent: 'center',
    shadowColor: '#000',
    shadowOpacity: 0.15,
    shadowRadius: 6,
    shadowOffset: { width: 0, height: 2 },
    elevation: 3,
  },
});
