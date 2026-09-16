/**
 * AI tab — a DeepSeek chat grounded in the archive's company data.
 *
 *   ┌ ☰  Title of chat            [Flash|Pro]  ＋ ┐   custom header
 *   │  …messages (inverted list, streaming)…      │
 *   │  ┌ status / delta bubble ─────────────────┐ │
 *   └ [ Ask about any company…            ➤ ] ────┘   composer
 *
 * The ☰ slides in a left panel with past conversations (server-side, so
 * they follow the user across devices). Mention a ticker or company
 * name and the server attaches its data; the model can also look
 * companies up itself. Model (flash / pro) is chosen per message.
 */
import { Ionicons } from '@expo/vector-icons';
import AsyncStorage from '@react-native-async-storage/async-storage';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  ActivityIndicator,
  Alert,
  Animated,
  FlatList,
  KeyboardAvoidingView,
  Platform,
  Pressable,
  StyleSheet,
  Text,
  TextInput,
  View,
  useWindowDimensions,
} from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import {
  aiApi,
  type ChatMessage,
  type Conversation,
  type ConversationSummary,
  type ModelKey,
  type StreamEvent,
} from '@/api/ai';
import { Markdown, hasTable, toPlainText } from '@/components/Markdown';
import { SelectTextSheet } from '@/components/SelectTextSheet';
import { useReplyStream } from '@/hooks/useReplyStream';
import { useColors, fontSize, radii, spacing } from '@/theme/colors';
import { formatDate } from '@/utils/format';

const MODEL_KEY = 'ai_model_v1';
const LAST_CONV_KEY = 'ai_last_conversation_v1';

type Streaming = { status: string | null; text: string; companies: string[] };
type Row = ChatMessage & { _streaming?: boolean };

