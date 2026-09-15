/**
 * Inline AI chat at the bottom of a company page.
 *
 *   ASK AI ABOUT QDEL                       [Flash | Pro]
 *   ┌ messages (this ticker's conversation) ──────────┐
 *   └──────────────────────────────────────────────────┘
 *   [ #QDEL  what does the debt look like?        ➤ ]
 *
 * The composer is pre-filled with "#TICKER " so the server attaches the
 * company's data to every question. One conversation per ticker, kept on
 * the server (it also shows up in the AI tab's drawer) and remembered
 * per device so the thread resumes next time the page opens. Model
 * defaults to Pro here — company deep-dives deserve the better model.
 */
import { Ionicons } from '@expo/vector-icons';
import AsyncStorage from '@react-native-async-storage/async-storage';
import { useRouter } from 'expo-router';
import { useEffect, useRef, useState } from 'react';
import { ActivityIndicator, Pressable, StyleSheet, Text, TextInput, View } from 'react-native';

import { aiApi, streamMessage, type ChatMessage, type ModelKey } from '@/api/ai';
import { Markdown } from '@/components/Markdown';
import { useColors, fontSize, radii, spacing } from '@/theme/colors';

const CONV_KEY = (t: string) => `ai_conv_ticker_${t}`;
const LAST_CONV_KEY = 'ai_last_conversation_v1';   // shared with the AI tab

type Streaming = { status: string | null; text: string };

