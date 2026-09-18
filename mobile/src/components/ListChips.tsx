/**
 * The row of list chips on the Saved tab: pick a list, "+" makes a new one,
 * long-press renames or deletes (the first list can be renamed, not deleted).
 */
import { Ionicons } from '@expo/vector-icons';
import { useState } from 'react';
import { Alert, Pressable, ScrollView, StyleSheet, Text } from 'react-native';

import type { Watchlist } from '@/api/watchlist';
import { NamePrompt } from '@/components/NamePrompt';
import { useSaved } from '@/hooks/useSaved';
import { useColors, fontSize, radii, spacing } from '@/theme/colors';

export function ListChips({ activeId, onSelect, canManage }: { activeId: number | null; onSelect: (id: number) => void; canManage: boolean }) {
  const c = useColors();
  const { lists, createList, renameList, deleteList } = useSaved();
  const [prompt, setPrompt] = useState<{ mode: 'new' } | { mode: 'rename'; list: Watchlist } | null>(null);

  const manage = (l: Watchlist) => {
    if (!canManage) return;
    const buttons: { text: string; style?: 'cancel' | 'destructive'; onPress?: () => void }[] = [
      { text: 'Rename', onPress: () => setPrompt({ mode: 'rename', list: l }) },
    ];
    if (lists[0]?.id !== l.id) {
      buttons.push({ text: 'Delete list', style: 'destructive', onPress: () =>
        Alert.alert(`Delete "${l.name}"?`, `${l.tickers.length} companies will leave this list.`, [
          { text: 'Cancel', style: 'cancel' },
          { text: 'Delete', style: 'destructive', onPress: () => { deleteList(l.id).catch(() => {}); if (activeId === l.id) onSelect(lists[0].id); } },
        ]) });
    }
    buttons.push({ text: 'Cancel', style: 'cancel' });
    Alert.alert(l.name, `${l.tickers.length} companies`, buttons);
  };

  return (
    <>
      <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={styles.row} keyboardShouldPersistTaps="handled">
        {lists.map((l) => {
          const active = l.id === activeId;
          return (
            <Pressable key={l.id} onPress={() => onSelect(l.id)} onLongPress={() => manage(l)}
              style={[styles.chip, { borderColor: active ? c.brand : c.border, backgroundColor: active ? c.brand : c.surface }]}>
              <Text style={[styles.chipText, { color: active ? '#fff' : c.textPrimary }]}>{l.name}</Text>
              <Text style={[styles.count, { color: active ? 'rgba(255,255,255,0.8)' : c.textMuted }]}>{l.tickers.length}</Text>
            </Pressable>
          );
        })}
        {canManage ? (
          <Pressable onPress={() => setPrompt({ mode: 'new' })} style={[styles.chip, styles.add, { borderColor: c.border }]} accessibilityLabel="New list">
            <Ionicons name="add" size={16} color={c.brand} />
            <Text style={[styles.chipText, { color: c.brand }]}>New list</Text>
          </Pressable>
        ) : null}
      </ScrollView>
      <NamePrompt
        visible={prompt !== null}
        title={prompt?.mode === 'rename' ? 'Rename list' : 'New list'}
        initial={prompt?.mode === 'rename' ? prompt.list.name : ''}
        placeholder="e.g. China ADRs"
        confirmLabel={prompt?.mode === 'rename' ? 'Rename' : 'Create'}
        onCancel={() => setPrompt(null)}
        onConfirm={async (name) => {
          const p = prompt;
          setPrompt(null);
          try {
            if (p?.mode === 'rename') await renameList(p.list.id, name);
            else { const created = await createList(name); if (created) onSelect(created.id); }
          } catch (e) {
            Alert.alert('Could not save', String((e as Error).message ?? e));
          }
        }}
      />
    </>
  );
}

const styles = StyleSheet.create({
  row: { gap: spacing.sm, paddingVertical: spacing.sm },
  chip: { flexDirection: 'row', alignItems: 'center', gap: 6, borderWidth: 1, borderRadius: radii.pill, paddingHorizontal: 12, paddingVertical: 6 },
  add: { borderStyle: 'dashed' },
  chipText: { fontSize: fontSize.sm, fontWeight: '700' },
  count: { fontSize: fontSize.xs, fontVariant: ['tabular-nums'] },
});
