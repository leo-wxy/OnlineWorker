import App from "./App";
import { I18nProvider } from "./i18n";

export default function MainApp() {
  return (
    <I18nProvider>
      <App />
    </I18nProvider>
  );
}