export function TickerChat({ ticker }: { ticker: string }) {
  const c = useColors();
  const router = useRouter();
  const prefix = `#${ticker} `;
  const [model, setModel] = useState<ModelKey>('pro');
  const [convId, setConvId] = useState<string | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState(prefix);
  const [streaming, setStreaming] = useState<Streaming | null>(null);
  const [error, setError] = useState<string | null>(null);
  const abortRef = useRef<(() => void) | null>(null);

  // Resume this ticker's thread, if one exists on this device.
  useEffect(() => {
    let cancelled = false;
    setConvId(null); setMessages([]); setInput(prefix); setStreaming(null); setError(null);
    AsyncStorage.getItem(CONV_KEY(ticker))
      .then(async (id) => {
        if (!id || cancelled) return;
        try {
          const conv = await aiApi.getConversation(id);
          if (!cancelled) { setConvId(conv.id); setMessages(conv.messages); }
        } catch {
          AsyncStorage.removeItem(CONV_KEY(ticker)).catch(() => {});
        }
      })
      .catch(() => {});
    return () => { cancelled = true; };
  }, [ticker, prefix]);

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
        AsyncStorage.setItem(CONV_KEY(ticker), id).catch(() => {});
      } catch (e) {
        setError(String((e as Error).message ?? e));
        setInput(text);
        return;
      }
    }
    AsyncStorage.setItem(LAST_CONV_KEY, id).catch(() => {});
    setMessages((m) => [...m, { role: 'user', content: text }]);
    setStreaming({ status: 'Thinking…', text: '' });
    const { promise, abort } = streamMessage(id, text, model, (ev) => {
      switch (ev.type) {
        case 'companies': setStreaming((s) => s && { ...s, status: `Reading ${ev.tickers.join(', ')}…` }); break;
        case 'status': setStreaming((s) => s && { ...s, status: ev.text }); break;
        case 'delta': setStreaming((s) => s && { status: null, text: s.text + ev.text }); break;
        case 'done': setMessages((m) => [...m, ev.message]); setStreaming(null); break;
        case 'error': setError(ev.text); setStreaming(null); break;
      }
    });
    abortRef.current = abort;
    try { await promise; } catch (e) { setError(String((e as Error).message ?? e)); }
    finally { abortRef.current = null; setStreaming((s) => (s ? null : s)); }
  };

  const stop = () => {
    abortRef.current?.();
    const partial = streaming?.text ?? '';
    setStreaming(null);
    if (partial) setMessages((m) => [...m, { role: 'assistant', content: partial + '\n\n_(stopped)_' }]);
  };

  const canSend = input.trim().length > prefix.trim().length && !streaming;

  return (
    <View style={[styles.wrap, { borderTopColor: c.border }]}>
      <View style={styles.head}>
        <Text style={[styles.eyebrow, { color: c.brand, borderBottomColor: c.brand }]}>ASK AI ABOUT {ticker}</Text>
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

      {messages.map((m, i) => (
        <View key={i} style={[styles.row, m.role === 'user' && styles.rowUser]}>
          <View style={[styles.bubble, m.role === 'user'
            ? { backgroundColor: c.brand, borderBottomRightRadius: 4 }
            : { backgroundColor: c.surface, borderColor: c.border, borderWidth: StyleSheet.hairlineWidth, borderBottomLeftRadius: 4 }]}>
            {m.role === 'user'
              ? <Text style={[styles.userText, { color: '#fff' }]}>{m.content}</Text>
              : <Markdown text={m.content} color={c.textPrimary} />}
            {m.role === 'assistant' && m.usage?.estimated_cost_usd != null ? (
              <Text style={[styles.meta, { color: c.textMuted }]}>
                {m.model?.includes('pro') ? 'Pro' : 'Flash'} · ${m.usage.estimated_cost_usd.toFixed(4)}
              </Text>
            ) : null}
          </View>
        </View>
      ))}
      {streaming ? (
        <View style={styles.row}>
          <View style={[styles.bubble, { backgroundColor: c.surface, borderColor: c.border, borderWidth: StyleSheet.hairlineWidth, borderBottomLeftRadius: 4 }]}>
            {streaming.status ? (
              <View style={styles.statusRow}>
                <ActivityIndicator size="small" color={c.textMuted} />
                <Text style={[styles.status, { color: c.textMuted }]}>{streaming.status}</Text>
              </View>
            ) : null}
            {streaming.text ? <Markdown text={streaming.text} color={c.textPrimary} /> : null}
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
    </View>
  );
}

const styles = StyleSheet.create({
  wrap: { paddingHorizontal: spacing.lg, paddingTop: spacing.lg, paddingBottom: spacing.sm, borderTopWidth: StyleSheet.hairlineWidth, marginTop: spacing.md },
  head: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', marginBottom: spacing.sm },
  eyebrow: { fontSize: fontSize.xs, fontWeight: '700', letterSpacing: 1.5, borderBottomWidth: 2, paddingBottom: 4 },
  segment: { flexDirection: 'row', borderWidth: StyleSheet.hairlineWidth, borderRadius: radii.pill, padding: 2 },
  segmentBtn: { paddingHorizontal: 10, paddingVertical: 4, borderRadius: radii.pill },
  segmentLabel: { fontSize: fontSize.xs, fontWeight: '700' },
  hint: { fontSize: fontSize.sm, lineHeight: 20, marginBottom: spacing.sm },
  row: { flexDirection: 'row', marginBottom: spacing.sm },
  rowUser: { justifyContent: 'flex-end' },
  bubble: { maxWidth: '94%', borderRadius: 16, paddingHorizontal: spacing.md, paddingVertical: spacing.sm + 2 },
  userText: { fontSize: fontSize.md, lineHeight: 22 },
  statusRow: { flexDirection: 'row', alignItems: 'center', gap: spacing.sm, paddingVertical: 2 },
  status: { fontSize: fontSize.sm, fontStyle: 'italic' },
  meta: { fontSize: fontSize.xs - 1, marginTop: spacing.xs, letterSpacing: 0.3 },
  errorBar: { padding: spacing.sm, borderRadius: radii.md, marginBottom: spacing.sm },
  errorText: { fontSize: fontSize.sm },
  composer: { flexDirection: 'row', alignItems: 'flex-end', gap: spacing.sm, marginTop: spacing.xs },
  input: { flex: 1, minHeight: 40, maxHeight: 140, borderWidth: StyleSheet.hairlineWidth, borderRadius: 20, paddingHorizontal: spacing.md, paddingTop: 10, paddingBottom: 10, fontSize: fontSize.md },
  sendBtn: { width: 36, height: 36, borderRadius: 18, alignItems: 'center', justifyContent: 'center', marginBottom: 2 },
  openLink: { alignSelf: 'flex-end', paddingVertical: spacing.sm },
  openText: { fontSize: fontSize.xs, fontWeight: '600', letterSpacing: 0.5 },
});
