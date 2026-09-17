/**
 * One chat turn in the ChatGPT / Claude layout: the user's message in a
 * soft bubble on the right, the assistant's reply as full-width text with
 * a small footer (Select · model · cost). Text is natively selectable.
 */
import { Ionicons } from '@expo/vector-icons';
import { ActivityIndicator, Pressable, StyleSheet, Text, View } from 'react-native';

import type { ChatMessage } from '@/api/ai';
import { Markdown, SelectableProse, hasTable, toPlainText } from '@/components/Markdown';
import { useColors, chatType, fontSize, spacing } from '@/theme/colors';
import { modelLabel } from '@/utils/format';

export type StreamingState = { status: string | null; text: string } | null;

export function MessageRow({ msg, streaming = null, onSelect, contentW, showSources = true }: {
  msg: ChatMessage;
  /** Non-null while this (assistant) row is the reply being written. */
  streaming?: StreamingState;
  onSelect: (text: string) => void;
  /** Width the reply may use — tables size their columns from it. */
  contentW?: number;
  showSources?: boolean;
}) {
  const c = useColors();
  if (msg.role === 'user') {
    return (
      <View style={styles.userRow}>
        <View style={[styles.userBubble, { backgroundColor: c.chatBubble }]}>
          <SelectableProse style={{ ...styles.userText, color: c.textPrimary }}>{msg.content}</SelectableProse>
        </View>
      </View>
    );
  }
  const usage = msg.usage;
  const meta = [
    showSources && msg.companies?.length ? `data: ${msg.companies.join(', ')}` : null,
    modelLabel(msg.model) || null,
    usage?.estimated_cost_usd != null ? `$${usage.estimated_cost_usd.toFixed(4)}` : null,
  ].filter(Boolean).join(' · ');
  return (
    <View style={styles.reply}>
      {streaming?.status ? (
        <View style={styles.statusRow}>
          <ActivityIndicator size="small" color={c.textMuted} />
          <Text style={[styles.status, { color: c.textMuted }]}>{streaming.status}</Text>
        </View>
      ) : null}
      {msg.content ? (
        <Markdown text={msg.content} color={c.textPrimary} width={hasTable(msg.content) ? contentW : undefined} />
      ) : null}
      {!streaming ? (
        <View style={styles.footer}>
          <Pressable onPress={() => onSelect(toPlainText(msg.content))} hitSlop={8} style={styles.selectBtn} accessibilityLabel="Select text">
            <Ionicons name="copy-outline" size={15} color={c.textMuted} />
            <Text style={[styles.meta, { color: c.textMuted }]}>Select</Text>
          </Pressable>
          {meta ? <Text style={[styles.meta, { color: c.textMuted, flexShrink: 1 }]}>{meta}</Text> : null}
        </View>
      ) : null}
    </View>
  );
}

const styles = StyleSheet.create({
  userRow: { flexDirection: 'row', justifyContent: 'flex-end', marginTop: spacing.md, marginBottom: spacing.lg },
  userBubble: { maxWidth: '80%', borderRadius: 20, paddingHorizontal: spacing.md + 2, paddingVertical: spacing.sm + 2 },
  userText: { fontSize: chatType.size, lineHeight: chatType.lineHeight - 2 },
  reply: { marginBottom: spacing.lg },
  statusRow: { flexDirection: 'row', alignItems: 'center', gap: spacing.sm, paddingVertical: 2 },
  status: { fontSize: fontSize.sm, fontStyle: 'italic' },
  footer: { flexDirection: 'row', alignItems: 'center', gap: spacing.md, marginTop: spacing.xs },
  meta: { fontSize: fontSize.xs - 1, letterSpacing: 0.3 },
  selectBtn: { flexDirection: 'row', alignItems: 'center', gap: 4, paddingVertical: 2 },
});
