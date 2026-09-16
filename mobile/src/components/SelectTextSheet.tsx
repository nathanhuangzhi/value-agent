/**
 * Full-screen "select text" view for a chat message.
 *
 * React Native's selectable <Text> only offers a whole-node "Copy" callout
 * on iOS — no range selection. A read-only multiline TextInput does get
 * the native selection handles, so the message is shown here as plain
 * text (Markdown stripped, tables flattened) where any sentence can be
 * selected and copied; "Copy all" grabs the whole thing.
 */
import { Ionicons } from '@expo/vector-icons';
import { useEffect, useRef, useState } from 'react';
import { Modal, Platform, Pressable, StyleSheet, Text, TextInput, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { useColors, fontSize, radii, spacing } from '@/theme/colors';
import { copyText } from '@/utils/clipboard';

export function SelectTextSheet({ text, visible, onClose }: { text: string | null; visible: boolean; onClose: () => void }) {
  const c = useColors();
  const insets = useSafeAreaInsets();
  const [copied, setCopied] = useState(false);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  useEffect(() => () => { if (timer.current) clearTimeout(timer.current); }, []);
  useEffect(() => { if (!visible) setCopied(false); }, [visible]);

  const copyAll = () => {
    if (!text || !copyText(text)) return;
    setCopied(true);
    if (timer.current) clearTimeout(timer.current);
    timer.current = setTimeout(() => setCopied(false), 1500);
  };

  return (
    <Modal visible={visible} animationType="slide" presentationStyle="pageSheet" onRequestClose={onClose}>
      <View style={[styles.root, { backgroundColor: c.background, paddingTop: Platform.OS === 'ios' ? spacing.md : insets.top }]}>
        <View style={[styles.head, { borderBottomColor: c.border }]}>
          <Text style={[styles.title, { color: c.textPrimary }]}>Select text</Text>
          <Pressable onPress={copyAll} hitSlop={8} style={[styles.pill, { borderColor: c.brand }]}>
            <Ionicons name={copied ? 'checkmark' : 'copy-outline'} size={14} color={c.brand} />
            <Text style={[styles.pillText, { color: c.brand }]}>{copied ? 'Copied' : 'Copy all'}</Text>
          </Pressable>
          <Pressable onPress={onClose} hitSlop={8} style={styles.done}>
            <Text style={[styles.doneText, { color: c.brand }]}>Done</Text>
          </Pressable>
        </View>
        <TextInput
          value={text ?? ''}
          multiline
          editable={false}
          scrollEnabled
          textAlignVertical="top"
          style={[styles.body, { color: c.textPrimary, paddingBottom: insets.bottom + spacing.xl }]}
        />
      </View>
    </Modal>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1 },
  head: {
    flexDirection: 'row', alignItems: 'center', gap: spacing.sm,
    paddingHorizontal: spacing.md, paddingBottom: spacing.sm, borderBottomWidth: StyleSheet.hairlineWidth,
  },
  title: { flex: 1, fontSize: fontSize.md, fontWeight: '700' },
  pill: { flexDirection: 'row', alignItems: 'center', gap: 4, borderWidth: 1, borderRadius: radii.pill, paddingHorizontal: 10, paddingVertical: 4 },
  pillText: { fontSize: fontSize.xs, fontWeight: '700' },
  done: { paddingLeft: spacing.sm, paddingVertical: 4 },
  doneText: { fontSize: fontSize.md, fontWeight: '700' },
  body: { flex: 1, fontSize: fontSize.md, lineHeight: 24, paddingHorizontal: spacing.md, paddingTop: spacing.md },
});
