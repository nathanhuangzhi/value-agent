/** The Flash / Pro choice, remembered across launches and shared by every chat surface. */
import AsyncStorage from '@react-native-async-storage/async-storage';
import { useEffect, useState } from 'react';

import type { ModelKey } from '../api/ai';

const MODEL_KEY = 'ai_model_v1';

export function useModelPref(fallback: ModelKey = 'flash'): [ModelKey, (m: ModelKey) => void] {
  const [model, setModel] = useState<ModelKey>(fallback);
  useEffect(() => {
    AsyncStorage.getItem(MODEL_KEY).then((m) => {
      if (m === 'flash' || m === 'pro') setModel(m);
    }).catch(() => {});
  }, []);
  const pick = (m: ModelKey) => {
    setModel(m);
    AsyncStorage.setItem(MODEL_KEY, m).catch(() => {});
  };
  return [model, pick];
}
