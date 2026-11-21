/** Citește un fișier XML respectând `encoding=` din prolog (exporturile 1C sunt adesea windows-1251). */
export async function readXmlFile(file: File): Promise<string> {
  const bytes = await file.arrayBuffer();
  const head = new TextDecoder("latin1").decode(bytes.slice(0, 200));
  const label = /<\?xml[^>]*encoding=["']([\w.-]+)["']/i.exec(head)?.[1] ?? "utf-8";
  try {
    return new TextDecoder(label).decode(bytes);
  } catch {
    return new TextDecoder("utf-8").decode(bytes);
  }
}
