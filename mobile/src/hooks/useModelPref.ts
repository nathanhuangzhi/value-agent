/** The Flash / Pro choice, remembered across launches and shared by every chat surface. */
import AsyncStorage from '@react-native-async-storage/async-storage';
import { useEffect, useState } from 'react';

import { aiApi, type ModelKey, type ModelOption } from '../api/ai';

const MODEL_KEY = 'ai_model_v1';
const DEFAULT_OPTIONS: ModelOption[] = [
  { key: 'flash', id: 'deepseek-v4-flash', label: 'Flash', hint: 'fast · cheap' },
  { key: 'pro', id: 'deepseek-v4-pro', label: 'Pro', hint: 'deeper · ~5x cost' },
];

let cachedOptions: ModelOption[] | null = null;

export function useModelPref(fallback: ModelKey = 'flash'): [ModelKey, (m: ModelKey) => void, ModelOption[]] {
  const [model, setModel] = useState<ModelKey>(fallback);
  const [options, setOptions] = useState<ModelOption[]>(cachedOptions ?? DEFAULT_OPTIONS);
  useEffect(() => {
    AsyncStorage.getItem(MODEL_KEY).then((m) => {
      if (m === 'flash' || m === 'pro' || m === 'claude') setModel(m);
    }).catch(() => {});
    if (!cachedOptions) {
      aiApi.listModels().then((list) => {
        if (list.length) { cachedOptions = list; setOptions(list); }
      }).catch(() => {});
    }
  }, []);
  // A remembered choice the server no longer offers falls back to the first option.
  useEffect(() => {
    if (!options.some((o) => o.key === model)) setModel(options[0]?.key ?? fallback);
  }, [options, model, fallback]);
  const pick = (m: ModelKey) => {
    setModel(m);
    AsyncStorage.setItem(MODEL_KEY, m).catch(() => {});
  };
  return [model, pick, options];
}