export default function AiScreen() {
  const c = useColors();
  const insets = useSafeAreaInsets();
  const { width } = useWindowDimensions();

  const [model, setModel] = useState<ModelKey>('flash');
  const [conversations, setConversations] = useState<ConversationSummary[] | null>(null);
  const [current, setCurrent] = useState<Conversation | null>(null);
  const [loadingConv, setLoadingConv] = useState(false);
  const [input, setInput] = useState('');
  const [streaming, setStreaming] = useState<Streaming | null>(null);
  const [error, setError] = useState<string | null>(null);
  const reply = useReplyStream();

  // ---- persistence of small prefs ----
  useEffect(() => {
    AsyncStorage.getItem(MODEL_KEY).then((m) => {
      if (m === 'flash' || m === 'pro') setModel(m);
    }).catch(() => {});
  }, []);
  const pickModel = (m: ModelKey) => {
    setModel(m);
    AsyncStorage.setItem(MODEL_KEY, m).catch(() => {});
  };

  // ---- conversations ----
  const refreshList = useCallback(async () => {
    try {
      setConversations(await aiApi.listConversations());
      setError(null);
    } catch (e) {
      setError(String((e as Error).message ?? e));
    }
  }, []);

  // Events of a streamed reply, whether freshly sent or re-attached.
  const streamHandlers = (convId: string) => ({
    onEvent: (ev: StreamEvent) => {
      switch (ev.type) {
        case 'companies':
          setStreaming((s) => s && { ...s, companies: ev.tickers, status: `Reading ${ev.tickers.join(', ')}…` });
          break;
        case 'status':
          setStreaming((s) => s && { ...s, status: ev.text });
          break;
        case 'delta':
          setStreaming((s) => s && { ...s, status: null, text: s.text + ev.text });
          break;
        case 'done':
          setCurrent((prev) =>
            prev && prev.id === convId
              ? {
                  ...prev,
                  title: ev.conversation.title,
                  model: ev.conversation.model,
                  messages: [...prev.messages, ev.message],
                }
              : prev,
          );
          setStreaming(null);
          refreshList();
          break;
        case 'error':
          setError(ev.text);
          setStreaming(null);
          break;
      }
    },
    // The server no longer has the live reply buffered: the stored
    // conversation holds it in full if it finished.
    onGone: (cid: string) => {
      aiApi.getConversation(cid)
        .then((conv) => { setCurrent((prev) => (prev && prev.id === cid ? conv : prev)); refreshList(); })
        .catch((e) => setError(String((e as Error).message ?? e)))
        .finally(() => setStreaming(null));
    },
  });

  const openConversation = useCallback(async (id: string) => {
    setLoadingConv(true);
    try {
      const conv = await aiApi.getConversation(id);
      reply.stop();
      setStreaming(null);
      setCurrent(conv);
      AsyncStorage.setItem(LAST_CONV_KEY, id).catch(() => {});
      setError(null);
      if (conv.pending) {   // a reply is still being written server-side — watch it
        setStreaming({ status: 'Thinking…', text: '', companies: [] });
        reply.follow({ convId: conv.id, ...streamHandlers(conv.id) });
      }
    } catch (e) {
      setError(String((e as Error).message ?? e));
    } finally {
      setLoadingConv(false);
    }
  }, []);

  useEffect(() => {
    (async () => {
      await refreshList();
      try {
        const last = await AsyncStorage.getItem(LAST_CONV_KEY);
        if (last) await openConversation(last);
      } catch {
        // ignore
      }
    })();
  }, [refreshList, openConversation]);

  const newChat = () => {
    reply.stop();
    setStreaming(null);
    setCurrent(null);
    AsyncStorage.removeItem(LAST_CONV_KEY).catch(() => {});
  };

  const deleteConversation = (conv: ConversationSummary) =>
    Alert.alert(`Delete "${conv.title}"?`, undefined, [
      { text: 'Cancel', style: 'cancel' },
      {
        text: 'Delete',
        style: 'destructive',
        onPress: async () => {
          try {
            await aiApi.deleteConversation(conv.id);
            if (current?.id === conv.id) newChat();
            await refreshList();
          } catch (e) {
            setError(String((e as Error).message ?? e));
          }
        },
      },
    ]);

  // ---- sending ----
  const send = async () => {
    const text = input.trim();
    if (!text || streaming) return;
    setInput('');
    setError(null);

    let conv = current;
    if (!conv) {
      try {
        conv = await aiApi.createConversation(model);
        setCurrent(conv);
        AsyncStorage.setItem(LAST_CONV_KEY, conv.id).catch(() => {});
      } catch (e) {
        setError(String((e as Error).message ?? e));
        setInput(text);
        return;
      }
    }
    const convId = conv.id;

    // Optimistic user turn + an empty streaming bubble.
    setCurrent((prev) =>
      prev && prev.id === convId
        ? { ...prev, messages: [...prev.messages, { role: 'user', content: text }] }
        : prev,
    );
    setStreaming({ status: 'Thinking…', text: '', companies: [] });
    reply.send({ convId, text, model, ...streamHandlers(convId) });
  };

  const stop = () => {
    reply.stop();
    // Keep what arrived so far as a local turn. The server finishes the
    // generation on its own and stores the full reply — reopening the
    // chat from the drawer shows that version.
    const partial = streaming?.text ?? '';
    setStreaming(null);
    if (partial) {
      setCurrent((prev) =>
        prev ? { ...prev, messages: [...prev.messages, { role: 'assistant', content: partial + '\n\n_(stopped)_' }] } : prev,
      );
    }
  };

  // ---- drawer ----
  const drawerWidth = Math.min(320, width * 0.82);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [selectText, setSelectText] = useState<string | null>(null);   // message open in the select/copy sheet
  const drawerX = useRef(new Animated.Value(-drawerWidth)).current;
  const backdrop = useRef(new Animated.Value(0)).current;
  const toggleDrawer = (open: boolean) => {
    if (open) {
      setDrawerOpen(true);
      refreshList();
    }
    Animated.parallel([
      Animated.timing(drawerX, { toValue: open ? 0 : -drawerWidth, duration: 220, useNativeDriver: true }),
      Animated.timing(backdrop, { toValue: open ? 1 : 0, duration: 220, useNativeDriver: true }),
    ]).start(() => {
      if (!open) setDrawerOpen(false);
    });
  };

  // ---- list data (inverted) ----
  const data = useMemo(() => {
    const msgs = current?.messages ?? [];
    const rows: Row[] = [...msgs];
    if (streaming) rows.push({ role: 'assistant', content: streaming.text, _streaming: true });
    return rows.reverse();
  }, [current, streaming]);

  const title = current?.title ?? 'New chat';

  return (
    <KeyboardAvoidingView
      style={{ flex: 1, backgroundColor: c.background }}
      behavior={Platform.OS === 'ios' ? 'padding' : undefined}
    >
      {/* Header */}
      <View style={[styles.header, { paddingTop: insets.top + spacing.sm, borderBottomColor: c.border, backgroundColor: c.background }]}>
        <Pressable onPress={() => toggleDrawer(true)} hitSlop={10} style={styles.iconBtn}>
          <Ionicons name="menu" size={24} color={c.textPrimary} />
        </Pressable>
        <Text style={[styles.title, { color: c.textPrimary }]} numberOfLines={1}>{title}</Text>
        <View style={[styles.segment, { borderColor: c.border, backgroundColor: c.surface }]}>
          {(['flash', 'pro'] as ModelKey[]).map((m) => (
            <Pressable
              key={m}
              onPress={() => pickModel(m)}
              style={[styles.segmentBtn, model === m && { backgroundColor: c.brand }]}
            >
              <Text style={[styles.segmentLabel, { color: model === m ? '#fff' : c.textMuted }]}>
                {m === 'flash' ? 'Flash' : 'Pro'}
              </Text>
            </Pressable>
          ))}
        </View>
        <Pressable onPress={newChat} hitSlop={10} style={styles.iconBtn}>
          <Ionicons name="create-outline" size={24} color={c.textPrimary} />
        </Pressable>
      </View>

      {/* Messages */}
      {loadingConv && !current ? (
        <View style={styles.center}><ActivityIndicator color={c.brand} /></View>
      ) : (
        <FlatList
          inverted
          data={data}
          keyExtractor={(_, i) => String(i)}
          contentContainerStyle={styles.messages}
          keyboardDismissMode="interactive"
          keyboardShouldPersistTaps="handled"
          renderItem={({ item }) => (
            <Bubble
              msg={item}
              streaming={item._streaming ? streaming : null}
              onSelect={setSelectText}
            />
          )}
          ListEmptyComponent={
            <View style={[styles.empty, { transform: [{ scaleY: -1 }] }]}>
              <Ionicons name="sparkles-outline" size={28} color={c.brand} />
              <Text style={[styles.emptyTitle, { color: c.textPrimary }]}>Ask about any company</Text>
              <Text style={[styles.emptyHint, { color: c.textMuted }]}>
                Mention a ticker or name — e.g. “Is QDEL’s debt manageable?” or “Compare Inogen and
                Bioventus on FCF” — and the reply uses the archive’s SEC data, ratios and filings.
              </Text>
            </View>
          }
        />
      )}

      {error ? (
        <Pressable onPress={() => setError(null)} style={[styles.errorBar, { backgroundColor: c.statusErrorBg }]}>
          <Text style={[styles.errorText, { color: c.negative }]} numberOfLines={3}>{error}</Text>
        </Pressable>
      ) : null}

      <SelectTextSheet text={selectText} visible={selectText !== null} onClose={() => setSelectText(null)} />

      {/* Composer */}
      <View style={[styles.composer, { borderTopColor: c.border, backgroundColor: c.background, paddingBottom: spacing.sm }]}>
        <TextInput
          value={input}
          onChangeText={setInput}
          placeholder={`Ask ${model === 'pro' ? 'Pro' : 'Flash'} about any company…`}
          placeholderTextColor={c.textMuted}
          multiline
          style={[styles.input, { color: c.textPrimary, backgroundColor: c.surface, borderColor: c.border }]}
          editable={!streaming}
        />
        {streaming ? (
          <Pressable onPress={stop} style={[styles.sendBtn, { backgroundColor: c.negative }]} hitSlop={6}>
            <Ionicons name="stop" size={18} color="#fff" />
          </Pressable>
        ) : (
          <Pressable
            onPress={send}
            disabled={!input.trim()}
            style={[styles.sendBtn, { backgroundColor: input.trim() ? c.brand : c.border }]}
            hitSlop={6}
          >
            <Ionicons name="arrow-up" size={18} color="#fff" />
          </Pressable>
        )}
      </View>

      {/* Drawer */}
      {drawerOpen ? (
        <>
          <Animated.View style={[StyleSheet.absoluteFill, { backgroundColor: '#000', opacity: backdrop.interpolate({ inputRange: [0, 1], outputRange: [0, 0.35] }) }]}>
            <Pressable style={{ flex: 1 }} onPress={() => toggleDrawer(false)} />
          </Animated.View>
          <Animated.View
            style={[
              styles.drawer,
              { width: drawerWidth, paddingTop: insets.top + spacing.md, backgroundColor: c.surface, borderRightColor: c.border, transform: [{ translateX: drawerX }] },
            ]}
          >
            <View style={styles.drawerHeader}>
              <Text style={[styles.drawerTitle, { color: c.textPrimary }]}>Conversations</Text>
              <Pressable onPress={() => { toggleDrawer(false); newChat(); }} hitSlop={8}>
                <Ionicons name="add" size={24} color={c.brand} />
              </Pressable>
            </View>
            <FlatList
              data={conversations ?? []}
              keyExtractor={(cv) => cv.id}
              ListEmptyComponent={
                <Text style={[styles.emptyHint, { color: c.textMuted, paddingHorizontal: spacing.lg }]}>
                  {conversations ? 'No conversations yet.' : 'Loading…'}
                </Text>
              }
              renderItem={({ item }) => {
                const active = item.id === current?.id;
                return (
                  <Pressable
                    onPress={() => { toggleDrawer(false); openConversation(item.id); }}
                    onLongPress={() => deleteConversation(item)}
                    style={({ pressed }) => [
                      styles.convRow,
                      { backgroundColor: pressed ? c.border : active ? c.statusOkBg : 'transparent', borderLeftColor: active ? c.brand : 'transparent' },
                    ]}
                  >
                    <Text style={[styles.convTitle, { color: active ? c.brand : c.textPrimary }]} numberOfLines={2}>
                      {item.title}
                    </Text>
                    <Text style={[styles.convMeta, { color: c.textMuted }]}>
                      {formatDate(item.updated_at)} · {item.message_count} msgs · {item.model?.includes('pro') ? 'Pro' : 'Flash'}
                    </Text>
                  </Pressable>
                );
              }}
            />
            <Text style={[styles.drawerFoot, { color: c.textMuted }]}>Long-press a chat to delete it.</Text>
          </Animated.View>
        </>
      ) : null}
    </KeyboardAvoidingView>
  );
}

