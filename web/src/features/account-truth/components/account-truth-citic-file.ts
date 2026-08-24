export const CITIC_HISTORY_XLS_MAX_BYTES = 10 * 1024 * 1024;
export const CITIC_HISTORY_XLS_MAX_FILES = 24;

export function readCiticFileAsBase64(file: File) {
  return new Promise<string>((resolve, reject) => {
    const reader = new FileReader();
    reader.onerror = () =>
      reject(reader.error ?? new Error('file read failed'));
    reader.onload = () => {
      if (typeof reader.result !== 'string') {
        reject(new Error('file read failed'));
        return;
      }
      const separatorIndex = reader.result.indexOf(',');
      if (separatorIndex < 0) {
        reject(new Error('file read failed'));
        return;
      }
      resolve(reader.result.slice(separatorIndex + 1));
    };
    reader.readAsDataURL(file);
  });
}
