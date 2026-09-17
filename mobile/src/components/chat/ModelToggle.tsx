/** Flash | Pro segmented control. */
import { Pressable, StyleSheet, Text, View } from 'react-native';

import type { ModelKey } from '@/api/ai';
import { useColors, fontSize, radii } from '@/theme/colors';

export function ModelToggle({ value, onChange }: { value: ModelKey; onChange: (m: ModelKey) => void }) {
  const c = useColors();
  return (
    <View style={[styles.segment, { borderColor: c.border, backgroundColor: c.surface }]}>
      {(['flash', 'pro'] as ModelKey[]).map((m) => (
        <Pressable key={m} onPress={() => onChange(m)} style={[styles.btn, value === m && { backgroundColor: c.brand }]}>
          <Text style={[styles.label, { color: value === m ? '#fff' : c.textMuted }]}>{m === 'flash' ? 'Flash' : 'Pro'}</Text>
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
