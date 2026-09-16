/**
 * Inline AI chat at the bottom of a company page.
 *
 *   ASK AI ABOUT QDEL                       [Flash | Pro]
 *   ┌ messages (this ticker's conversation) ──────────┐
 *   └──────────────────────────────────────────────────┘
 *   [ #QDEL  what does the debt look like?        ➤ ]
 *
 * The composer is pre-filled with "#TICKER " so the server attaches the
 * company's data to every question. The box opens BLANK every time the
 * page is entered; each thread lives on the server (it also shows up in
 * the AI tab's drawer) and the clock button brings past conversations
 * back (this ticker's first). Model defaults to Flash.
 */
import { Ionicons } from '@expo/vector-icons';
import AsyncStorage from '@react-native-async-storage/async-storage';
import { useRouter } from 'expo-router';
import { useEffect, useState } from 'react';
import { ActivityIndicator, FlatList, Modal, Pressable, StyleSheet, Text, TextInput, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { aiApi, type ChatMessage, type ConversationSummary, type ModelKey, type StreamEvent } from '@/api/ai';
import { useReplyStream } from '@/hooks/useReplyStream';
import { formatDate } from '@/utils/format';
import { Markdown, hasTable, toPlainText } from '@/components/Markdown';
import { SelectTextSheet } from '@/components/SelectTextSheet';
import { useColors, fontSize, radii, spacing } from '@/theme/colors';

const LAST_CONV_KEY = 'ai_last_conversation_v1';   // shared with the AI tab

type Streaming = { status: string | null; text: string };

export function TickerChat({ ticker }: { ticker: string }) {
  const c = useColors();
  const router = useRouter();
  const prefix = `#${ticker} `;
  const [model, setModel] = useState<ModelKey>('flash');
  const [convId, setConvId] = useState<string | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState(prefix);
  const [streaming, setStreaming] = useState<Streaming | null>(null);
  const [error, setError] = useState<string | null>(null);
  const reply = useReplyStream();
  const insets = useSafeAreaInsets();
  const [historyOpen, setHistoryOpen] = useState(false);
  const [selectText, setSelectText] = useState<string | null>(null);   // message open in the select/copy sheet
  const [chatW, setChatW] = useState(0);
  // Inner width of a full-width bubble: the wrap's padding, then 94%, then the bubble's own padding.
  const contentW = chatW ? Math.floor((chatW - 2 * spacing.lg) * 0.94) - 2 * spacing.md : undefined;
  const [history, setHistory] = useState<ConversationSummary[] | null>(null);

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
      .catch((e) => { setError(String((e as Error).message ?? e)); setHistoryOpen(false); });
  };

  const loadConversation = async (id: string) => {
    setHistoryOpen(false);
    reply.stop();
    setStreaming(null);
    try {
      const conv = await aiApi.getConversation(id);
      setConvId(conv.id);
      setMessages(conv.messages);
      AsyncStorage.setItem(LAST_CONV_KEY, conv.id).catch(() => {});
      if (conv.pending) {   // a reply is still being written server-side — watch it
        setStreaming({ status: 'Thinking…', text: '' });
        reply.follow({ convId: conv.id, ...streamHandlers });
      }
    } catch (e) {
      setError(String((e as Error).message ?? e));
    }
  };

  const newThread = () => {
    setHistoryOpen(false);
    reply.stop();
    setStreaming(null);
    setConvId(null);
    setMessages([]);
    setInput(prefix);
  };

  // A fresh, blank box whenever the page (or the ticker) changes; earlier
  // threads stay reachable through the history button.
  useEffect(() => {
    reply.stop();
    setConvId(null); setMessages([]); setInput(prefix); setStreaming(null); setError(null);
  }, [ticker, prefix, reply]);

  // Events of a streamed reply, whether freshly sent or re-attached.
  const streamHandlers = {
    onEvent: (ev: StreamEvent) => {
      switch (ev.type) {
        case 'companies': setStreaming((s) => s && { ...s, status: `Reading ${ev.tickers.join(', ')}…` }); break;
        case 'status': setStreaming((s) => s && { ...s, status: ev.text }); break;
        case 'delta': setStreaming((s) => s && { status: null, text: s.text + ev.text }); break;
        case 'done': setMessages((m) => [...m, ev.message]); setStreaming(null); break;
        case 'error': setError(ev.text); setStreaming(null); break;
      }
    },
    // The server no longer has the live reply buffered: the stored
    // conversation holds it in full if it finished.
    onGone: (cid: string) => {
      aiApi.getConversation(cid)
        .then((conv) => setMessages(conv.messages))
        .catch((e) => setError(String((e as Error).message ?? e)))
        .finally(() => setStreaming(null));
    },
  };

  const send = async () => {
    const text = input.trim();
    if (!text || text === prefix.trim() || streaming) return;
    setError(null);
    setInput(prefix);
    let id = convId;
    if (!id) {
      try {
        const conv = await aiApi.createConversation(model);
        id = conv.id;
        setConvId(id);
      } catch (e) {
        setError(String((e as Error).message ?? e));
        setInput(text);
        return;
      }
    }
    AsyncStorage.setItem(LAST_CONV_KEY, id).catch(() => {});
    setMessages((m) => [...m, { role: 'user', content: text }]);
    setStreaming({ status: 'Thinking…', text: '' });
    reply.send({ convId: id, text, model, ...streamHandlers });
  };

  const stop = () => {
    reply.stop();   // the server still finishes and stores the full reply
    const partial = streaming?.text ?? '';
    setStreaming(null);
    if (partial) setMessages((m) => [...m, { role: 'assistant', content: partial + '\n\n_(stopped)_' }]);
  };

  const canSend = input.trim().length > prefix.trim().length && !streaming;

  return (
    <View style={[styles.wrap, { borderTopColor: c.border }]} onLayout={(e) => setChatW(e.nativeEvent.layout.width)}>
      <View style={styles.head}>
        <Text style={[styles.eyebrow, { color: c.brand, borderBottomColor: c.brand }]}>ASK AI ABOUT {ticker}</Text>
        <Pressable onPress={openHistory} hitSlop={10} style={styles.iconBtn} accessibilityLabel="Past conversations">
          <Ionicons name="time-outline" size={20} color={c.textMuted} />
        </Pressable>
        <View style={[styles.segment, { borderColor: c.border, backgroundColor: c.surface }]}>
          {(['flash', 'pro'] as ModelKey[]).map((m) => (
            <Pressable key={m} onPress={() => setModel(m)} style={[styles.segmentBtn, model === m && { backgroundColor: c.brand }]}>
              <Text style={[styles.segmentLabel, { color: model === m ? '#fff' : c.textMuted }]}>{m === 'flash' ? 'Flash' : 'Pro'}</Text>
            </Pressable>
          ))}
        </View>
      </View>

      {messages.length === 0 && !streaming ? (
        <Text style={[styles.hint, { color: c.textMuted }]}>
          Ask anything about this company — the reply uses its SEC statements, ratios and filings.
        </Text>
      ) : null}

      {messages.map((m, i) => {
        const table = m.role === 'assistant' && hasTable(m.content);
        const bubbleStyle = [styles.bubble, m.role === 'user'
          ? { backgroundColor: c.brand, borderBottomRightRadius: 4 }
          : { backgroundColor: c.surface, borderColor: c.border, borderWidth: StyleSheet.hairlineWidth, borderBottomLeftRadius: 4 },
          table && styles.bubbleWide];
        const inner = (
          <>
            {m.role === 'user'
              ? <Text style={[styles.userText, { color: '#fff' }]}>{m.content}</Text>
              : <Markdown text={m.content} color={c.textPrimary} width={table ? contentW : undefined} />}
            {m.role === 'assistant' ? (
              <View style={styles.footer}>
                <Text style={[styles.meta, { color: c.textMuted }]}>
                  {m.usage?.estimated_cost_usd != null
                    ? `${m.model?.includes('pro') ? 'Pro' : 'Flash'} · $${m.usage.estimated_cost_usd.toFixed(4)}`
                    : ''}
                </Text>
                <Pressable onPress={() => setSelectText(toPlainText(m.content))} hitSlop={8} style={styles.selectBtn} accessibilityLabel="Select text">
                  <Ionicons name="copy-outline" size={14} color={c.textMuted} />
                  <Text style={[styles.meta, { color: c.textMuted }]}>Select</Text>
                </Pressable>
              </View>
            ) : null}
          </>
        );
        return (
          <View key={i} style={[styles.row, m.role === 'user' && styles.rowUser]}>
            {/* Long-press opens the select/copy sheet. A bubble holding a table is a plain
                View so nothing sits between the table's horizontal ScrollView and the touch. */}
            {table
              ? <View style={bubbleStyle}>{inner}</View>
              : <Pressable onLongPress={() => setSelectText(m.role === 'user' ? m.content : toPlainText(m.content))} style={bubbleStyle}>{inner}</Pressable>}
          </View>
        );
      })}
      {streaming ? (
        <View style={styles.row}>
          <View style={[styles.bubble, { backgroundColor: c.surface, borderColor: c.border, borderWidth: StyleSheet.hairlineWidth, borderBottomLeftRadius: 4 },
            hasTable(streaming.text) && styles.bubbleWide]}>
            {streaming.status ? (
              <View style={styles.statusRow}>
                <ActivityIndicator size="small" color={c.textMuted} />
                <Text style={[styles.status, { color: c.textMuted }]}>{streaming.status}</Text>
              </View>
            ) : null}
            {streaming.text ? <Markdown text={streaming.text} color={c.textPrimary} width={hasTable(streaming.text) ? contentW : undefined} /> : null}
          </View>
        </View>
      ) : null}
      {error ? (
        <Pressable onPress={() => setError(null)} style={[styles.errorBar, { backgroundColor: c.statusErrorBg }]}>
          <Text style={[styles.errorText, { color: c.negative }]} numberOfLines={3}>{error}</Text>
        </Pressable>
      ) : null}

      <View style={styles.composer}>
        <TextInput
          value={input}
          onChangeText={(v) => setInput(v.startsWith(prefix) ? v : prefix + v.replace(/^#\w+\s*/, ''))}
          placeholder={`${prefix}your question…`}
          placeholderTextColor={c.textMuted}
          multiline
          editable={!streaming}
          style={[styles.input, { color: c.textPrimary, backgroundColor: c.surface, borderColor: c.border }]}
        />
        {streaming ? (
          <Pressable onPress={stop} style={[styles.sendBtn, { backgroundColor: c.negative }]} hitSlop={6}>
            <Ionicons name="stop" size={18} color="#fff" />
          </Pressable>
        ) : (
          <Pressable onPress={send} disabled={!canSend} style={[styles.sendBtn, { backgroundColor: canSend ? c.brand : c.border }]} hitSlop={6}>
            <Ionicons name="arrow-up" size={18} color="#fff" />
          </Pressable>
        )}
      </View>
      {convId ? (
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
            <Pressable onPress={newThread} hitSlop={8} style={[styles.newBtn, { borderColor: c.brand }]}>
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
                const active = item.id === convId;
                return (
                  <Pressable
                    onPress={() => loadConversation(item.id)}
                    style={({ pressed }) => [styles.convRow, { borderBottomColor: c.border, backgroundColor: pressed ? c.surface : active ? c.statusOkBg : 'transparent', borderLeftColor: active ? c.brand : 'transparent' }]}
                  >
                    <Text style={[styles.convTitle, { color: mine ? c.textPrimary : c.textMuted }]} numberOfLines={2}>{item.title}</Text>
                    <Text style={[styles.convMeta, { color: c.textMuted }]}>
                      {formatDate(item.updated_at)} · {item.message_count} msgs · {item.model?.includes('pro') ? 'Pro' : 'Flash'}{mine ? ` · #${ticker}` : ''}
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
  segment: { flexDirection: 'row', borderWidth: StyleSheet.hairlineWidth, borderRadius: radii.pill, padding: 2 },
  segmentBtn: { paddingHorizontal: 10, paddingVertical: 4, borderRadius: radii.pill },
  segmentLabel: { fontSize: fontSize.xs, fontWeight: '700' },
  hint: { fontSize: fontSize.sm, lineHeight: 20, marginBottom: spacing.sm },
  row: { flexDirection: 'row', marginBottom: spacing.sm },
  rowUser: { justifyContent: 'flex-end' },
  bubble: { maxWidth: '94%', borderRadius: 16, paddingHorizontal: spacing.md, paddingVertical: spacing.sm + 2 },
  bubbleWide: { width: '94%' },
  userText: { fontSize: fontSize.md, lineHeight: 22 },
  statusRow: { flexDirection: 'row', alignItems: 'center', gap: spacing.sm, paddingVertical: 2 },
  status: { fontSize: fontSize.sm, fontStyle: 'italic' },
  footer: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', marginTop: spacing.xs },
  meta: { fontSize: fontSize.xs - 1, letterSpacing: 0.3 },
  selectBtn: { flexDirection: 'row', alignItems: 'center', gap: 3, paddingLeft: spacing.sm, paddingVertical: 2 },
  errorBar: { padding: spacing.sm, borderRadius: radii.md, marginBottom: spacing.sm },
  errorText: { fontSize: fontSize.sm },
  composer: { flexDirection: 'row', alignItems: 'flex-end', gap: spacing.sm, marginTop: spacing.xs },
  input: { flex: 1, minHeight: 40, maxHeight: 140, borderWidth: StyleSheet.hairlineWidth, borderRadius: 20, paddingHorizontal: spacing.md, paddingTop: 10, paddingBottom: 10, fontSize: fontSize.md },
  sendBtn: { width: 36, height: 36, borderRadius: 18, alignItems: 'center', justifyContent: 'center', marginBottom: 2 },
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