function Bubble({ msg, streaming, onSelect }: { msg: ChatMessage; streaming: Streaming | null; onSelect: (text: string) => void }) {
  const c = useColors();
  const isUser = msg.role === 'user';
  const usage = msg.usage;
  return (
    <View style={[styles.bubbleRow, isUser && styles.bubbleRowUser]}>
      {/* Long-press (or the icon) opens the message in a sheet where any part can be selected and copied. */}
      <Pressable
        onLongPress={() => onSelect(isUser ? msg.content : toPlainText(msg.content))}
        style={[
          styles.bubble,
          isUser
            ? { backgroundColor: c.brand, borderBottomRightRadius: 4 }
            : { backgroundColor: c.surface, borderColor: c.border, borderWidth: StyleSheet.hairlineWidth, borderBottomLeftRadius: 4 },
          !isUser && hasTable(msg.content) && styles.bubbleWide,
        ]}
      >
        {isUser ? (
          <Text style={[styles.userText, { color: '#fff' }]}>{msg.content}</Text>
        ) : (
          <>
            {streaming?.status ? (
              <View style={styles.statusRow}>
                <ActivityIndicator size="small" color={c.textMuted} />
                <Text style={[styles.status, { color: c.textMuted }]}>{streaming.status}</Text>
              </View>
            ) : null}
            {msg.content ? <Markdown text={msg.content} color={c.textPrimary} /> : null}
            {!streaming ? (
              <View style={styles.footer}>
                <Text style={[styles.meta, { color: c.textMuted, flexShrink: 1 }]}>
                  {[
                    msg.companies?.length ? `data: ${msg.companies.join(', ')}` : null,
                    msg.model ? (msg.model.includes('pro') ? 'Pro' : 'Flash') : null,
                    usage?.estimated_cost_usd != null ? `$${usage.estimated_cost_usd.toFixed(4)}` : null,
                  ].filter(Boolean).join(' · ')}
                </Text>
                <Pressable onPress={() => onSelect(toPlainText(msg.content))} hitSlop={8} style={styles.selectBtn} accessibilityLabel="Select text">
                  <Ionicons name="copy-outline" size={14} color={c.textMuted} />
                  <Text style={[styles.meta, { color: c.textMuted }]}>Select</Text>
                </Pressable>
              </View>
            ) : null}
          </>
        )}
      </Pressable>
    </View>
  );
}

