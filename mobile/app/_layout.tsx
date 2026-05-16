import { Stack } from 'expo-router';
import { StatusBar } from 'expo-status-bar';
import { SafeAreaProvider } from 'react-native-safe-area-context';
import { useColorScheme } from 'react-native';

import { useColors } from '@/theme/colors';

export default function RootLayout() {
  const c = useColors();
  const scheme = useColorScheme();
  return (
    <SafeAreaProvider>
      <StatusBar style={scheme === 'dark' ? 'light' : 'dark'} />
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
          options={{ title: '', headerBackTitle: 'Back' }}
        />
      </Stack>
    </SafeAreaProvider>
  );
}
