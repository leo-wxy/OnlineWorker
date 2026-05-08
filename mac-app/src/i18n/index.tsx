import {
  createContext,
  useContext,
  useEffect,
  useState,
  type ReactNode,
} from "react";

import { getTexts, type AppTexts, type Locale } from "./texts";

export { getTexts, type AppTexts, type Locale } from "./texts";

const LOCALE_STORAGE_KEY = "onlineworker.locale";

interface I18nContextValue {
  locale: Locale;
  setLocale: (locale: Locale) => void;
  t: AppTexts;
}

const I18nContext = createContext<I18nContextValue | null>(null);

export function detectLocale(): Locale {
  if (typeof navigator === "undefined") {
    return "en";
  }
  const lang = navigator.language || "";
  return lang.startsWith("zh") ? "zh" : "en";
}

function readInitialLocale(): Locale {
  if (typeof window === "undefined") {
    return detectLocale();
  }
  const stored = window.localStorage.getItem(LOCALE_STORAGE_KEY);
  if (stored === "en" || stored === "zh") {
    return stored;
  }
  return detectLocale();
}

export function I18nProvider({ children }: { children: ReactNode }) {
  const [locale, setLocale] = useState<Locale>(readInitialLocale);

  useEffect(() => {
    window.localStorage.setItem(LOCALE_STORAGE_KEY, locale);
  }, [locale]);

  return (
    <I18nContext.Provider value={{ locale, setLocale, t: getTexts(locale) }}>
      {children}
    </I18nContext.Provider>
  );
}

export function useI18n(): I18nContextValue {
  const context = useContext(I18nContext);
  if (!context) {
    throw new Error("useI18n must be used within I18nProvider");
  }
  return context;
}