const styles = StyleSheet.create({
  header: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.sm,
    paddingHorizontal: spacing.md,
    paddingBottom: spacing.sm,
    borderBottomWidth: StyleSheet.hairlineWidth,
  },
  iconBtn: { padding: 4 },
  title: { flex: 1, fontSize: fontSize.md, fontWeight: '700' },
  segment: { flexDirection: 'row', borderWidth: StyleSheet.hairlineWidth, borderRadius: radii.pill, padding: 2 },
  segmentBtn: { paddingHorizontal: 10, paddingVertical: 4, borderRadius: radii.pill },
  segmentLabel: { fontSize: fontSize.xs, fontWeight: '700' },
  center: { flex: 1, alignItems: 'center', justifyContent: 'center' },
  messages: { paddingHorizontal: spacing.md, paddingVertical: spacing.md, flexGrow: 1 },
  bubbleRow: { flexDirection: 'row', marginBottom: spacing.sm },
  bubbleRowUser: { justifyContent: 'flex-end' },
  bubble: { maxWidth: '92%', borderRadius: 16, paddingHorizontal: spacing.md, paddingVertical: spacing.sm + 2 },
  bubbleWide: { width: '92%' },
  userText: { fontSize: fontSize.md, lineHeight: 22 },
  statusRow: { flexDirection: 'row', alignItems: 'center', gap: spacing.sm, paddingVertical: 2 },
  status: { fontSize: fontSize.sm, fontStyle: 'italic' },
  footer: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', marginTop: spacing.xs },
  meta: { fontSize: fontSize.xs - 1, letterSpacing: 0.3 },
  selectBtn: { flexDirection: 'row', alignItems: 'center', gap: 3, paddingLeft: spacing.sm, paddingVertical: 2 },
  empty: { alignItems: 'center', paddingHorizontal: spacing.xl, paddingVertical: spacing.xxl, gap: spacing.sm },
  emptyTitle: { fontSize: fontSize.lg, fontWeight: '700' },
  emptyHint: { fontSize: fontSize.sm, lineHeight: 20, textAlign: 'center' },
  errorBar: { marginHorizontal: spacing.md, marginBottom: spacing.xs, padding: spacing.sm, borderRadius: radii.md },
  errorText: { fontSize: fontSize.sm },
  composer: {
    flexDirection: 'row',
    alignItems: 'flex-end',
    gap: spacing.sm,
    paddingHorizontal: spacing.md,
    paddingTop: spacing.sm,
    borderTopWidth: StyleSheet.hairlineWidth,
  },
  input: {
    flex: 1,
    minHeight: 40,
    maxHeight: 140,
    borderWidth: StyleSheet.hairlineWidth,
    borderRadius: 20,
    paddingHorizontal: spacing.md,
    paddingTop: 10,
    paddingBottom: 10,
    fontSize: fontSize.md,
  },
  sendBtn: { width: 36, height: 36, borderRadius: 18, alignItems: 'center', justifyContent: 'center', marginBottom: 2 },
  drawer: {
    position: 'absolute',
    top: 0,
    bottom: 0,
    left: 0,
    borderRightWidth: StyleSheet.hairlineWidth,
    shadowColor: '#000',
    shadowOpacity: 0.15,
    shadowRadius: 12,
    shadowOffset: { width: 4, height: 0 },
    elevation: 8,
  },
  drawerHeader: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', paddingHorizontal: spacing.lg, paddingBottom: spacing.md },
  drawerTitle: { fontSize: fontSize.lg, fontWeight: '700' },
  convRow: { paddingHorizontal: spacing.lg, paddingVertical: spacing.md, borderLeftWidth: 3 },
  convTitle: { fontSize: fontSize.md, fontWeight: '600' },
  convMeta: { fontSize: fontSize.xs, marginTop: 2 },
  drawerFoot: { fontSize: fontSize.xs, padding: spacing.lg },
});
