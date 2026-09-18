/** Small cross-platform "enter a name" dialog (Alert.prompt is iOS-only). */
import { useEffect, useState } from 'react';
import { KeyboardAvoidingView, Modal, Platform, Pressable, StyleSheet, Text, TextInput, View } from 'react-native';

import { useColors, fontSize, radii, spacing } from '@/theme/colors';

export function NamePrompt({ visible, title, initial = '', placeholder, confirmLabel = 'Save', onConfirm, onCancel }: {
  visible: boolean; title: string; initial?: string; placeholder?: string; confirmLabel?: string;
  onConfirm: (name: string) => void; onCancel: () => void;
}) {
  const c = useColors();
  const [value, setValue] = useState(initial);
  useEffect(() => { if (visible) setValue(initial); }, [visible, initial]);
  const ok = value.trim().length > 0;
  return (
    <Modal visible={visible} transparent animationType="fade" onRequestClose={onCancel}>
      <KeyboardAvoidingView behavior={Platform.OS === 'ios' ? 'padding' : undefined} style={styles.backdrop}>
        <Pressable style={StyleSheet.absoluteFill} onPress={onCancel} />
        <View style={[styles.card, { backgroundColor: c.background, borderColor: c.border }]}>
          <Text style={[styles.title, { color: c.textPrimary }]}>{title}</Text>
          <TextInput
            value={value}
            onChangeText={setValue}
            placeholder={placeholder}
            placeholderTextColor={c.textMuted}
            autoFocus
            returnKeyType="done"
            onSubmitEditing={() => ok && onConfirm(value.trim())}
            style={[styles.input, { color: c.textPrimary, backgroundColor: c.surface, borderColor: c.border }]}
          />
          <View style={styles.row}>
            <Pressable onPress={onCancel} hitSlop={8} style={styles.btn}><Text style={[styles.btnText, { color: c.textMuted }]}>Cancel</Text></Pressable>
            <Pressable onPress={() => ok && onConfirm(value.trim())} hitSlop={8} style={[styles.btn, styles.primary, { backgroundColor: ok ? c.brand : c.border }]}>
              <Text style={[styles.btnText, { color: '#fff' }]}>{confirmLabel}</Text>
            </Pressable>
          </View>
        </View>
      </KeyboardAvoidingView>
    </Modal>
  );
}

const styles = StyleSheet.create({
  backdrop: { flex: 1, backgroundColor: 'rgba(0,0,0,0.35)', justifyContent: 'center', padding: spacing.xl },
  card: { borderWidth: StyleSheet.hairlineWidth, borderRadius: radii.lg, padding: spacing.lg, gap: spacing.md },
  title: { fontSize: fontSize.md, fontWeight: '700' },
  input: { borderWidth: StyleSheet.hairlineWidth, borderRadius: radii.md, paddingHorizontal: spacing.md, paddingVertical: 10, fontSize: fontSize.md },
  row: { flexDirection: 'row', justifyContent: 'flex-end', gap: spacing.md },
  btn: { paddingVertical: 8, paddingHorizontal: spacing.md, borderRadius: radii.pill },
  primary: { minWidth: 84, alignItems: 'center' },
  btnText: { fontSize: fontSize.sm, fontWeight: '700' },
});
