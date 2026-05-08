import type { AppTexts, Locale } from "./types";
import { enTexts } from "./locales/en";
import { zhTexts } from "./locales/zh";

export type { AppTexts, Locale } from "./types";

const texts: Record<Locale, AppTexts> = {
  en: enTexts,
  zh: zhTexts,
};

export function getTexts(locale: Locale): AppTexts {
  return texts[locale];
}
