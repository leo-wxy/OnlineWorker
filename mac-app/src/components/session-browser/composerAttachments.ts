import { useCallback, useState, type Dispatch, type SetStateAction } from "react";
import type { ComposerAttachment } from "../../types";
import { stageComposerAttachments } from "./api";

async function readFileAsBase64(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onerror = () => reject(reader.error ?? new Error("Failed to read attachment"));
    reader.onload = () => {
      const result = typeof reader.result === "string" ? reader.result : "";
      const commaIndex = result.indexOf(",");
      resolve(commaIndex >= 0 ? result.slice(commaIndex + 1) : result);
    };
    reader.readAsDataURL(file);
  });
}

export async function stageBrowserFiles(files: File[]): Promise<ComposerAttachment[]> {
  const payload = await Promise.all(
    files.map(async (file) => ({
      path: "",
      name: file.name,
      mimeType: file.type || null,
      sizeBytes: file.size,
      base64Data: await readFileAsBase64(file),
    })),
  );
  return stageComposerAttachments(payload);
}

export function useStagedAttachments({
  supportsAttachments,
  unsupportedMessage,
  setError,
  setAttachments,
}: {
  supportsAttachments: boolean;
  unsupportedMessage: string;
  setError: (message: string | null) => void;
  setAttachments: Dispatch<SetStateAction<ComposerAttachment[]>>;
}) {
  const [stagingAttachments, setStagingAttachments] = useState(false);

  const handlePickFiles = useCallback(async (_kind: "file" | "image", files: FileList | File[]) => {
    if (!supportsAttachments) {
      setError(unsupportedMessage);
      return;
    }
    setStagingAttachments(true);
    try {
      const staged = await stageBrowserFiles(Array.from(files));
      setError(null);
      setAttachments((current) => [...current, ...staged]);
    } catch (error) {
      setError((error as Error).message);
    } finally {
      setStagingAttachments(false);
    }
  }, [setAttachments, setError, supportsAttachments, unsupportedMessage]);

  return { stagingAttachments, handlePickFiles };
}
