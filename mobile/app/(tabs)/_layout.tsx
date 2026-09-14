/**
 * Bottom tab bar (phone + iPad portrait):
 *   - Daily Digest — the archive home: batch banners + industries list.
 *   - Saved        — the user's own watchlist, with a universe search bar.
 *   - AI           — DeepSeek chat grounded in the archive's company data.
 *
 * Detail screens (digest / industry / ticker) live in the root Stack and
 * push over the tabs, so the tab bar hides while drilled in. iPad
 * landscape uses SplitLayout instead (see app/_layout.tsx) — the sidebar
 * carries the same two entries.
 */
import { Ionicons } from '@expo/vector-icons';
import { Tabs } from 'expo-router';

import { useColors } from '@/theme/colors';

export default function TabsLayout() {
  const c = useColors();
  return (
    <Tabs
      screenOptions={{
        headerStyle: { backgroundColor: c.background },
        headerTintColor: c.textPrimary,
        headerTitleStyle: { fontWeight: '700', fontSize: 17 },
        headerShadowVisible: false,
        sceneStyle: { backgroundColor: c.background },
        tabBarStyle: { backgroundColor: c.background, borderTopColor: c.border },
        tabBarActiveTintColor: c.brand,
        tabBarInactiveTintColor: c.textMuted,
        tabBarLabelStyle: { fontSize: 11, fontWeight: '600' },
      }}
    >
      <Tabs.Screen
        name="index"
        options={{
          title: 'Valueland',
          tabBarLabel: 'Daily Digest',
          tabBarIcon: ({ color, size }) => (
            <Ionicons name="newspaper-outline" color={color} size={size} />
          ),
        }}
      />
      <Tabs.Screen
        name="ai"
        options={{
          title: 'AI',
          // The screen draws its own header (drawer button + model toggle).
          headerShown: false,
          tabBarIcon: ({ color, size }) => (
            <Ionicons name="sparkles-outline" color={color} size={size} />
          ),
        }}
      />
      <Tabs.Screen
        name="saved"
        options={{
          title: 'Saved',
          tabBarLabel: 'Saved',
          tabBarIcon: ({ color, size }) => (
            <Ionicons name="bookmark-outline" color={color} size={size} />
          ),
        }}
      />
    </Tabs>
  );
}
