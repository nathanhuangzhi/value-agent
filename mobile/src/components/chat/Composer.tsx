/** The message box with its send / stop button. */
import { Ionicons } from '@expo/vector-icons';
import { Pressable, StyleSheet, TextInput, View, type StyleProp, type ViewStyle } from 'react-native';

import { useColors, fontSize, radii, spacing } from '@/theme/colors';

export function Composer({ value, onChange, placeholder, streaming, canSend, onSend, onStop, style }: {
  value: string;
  onChange: (v: string) => void;
  placeholder: string;
  streaming: boolean;
  canSend: boolean;
  onSend: () => void;
  onStop: () => void;
  style?: StyleProp<ViewStyle>;
}) {
  const c = useColors();
  return (
    <View style={[styles.row, style]}>
      <TextInput
        value={value}
        onChangeText={onChange}
        placeholder={placeholder}
        placeholderTextColor={c.textMuted}
        multiline
        editable={!streaming}
        style={[styles.input, { color: c.textPrimary, backgroundColor: c.surface, borderColor: c.border }]}
      />
      {streaming ? (
        <Pressable onPress={onStop} style={[styles.btn, { backgroundColor: c.negative }]} hitSlop={6} accessibilityLabel="Stop">
          <Ionicons name="stop" size={18} color="#fff" />
        </Pressable>
      ) : (
        <Pressable onPress={onSend} disabled={!canSend} style={[styles.btn, { backgroundColor: canSend ? c.brand : c.border }]} hitSlop={6} accessibilityLabel="Send">
          <Ionicons name="arrow-up" size={18} color="#fff" />
        </Pressable>
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  row: { flexDirection: 'row', alignItems: 'flex-end', gap: spacing.sm },
  input: {
    flex: 1, minHeight: 40, maxHeight: 140, fontSize: fontSize.md, lineHeight: 20,
    paddingHorizontal: spacing.md, paddingVertical: 10, borderRadius: radii.pill, borderWidth: StyleSheet.hairlineWidth,
  },
  btn: { width: 36, height: 36, borderRadius: 18, alignItems: 'center', justifyContent: 'center' },
});
