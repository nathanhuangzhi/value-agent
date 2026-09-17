/** Flash | Pro segmented control. */
import { Pressable, StyleSheet, Text, View } from 'react-native';

import type { ModelKey, ModelOption } from '@/api/ai';
import { useColors, fontSize, radii } from '@/theme/colors';

export function ModelToggle({ value, onChange, options }: { value: ModelKey; onChange: (m: ModelKey) => void; options: ModelOption[] }) {
  const c = useColors();
  return (
    <View style={[styles.segment, { borderColor: c.border, backgroundColor: c.surface }]}>
      {options.map((o) => (
        <Pressable key={o.key} onPress={() => onChange(o.key)} style={[styles.btn, value === o.key && { backgroundColor: c.brand }]} accessibilityHint={o.hint}>
          <Text style={[styles.label, { color: value === o.key ? '#fff' : c.textMuted }]}>{o.label}</Text>
        </Pressable>
      ))}
    </View>
  );
}

const styles = StyleSheet.create({
  segment: { flexDirection: 'row', borderWidth: StyleSheet.hairlineWidth, borderRadius: radii.pill, padding: 2 },
  btn: { paddingHorizontal: 10, paddingVertical: 4, borderRadius: radii.pill },
  label: { fontSize: fontSize.xs, fontWeight: '700' },
});
