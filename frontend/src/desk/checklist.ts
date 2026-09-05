/**
 * Notların içindeki kontrol listesi satırları.
 *
 * Tasarımda Notlar ve Görevler pencereleri işaretlenebilir maddeler
 * gösteriyor. Bunun için backend'e ayrı bir "görev" tablosu EKLENMEDİ:
 * bir görev zaten bir notun bir satırıdır ve ikinci bir depo, aynı şeyin
 * iki yerde tutulması demek olurdu — biri güncellenip diğeri unutulduğunda
 * kullanıcı hangisinin doğru olduğunu bilemezdi.
 *
 * Biçim markdown'ın kendi kuralıdır (`- [ ]` / `- [x]`). Uydurulmuş bir
 * işaret yerine bunun seçilmesi, notun başka bir yerde (ajan tarafından,
 * bir editörde) okunduğunda da anlamını korumasını sağlar.
 */

export interface ChecklistItem {
  /** Satırın not içindeki sırası — geri yazarken adres olarak kullanılır. */
  line: number;
  text: string;
  done: boolean;
}

const ITEM = /^(\s*)[-*]\s+\[([ xX])\]\s?(.*)$/;

/** Bir notun gövdesindeki işaretlenebilir satırları çıkarır. */
export function parseChecklist(content: string): ChecklistItem[] {
  const items: ChecklistItem[] = [];
  content.split('\n').forEach((raw, index) => {
    const match = ITEM.exec(raw);
    if (match) {
      items.push({ line: index, text: match[3].trim(), done: match[2].toLowerCase() === 'x' });
    }
  });
  return items;
}

/**
 * Bir satırın işaretini ters çevirir ve YENİ gövdeyi döndürür.
 *
 * Yalnızca o satır değişir; notun geri kalanı karakterine kadar korunur.
 * Gövdeyi maddelerden yeniden üretmek, madde olmayan her satırı (başlık,
 * açıklama, boş satır) silmek olurdu.
 */
export function toggleLine(content: string, line: number): string {
  const lines = content.split('\n');
  const raw = lines[line];
  if (raw === undefined) return content;
  const match = ITEM.exec(raw);
  if (!match) return content;
  const next = match[2].toLowerCase() === 'x' ? ' ' : 'x';
  lines[line] = `${match[1]}- [${next}] ${match[3]}`;
  return lines.join('\n');
}

/** Notun sonuna yeni bir işaretlenmemiş madde ekler. */
export function appendItem(content: string, text: string): string {
  const trimmed = content.replace(/\s+$/, '');
  return `${trimmed}\n- [ ] ${text.trim()}`;
}

/** Maddesi olmayan notlarda gövdeyi okunur satırlara böler. */
export function plainLines(content: string): string[] {
  return content.split('\n').filter((line) => line.trim().length > 0);
}
