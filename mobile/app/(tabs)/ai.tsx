/**
 * AI tab — a DeepSeek chat grounded in the archive's company data.
 *
 *   ┌ ☰  Title of chat            [Flash|Pro]  ＋ ┐   custom header
 *   │  …messages (inverted list, streaming)…      │
 *   └ [ Ask about any company…            ➤ ] ────┘   composer
 *
 * The ☰ slides in a left panel with past conversations (server-side, so
 * they follow the user across devices). Mention a ticker or company
 * name and the server attaches its data; the model can also look
 * companies up itself. Conversation state lives in useConversation
 * (shared with the company-page chat); this screen owns the drawer,
 * the inverted list and the header.
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
  View,
  useWindowDimensions,
} from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { aiApi, type ChatMessage, type ConversationSummary } from '@/api/ai';
import { Composer } from '@/components/chat/Composer';
import { MessageRow } from '@/components/chat/MessageRow';
import { ModelToggle } from '@/components/chat/ModelToggle';
import { ScrollToBottomButton } from '@/components/ScrollToBottomButton';
import { SelectTextSheet } from '@/components/SelectTextSheet';
import { LAST_CONV_KEY, useConversation } from '@/hooks/useConversation';
import { useModelPref } from '@/hooks/useModelPref';
import { useColors, fontSize, radii, spacing } from '@/theme/colors';
import { formatDate, modelLabel } from '@/utils/format';

type Row = ChatMessage & { _streaming?: boolean };

export default function AiScreen() {
  const c = useColors();
  const insets = useSafeAreaInsets();
  const { width } = useWindowDimensions();
  const [model, pickModel, modelOptions] = useModelPref();
  const [conversations, setConversations] = useState<ConversationSummary[] | null>(null);
  const [input, setInput] = useState('');

  const refreshList = useCallback(async () => {
    try {
      setConversations(await aiApi.listConversations());
    } catch {
      // the drawer shows "Loading…" until a list arrives
    }
  }, []);
  const chat = useConversation({ onChanged: refreshList });
  const openRef = useRef(chat.open);
  openRef.current = chat.open;

  // Reopen the last conversation on launch.
  useEffect(() => {
    (async () => {
      await refreshList();
      try {
        const last = await AsyncStorage.getItem(LAST_CONV_KEY);
        if (last) await openRef.current(last);
      } catch {
        // ignore
      }
    })();
  }, [refreshList]);

  const newChat = () => chat.reset(true);

  const deleteConversation = (conv: ConversationSummary) =>
    Alert.alert(`Delete "${conv.title}"?`, undefined, [
      { text: 'Cancel', style: 'cancel' },
      {
        text: 'Delete',
        style: 'destructive',
        onPress: async () => {
          try {
            await aiApi.deleteConversation(conv.id);
            if (chat.convId === conv.id) newChat();
            await refreshList();
          } catch (e) {
            chat.setError(String((e as Error).message ?? e));
          }
        },
      },
    ]);

  const send = async () => {
    const text = input.trim();
    if (!text) return;
    setInput('');
    if (!(await chat.send(text, model))) setInput(text);
  };

  // ---- drawer ----
  const drawerWidth = Math.min(320, width * 0.82);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [selectText, setSelectText] = useState<string | null>(null);   // message open in the select/copy sheet
  const [listW, setListW] = useState(0);
  const listRef = useRef<FlatList<Row>>(null);
  const [awayFromBottom, setAwayFromBottom] = useState(false);   // inverted list: offset 0 is the newest message
  const contentW = listW ? listW - 2 * spacing.md : undefined;   // replies run the full width of the list
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
    const rows: Row[] = [...chat.messages];
    if (chat.streaming) rows.push({ role: 'assistant', content: chat.streaming.text, _streaming: true });
    return rows.reverse();
  }, [chat.messages, chat.streaming]);

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
        <Text style={[styles.title, { color: c.textPrimary }]} numberOfLines={1}>{chat.title ?? 'New chat'}</Text>
        <ModelToggle value={model} onChange={pickModel} options={modelOptions} />
        <Pressable onPress={newChat} hitSlop={10} style={styles.iconBtn}>
          <Ionicons name="create-outline" size={24} color={c.textPrimary} />
        </Pressable>
      </View>

      {/* Messages */}
      {chat.loading && !chat.convId ? (
        <View style={styles.center}><ActivityIndicator color={c.brand} /></View>
      ) : (
        <View style={{ flex: 1 }}>
          <FlatList
            ref={listRef}
            inverted
            onLayout={(e) => setListW(e.nativeEvent.layout.width)}
            onScroll={(e) => {
              const away = e.nativeEvent.contentOffset.y > 160;
              setAwayFromBottom((prev) => (prev === away ? prev : away));
            }}
            scrollEventThrottle={48}
            data={data}
            keyExtractor={(_, i) => String(i)}
            contentContainerStyle={styles.messages}
            keyboardDismissMode="interactive"
            keyboardShouldPersistTaps="handled"
            renderItem={({ item }) => (
              <MessageRow
                msg={item}
                streaming={item._streaming ? chat.streaming : null}
                onSelect={setSelectText}
                contentW={contentW}
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
          <ScrollToBottomButton
            visible={awayFromBottom}
            onPress={() => listRef.current?.scrollToOffset({ offset: 0, animated: true })}
          />
        </View>
      )}

      {chat.error ? (
        <Pressable onPress={() => chat.setError(null)} style={[styles.errorBar, { backgroundColor: c.statusErrorBg }]}>
          <Text style={[styles.errorText, { color: c.negative }]} numberOfLines={3}>{chat.error}</Text>
        </Pressable>
      ) : null}

      <SelectTextSheet text={selectText} visible={selectText !== null} onClose={() => setSelectText(null)} />

      <Composer
        value={input}
        onChange={setInput}
        placeholder={`Ask ${modelOptions.find((o) => o.key === model)?.label ?? 'AI'} about any company…`}
        streaming={chat.streaming !== null}
        canSend={input.trim().length > 0}
        onSend={send}
        onStop={chat.stop}
        style={[styles.composer, { borderTopColor: c.border, backgroundColor: c.background, paddingBottom: spacing.sm }]}
      />

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
                const active = item.id === chat.convId;
                return (
                  <Pressable
                    onPress={() => { toggleDrawer(false); chat.open(item.id); }}
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
                      {formatDate(item.updated_at)} · {item.message_count} msgs · {modelLabel(item.model)}
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
  center: { flex: 1, alignItems: 'center', justifyContent: 'center' },
  messages: { paddingHorizontal: spacing.md, paddingVertical: spacing.md, flexGrow: 1 },
  empty: { alignItems: 'center', paddingHorizontal: spacing.xl, paddingVertical: spacing.xxl, gap: spacing.sm },
  emptyTitle: { fontSize: fontSize.lg, fontWeight: '700' },
  emptyHint: { fontSize: fontSize.sm, lineHeight: 20, textAlign: 'center' },
  errorBar: { marginHorizontal: spacing.md, marginBottom: spacing.xs, padding: spacing.sm, borderRadius: radii.md },
  errorText: { fontSize: fontSize.sm },
  composer: { paddingHorizontal: spacing.md, paddingTop: spacing.sm, borderTopWidth: StyleSheet.hairlineWidth },
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
