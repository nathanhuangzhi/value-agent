/** Small floating "jump to the bottom" control, shown while the reader is scrolled up. */
import { Ionicons } from '@expo/vector-icons';
import { Pressable, StyleSheet } from 'react-native';

import { useColors } from '@/theme/colors';

export function ScrollToBottomButton({ visible, onPress, bottom = 16 }: { visible: boolean; onPress: () => void; bottom?: number }) {
  const c = useColors();
  if (!visible) return null;
  return (
    <Pressable
      onPress={onPress}
      hitSlop={8}
      accessibilityLabel="Scroll to bottom"
      style={({ pressed }) => [
        styles.btn,
        { bottom, backgroundColor: c.background, borderColor: c.border, opacity: pressed ? 0.7 : 1 },
      ]}
    >
      <Ionicons name="arrow-down" size={18} color={c.textPrimary} />
    </Pressable>
  );
}

const styles = StyleSheet.create({
  btn: {
    position: 'absolute',
    alignSelf: 'center',
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
