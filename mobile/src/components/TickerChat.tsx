/**
 * Inline AI chat at the bottom of a company page.
 *
 *   ASK AI ABOUT QDEL                       [Flash | Pro]
 *   …messages (this ticker's conversation)…
 *   [ #QDEL  what does the debt look like?        ➤ ]
 *
 * The composer is pre-filled with "#TICKER " so the server attaches the
 * company's data to every question. The box opens BLANK every time the
 * page is entered; each thread lives on the server (it also shows up in
 * the AI tab's drawer) and the clock button brings past conversations
 * back (this ticker's first). Conversation state and streaming come from
 * useConversation, shared with the AI tab.
 */
import { Ionicons } from '@expo/vector-icons';
import { useRouter } from 'expo-router';
import { useEffect, useState } from 'react';
import { ActivityIndicator, FlatList, Modal, Pressable, StyleSheet, Text, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { aiApi, type ConversationSummary } from '@/api/ai';
import { Composer } from '@/components/chat/Composer';
import { MessageRow } from '@/components/chat/MessageRow';
import { ModelToggle } from '@/components/chat/ModelToggle';
import { SelectTextSheet } from '@/components/SelectTextSheet';
import { useConversation } from '@/hooks/useConversation';
import { useModelPref } from '@/hooks/useModelPref';
import { useColors, fontSize, radii, spacing } from '@/theme/colors';
import { formatDate, modelLabel } from '@/utils/format';

export function TickerChat({ ticker, onActiveChange }: { ticker: string; onActiveChange?: (active: boolean) => void }) {
  const c = useColors();
  const router = useRouter();
  const insets = useSafeAreaInsets();
  const prefix = `#${ticker} `;
  const [model, pickModel, modelOptions] = useModelPref();
  const chat = useConversation();
  const [input, setInput] = useState(prefix);
  const [historyOpen, setHistoryOpen] = useState(false);
  const [history, setHistory] = useState<ConversationSummary[] | null>(null);
  const [selectText, setSelectText] = useState<string | null>(null);   // message open in the select/copy sheet
  const [chatW, setChatW] = useState(0);
  const contentW = chatW ? chatW - 2 * spacing.lg : undefined;   // replies run the full width

  // Let the page know a conversation is on screen (it shows a jump-to-bottom button).
  const active = chat.messages.length > 0 || chat.streaming !== null;
  useEffect(() => { onActiveChange?.(active); }, [active, onActiveChange]);

  // A fresh, blank box whenever the page (or the ticker) changes; earlier
  // threads stay reachable through the history button.
  const { reset } = chat;
  useEffect(() => {
    reset();
    setInput(prefix);
  }, [ticker, prefix, reset]);

  const openHistory = () => {
    setHistoryOpen(true);
    setHistory(null);
    aiApi.listConversations()
      .then((list) => {
        const tag = `#${ticker}`.toLowerCase();
        const mine = list.filter((cv) => cv.title.toLowerCase().includes(tag));
        const rest = list.filter((cv) => !cv.title.toLowerCase().includes(tag));
        setHistory([...mine, ...rest]);
      })
      .catch((e) => { chat.setError(String((e as Error).message ?? e)); setHistoryOpen(false); });
  };

  const send = async () => {
    const text = input.trim();
    if (!text || text === prefix.trim()) return;
    setInput(prefix);
    if (!(await chat.send(text, model))) setInput(text);
  };

  const canSend = input.trim().length > prefix.trim().length;

  return (
    <View style={[styles.wrap, { borderTopColor: c.border }]} onLayout={(e) => setChatW(e.nativeEvent.layout.width)}>
      <View style={styles.head}>
        <Text style={[styles.eyebrow, { color: c.brand, borderBottomColor: c.brand }]}>ASK AI ABOUT {ticker}</Text>
        <Pressable onPress={openHistory} hitSlop={10} style={styles.iconBtn} accessibilityLabel="Past conversations">
          <Ionicons name="time-outline" size={20} color={c.textMuted} />
        </Pressable>
        <ModelToggle value={model} onChange={pickModel} options={modelOptions} />
      </View>

      {chat.messages.length === 0 && !chat.streaming ? (
        <Text style={[styles.hint, { color: c.textMuted }]}>
          Ask anything about this company — the reply uses its SEC statements, ratios and filings.
        </Text>
      ) : null}

      {chat.messages.map((m, i) => (
        <MessageRow key={i} msg={m} onSelect={setSelectText} contentW={contentW} showSources={false} />
      ))}
      {chat.streaming ? (
        <MessageRow
          msg={{ role: 'assistant', content: chat.streaming.text }}
          streaming={chat.streaming}
          onSelect={setSelectText}
          contentW={contentW}
        />
      ) : null}
      {chat.error ? (
        <Pressable onPress={() => chat.setError(null)} style={[styles.errorBar, { backgroundColor: c.statusErrorBg }]}>
          <Text style={[styles.errorText, { color: c.negative }]} numberOfLines={3}>{chat.error}</Text>
        </Pressable>
      ) : null}

      <Composer
        value={input}
        onChange={(v) => setInput(v.startsWith(prefix) ? v : prefix + v.replace(/^#\w+\s*/, ''))}
        placeholder={`${prefix}your question…`}
        streaming={chat.streaming !== null}
        canSend={canSend}
        onSend={send}
        onStop={chat.stop}
        style={styles.composer}
      />
      {chat.convId ? (
        <Pressable onPress={() => router.push('/ai')} hitSlop={6} style={styles.openLink}>
          <Text style={[styles.openText, { color: c.brand }]}>Continue in the AI tab →</Text>
        </Pressable>
      ) : null}

      <SelectTextSheet text={selectText} visible={selectText !== null} onClose={() => setSelectText(null)} />

      <Modal visible={historyOpen} animationType="slide" transparent onRequestClose={() => setHistoryOpen(false)}>
        <Pressable style={styles.backdrop} onPress={() => setHistoryOpen(false)} />
        <View style={[styles.sheet, { backgroundColor: c.background, paddingBottom: insets.bottom + spacing.md }]}>
          <View style={styles.sheetHead}>
            <Text style={[styles.sheetTitle, { color: c.textPrimary }]}>Conversations</Text>
            <Pressable onPress={() => { setHistoryOpen(false); chat.reset(); setInput(prefix); }} hitSlop={8} style={[styles.newBtn, { borderColor: c.brand }]}>
              <Ionicons name="add" size={16} color={c.brand} />
              <Text style={[styles.newText, { color: c.brand }]}>New thread</Text>
            </Pressable>
          </View>
          {history === null ? (
            <ActivityIndicator color={c.brand} style={{ paddingVertical: spacing.xl }} />
          ) : (
            <FlatList
              data={history}
              keyExtractor={(cv) => cv.id}
              style={{ maxHeight: 420 }}
              ListEmptyComponent={<Text style={[styles.hint, { color: c.textMuted, padding: spacing.lg }]}>No conversations yet.</Text>}
              renderItem={({ item }) => {
                const mine = item.title.toLowerCase().includes(`#${ticker}`.toLowerCase());
                const isActive = item.id === chat.convId;
                return (
                  <Pressable
                    onPress={() => { setHistoryOpen(false); chat.open(item.id); }}
                    style={({ pressed }) => [styles.convRow, { borderBottomColor: c.border, backgroundColor: pressed ? c.surface : isActive ? c.statusOkBg : 'transparent', borderLeftColor: isActive ? c.brand : 'transparent' }]}
                  >
                    <Text style={[styles.convTitle, { color: mine ? c.textPrimary : c.textMuted }]} numberOfLines={2}>{item.title}</Text>
                    <Text style={[styles.convMeta, { color: c.textMuted }]}>
                      {formatDate(item.updated_at)} · {item.message_count} msgs · {modelLabel(item.model)}{mine ? ` · #${ticker}` : ''}
                    </Text>
                  </Pressable>
                );
              }}
            />
          )}
        </View>
      </Modal>
    </View>
  );
}

const styles = StyleSheet.create({
  wrap: { paddingHorizontal: spacing.lg, paddingTop: spacing.lg, paddingBottom: spacing.sm, borderTopWidth: StyleSheet.hairlineWidth, marginTop: spacing.md },
  head: { flexDirection: 'row', alignItems: 'center', marginBottom: spacing.sm },
  eyebrow: { fontSize: fontSize.xs, fontWeight: '700', letterSpacing: 1.5, borderBottomWidth: 2, paddingBottom: 4 },
  hint: { fontSize: fontSize.sm, lineHeight: 20, marginBottom: spacing.sm },
  errorBar: { padding: spacing.sm, borderRadius: radii.md, marginBottom: spacing.sm },
  errorText: { fontSize: fontSize.sm },
  composer: { marginTop: spacing.xs },
  openLink: { alignSelf: 'flex-end', paddingVertical: spacing.sm },
  openText: { fontSize: fontSize.xs, fontWeight: '600', letterSpacing: 0.5 },
  iconBtn: { marginLeft: 'auto', marginRight: spacing.sm, padding: 2 },
  backdrop: { flex: 1, backgroundColor: 'rgba(0,0,0,0.35)' },
  sheet: { borderTopLeftRadius: radii.lg, borderTopRightRadius: radii.lg, paddingTop: spacing.md },
  sheetHead: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', paddingHorizontal: spacing.lg, paddingBottom: spacing.sm },
  sheetTitle: { fontSize: fontSize.lg, fontWeight: '700' },
  newBtn: { flexDirection: 'row', alignItems: 'center', gap: 4, borderWidth: 1, borderRadius: radii.pill, paddingHorizontal: 10, paddingVertical: 4 },
  newText: { fontSize: fontSize.xs, fontWeight: '700' },
  convRow: { paddingHorizontal: spacing.lg, paddingVertical: spacing.md, borderBottomWidth: StyleSheet.hairlineWidth, borderLeftWidth: 3 },
  convTitle: { fontSize: fontSize.md, fontWeight: '600' },
  convMeta: { fontSize: fontSize.xs, marginTop: 2 },
});
