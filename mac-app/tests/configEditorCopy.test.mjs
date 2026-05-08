import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const __dirname = dirname(fileURLToPath(import.meta.url));
const root = join(__dirname, "..");

function readLocale(name) {
  return readFileSync(join(root, "src", "i18n", "locales", `${name}.ts`), "utf8");
}

test("advanced config tab labels stay plain and compact", () => {
  for (const locale of ["en", "zh"]) {
    const source = readLocale(locale);

    assert.match(source, /yamlTab:\s*"config\.yaml"/);
    assert.match(source, /envTab:\s*"\.env"/);
    assert.doesNotMatch(source, /yamlTab:\s*"[^"]*[📄🔐👁🔒]/u);
    assert.doesNotMatch(source, /envTab:\s*"[^"]*[📄🔐👁🔒]/u);
    assert.doesNotMatch(source, /reveal:\s*"[^"]*[📄🔐👁🔒]/u);
    assert.doesNotMatch(source, /conceal:\s*"[^"]*[📄🔐👁🔒]/u);
  }
});

test("advanced config starts from file choices instead of eager raw content", () => {
  const source = readFileSync(join(root, "src", "components", "ConfigEditor.tsx"), "utf8");

  assert.match(source, /useState<FilePanel \| null>\(null\)/);
  assert.doesNotMatch(source, /useState<ConfigSection>\("yaml"\)/);
});
