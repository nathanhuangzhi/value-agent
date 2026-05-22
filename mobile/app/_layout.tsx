import { Stack } from 'expo-router';
import { StatusBar } from 'expo-status-bar';
import { SafeAreaProvider } from 'react-native-safe-area-context';
import { useColorScheme } from 'react-native';

import { useColors } from '@/theme/colors';
import { useIsTabletLandscape } from '@/hooks/useDeviceClass';
import { SplitLayout } from '@/components/SplitLayout';


/**
 * Layout switch:
 *   - iPad landscape (≥1024 pt wide): two-pane SplitLayout with a
 *     persistent sidebar + the current route's content in the right pane.
 *   - Everything else (iPhone, iPad portrait): the original Stack with
 *     drill-in navigation. Phone UX is unchanged.
 *
 * Re-evaluates on orientation change because `useWindowDimensions` (read
 * by useIsTabletLandscape) triggers a re-render when the device rotates.
 */
export default function RootLayout() {
  const c = useColors();
  const scheme = useColorScheme();
  const isTabletLandscape = useIsTabletLandscape();

  return (
    <SafeAreaProvider>
      <StatusBar style={scheme === 'dark' ? 'light' : 'dark'} />
      {isTabletLandscape ? (
        <SplitLayout />
      ) : (
        <Stack
          screenOptions={{
            headerStyle: { backgroundColor: c.background },
            headerTintColor: c.textPrimary,
            headerTitleStyle: { fontWeight: '700', fontSize: 17 },
            contentStyle: { backgroundColor: c.background },
          }}
        >
          <Stack.Screen name="index" options={{ title: 'Valueland' }} />
          <Stack.Screen
            name="digest"
            options={{ title: "Today's Digest", headerBackTitle: 'Back' }}
          />
          <Stack.Screen
            name="industry/[slug]"
            options={{ title: '', headerBackTitle: 'Back' }}
          />
          <Stack.Screen
            name="ticker/[symbol]"
            options={{
              title: '',
              headerBackTitle: 'Back',
              // Disable iOS edge-swipe-back so our left/right swipe-to-
              // navigate-siblings gesture doesn't fight the system back
              // gesture. Use the header back button to return.
              gestureEnabled: false,
            }}
          />
        </Stack>
      )}
    </SafeAreaProvider>
  );
}
