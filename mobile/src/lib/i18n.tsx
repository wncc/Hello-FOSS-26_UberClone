import { getLocales } from 'expo-localization';
import React, {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
} from 'react';

import { storage } from '@/lib/storage';
import en from '@/lib/locales/en';
import hi from '@/lib/locales/hi';
import mr from '@/lib/locales/mr';

export type Language = 'en' | 'hi' | 'mr';
type TranslationKey = keyof typeof en;
type Values = Record<string, string | number>;

const dictionaries = { en, hi, mr };

function phoneLanguage(): Language {
  const code = getLocales()[0]?.languageCode;
  return code === 'hi' || code === 'mr' ? code : 'en';
}

function translate(
  language: Language,
  key: TranslationKey,
  values?: Values,
): string {
  let result: string = dictionaries[language][key];

  if (values) {
    for (const [name, value] of Object.entries(values)) {
      result = result.replaceAll(`{{${name}}}`, String(value));
    }
  }

  return result;
}

type LanguageContextValue = {
  language: Language;
  ready: boolean;
  setLanguage: (language: Language) => Promise<void>;
  t: (key: TranslationKey, values?: Values) => string;
};

const LanguageContext = createContext<LanguageContextValue | null>(null);

export function LanguageProvider({ children }: { children: React.ReactNode }) {
  const [language, updateLanguage] = useState<Language>('en');
  const [ready, setReady] = useState(false);

  useEffect(() => {
    let alive = true;

    storage.get('app.language')
      .then((saved) => {
        if (alive) {
          const selected: Language =
            saved === 'en' || saved === 'hi' || saved === 'mr'
              ? saved
              : phoneLanguage();

          updateLanguage(selected);
        }
      })
      .catch(() => {
        if (alive) updateLanguage(phoneLanguage());
      })
      .finally(() => {
        if (alive) setReady(true);
      });

    return () => {
      alive = false;
    };
  }, []);

  const setLanguage = useCallback(async (next: Language) => {
    updateLanguage(next);
    try {
      await storage.set('app.language', next);
    } catch {
      // The language still changes for the current app session.
    }
  }, []);

  const t = useCallback(
    (key: TranslationKey, values?: Values) => translate(language, key, values),
    [language],
  );

  const value = useMemo(
    () => ({ language, ready, setLanguage, t }),
    [language, ready, setLanguage, t],
  );

  return (
    <LanguageContext.Provider value={value}>
      {children}
    </LanguageContext.Provider>
  );
}

export function useLanguage() {
  const context = useContext(LanguageContext);
  if (!context) {
    throw new Error('useLanguage must be used inside LanguageProvider');
  }
  return context;
}