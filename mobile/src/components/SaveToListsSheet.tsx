/** Bottom sheet from the bookmark: tick the lists this company belongs to; create a new one inline. */
import { Ionicons } from '@expo/vector-icons';
import { useState } from 'react';
import { Alert, Modal, Pressable, StyleSheet, Text, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { NamePrompt } from '@/components/NamePrompt';
import { useAuth } from '@/hooks/useAuth';
import { useSaved } from '@/hooks/useSaved';
import { useColors, fontSize, radii, spacing } from '@/theme/colors';

export function SaveToListsSheet({ symbol, visible, onClose }: { symbol: string; visible: boolean; onClose: () => void }) {
  const c = useColors();
  const insets = useSafeAreaInsets();
  const { lists, add, remove, createList } = useSaved();
  const { user } = useAuth();
  const [naming, setNaming] = useState(false);
  return (
    <Modal visible={visible} transparent animationType="slide" onRequestClose={onClose}>
      <Pressable style={styles.backdrop} onPress={onClose} />
      <View style={[styles.sheet, { backgroundColor: c.background, paddingBottom: insets.bottom + spacing.md }]}>
        <Text style={[styles.title, { color: c.textPrimary }]}>Save {symbol} to…</Text>
        {lists.map((l) => {
          const on = l.tickers.includes(symbol);
          return (
            <Pressable key={l.id} onPress={() => (on ? remove(symbol, l.id) : add(symbol, l.id))} style={[styles.row, { borderBottomColor: c.border }]}>
              <Ionicons name={on ? 'checkbox' : 'square-outline'} size={22} color={on ? c.brand : c.textMuted} />
              <Text style={[styles.name, { color: c.textPrimary }]}>{l.name}</Text>
              <Text style={[styles.count, { color: c.textMuted }]}>{l.tickers.length}</Text>
            </Pressable>
          );
        })}
        {user ? (
          <Pressable onPress={() => setNaming(true)} style={styles.row}>
            <Ionicons name="add-circle-outline" size={22} color={c.brand} />
            <Text style={[styles.name, { color: c.brand }]}>New list</Text>
          </Pressable>
        ) : (
          <Text style={[styles.hint, { color: c.textMuted }]}>Sign in (Me tab) to keep several named lists across devices.</Text>
        )}
        <Pressable onPress={onClose} style={[styles.done, { backgroundColor: c.surface, borderColor: c.border }]}>
          <Text style={[styles.doneText, { color: c.textPrimary }]}>Done</Text>
        </Pressable>
      </View>
      <NamePrompt visible={naming} title="New list" placeholder="e.g. Cash cows" confirmLabel="Create" onCancel={() => setNaming(false)}
        onConfirm={async (name) => {
          setNaming(false);
          try { const created = await createList(name); if (created) add(symbol, created.id); }
          catch (e) { Alert.alert('Could not create', String((e as Error).message ?? e)); }
        }} />
    </Modal>
  );
}

const styles = StyleSheet.create({
  backdrop: { flex: 1, backgroundColor: 'rgba(0,0,0,0.35)' },
  sheet: { borderTopLeftRadius: radii.lg, borderTopRightRadius: radii.lg, paddingTop: spacing.lg, paddingHorizontal: spacing.lg },
  title: { fontSize: fontSize.lg, fontWeight: '700', marginBottom: spacing.sm },
  row: { flexDirection: 'row', alignItems: 'center', gap: spacing.md, paddingVertical: 12, borderBottomWidth: StyleSheet.hairlineWidth },
  name: { flex: 1, fontSize: fontSize.md, fontWeight: '600' },
  count: { fontSize: fontSize.xs, fontVariant: ['tabular-nums'] },
  hint: { fontSize: fontSize.sm, paddingVertical: spacing.md },
  done: { marginTop: spacing.md, borderWidth: StyleSheet.hairlineWidth, borderRadius: radii.pill, paddingVertical: 10, alignItems: 'center' },
  doneText: { fontSize: fontSize.sm, fontWeight: '700' },
});
