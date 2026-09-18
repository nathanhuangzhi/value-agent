/**
 * Minimal Markdown renderer for chat replies — enough for what the model
 * actually emits: headings, bullet / numbered lists, paragraphs, **bold**,
 * `code`, and pipe tables (rendered as a horizontally-scrollable grid).
 * No dependency; anything fancier falls through as plain text.
 */
import { useState, type ReactNode } from 'react';
import { Platform, ScrollView, StyleSheet, Text, TextInput, View, type TextStyle } from 'react-native';

import { CustomChart } from '@/components/CustomChart';
import { MetricTile } from '@/components/MetricTile';
import { useColors, chatType, fontSize, spacing } from '@/theme/colors';

type Block =
  | { kind: 'h'; level: number; text: string }
  | { kind: 'p'; text: string }
  | { kind: 'li'; ordered: boolean; marker: string; text: string }
  | { kind: 'table'; rows: string[][] }
  | { kind: 'code'; text: string }
  /** `{{chart:12:VIPS}}` / `{{metric:3:VIPS}}` — a saved chart or metric the reply embeds. */
  | { kind: 'embed'; what: 'chart' | 'metric'; id: number; ticker: string };

const EMBED_RE = /^\s*\{\{(chart|metric):(\d+):([A-Za-z.\-]{1,10})\}\}\s*$/;

function parse(md: string): Block[] {
  const lines = md.replace(/\r/g, '').split('\n');
  const blocks: Block[] = [];
  let para: string[] = [];
  let table: string[][] | null = null;
  let code: string[] | null = null;

  const flushPara = () => {
    if (para.length) blocks.push({ kind: 'p', text: para.join(' ') });
    para = [];
  };
  const flushTable = () => {
    if (table && table.length) blocks.push({ kind: 'table', rows: table });
    table = null;
  };

  for (const raw of lines) {
    const line = raw.trimEnd();
    if (code) {
      if (line.startsWith('```')) {
        blocks.push({ kind: 'code', text: code.join('\n') });
        code = null;
      } else code.push(raw);
      continue;
    }
    if (line.startsWith('```')) {
      flushPara(); flushTable(); code = [];
      continue;
    }
    const em = EMBED_RE.exec(line);
    if (em) {
      flushPara(); flushTable();
      blocks.push({ kind: 'embed', what: em[1] as 'chart' | 'metric', id: parseInt(em[2], 10), ticker: em[3].toUpperCase() });
      continue;
    }
    if (/^\s*\|.*\|\s*$/.test(line)) {
      flushPara();
      const cells = line.trim().slice(1, -1).split('|').map((c) => c.trim());
      if (cells.every((c) => /^:?-{2,}:?$/.test(c))) continue; // separator row
      (table ??= []).push(cells);
      continue;
    }
    flushTable();
    const h = /^(#{1,4})\s+(.*)$/.exec(line);
    if (h) { flushPara(); blocks.push({ kind: 'h', level: h[1].length, text: h[2] }); continue; }
    const li = /^\s*([-*•]|\d+[.)])\s+(.*)$/.exec(line);
    if (li) {
      flushPara();
      const ordered = /\d/.test(li[1]);
      blocks.push({ kind: 'li', ordered, marker: ordered ? li[1].replace(')', '.') : '•', text: li[2] });
      continue;
    }
    if (!line.trim()) { flushPara(); continue; }
    para.push(line.trim());
  }
  if (code) blocks.push({ kind: 'code', text: code.join('\n') });
  flushPara(); flushTable();
  return blocks;
}

/**
 * The message as plain text for the select/copy sheet: Markdown markers
 * stripped, list markers kept, tables flattened to "a · b · c" lines.
 */
export function toPlainText(md: string): string {
  const out: string[] = [];
  for (const b of parse(md)) {
    switch (b.kind) {
      case 'h': out.push(strip(b.text), ''); break;
      case 'p': out.push(strip(b.text), ''); break;
      case 'li': out.push(`${b.marker} ${strip(b.text)}`); break;
      case 'code': out.push(b.text, ''); break;
      case 'table':
        for (const row of b.rows) out.push(row.map(strip).join('  ·  '));
        out.push('');
        break;
      case 'embed': out.push(`[${b.what} #${b.id} · ${b.ticker}]`, ''); break;
    }
  }
  return out.join('\n').replace(/\n{3,}/g, '\n\n').trim();
}

const strip = (t: string) => t.replace(/\*\*([^*]+)\*\*/g, '$1').replace(/`([^`]+)`/g, '$1');

/** Inline **bold** and `code`; everything else verbatim. */
function Inline({ text, style }: { text: string; style: TextStyle }) {
  const c = useColors();
  const parts = text.split(/(\*\*[^*]+\*\*|`[^`]+`)/g).filter(Boolean);
  return (
    <Text style={style}>
      {parts.map((p, i) => {
        if (p.startsWith('**') && p.endsWith('**')) {
          return <Text key={i} style={{ fontWeight: '700' }}>{p.slice(2, -2)}</Text>;
        }
        if (p.startsWith('`') && p.endsWith('`')) {
          return (
            <Text key={i} style={{ fontFamily: 'Menlo', backgroundColor: c.surface, fontSize: (style.fontSize ?? chatType.size) - 2 }}>
              {p.slice(1, -1)}
            </Text>
          );
        }
        return <Text key={i}>{p}</Text>;
      })}
    </Text>
  );
}

const NUMERIC = /^[\s$€£¥(+-]*[\d.,]+[\s%)xX×BMKbmk]*$|^[-–—]$/;
const CJK = /[\u2E80-\u9FFF\uF900-\uFAFF\uFF00-\uFFEF]/;

/** Rough rendered width of a cell at the table's 13px font, incl. padding. */
function estWidth(text: string, bold: boolean): number {
  let w = 0;
  for (const ch of strip(text)) {
    w += CJK.test(ch) ? 13 : /[0-9]/.test(ch) ? 7.4 : /[A-Z]/.test(ch) ? 8.6 : /[ .,:;'|()-]/.test(ch) ? 3.8 : 7;
  }
  return (bold ? w * 1.06 : w) + 14;
}

/**
 * Pipe table. Column widths come from the content: when they add up to
 * less than the bubble, the columns stretch to fill it and cell text
 * wraps; when they don't, the table keeps its natural width and scrolls
 * sideways — never overflowing the screen. A column is right-aligned when
 * its body cells are numbers.
 */
function Table({ rows, body, width }: { rows: string[][]; body: TextStyle; width?: number }) {
  const c = useColors();
  const [measured, setMeasured] = useState(0);
  const avail = width ?? measured;
  const cols = Math.max(...rows.map((r) => r.length));
  const numeric = Array.from({ length: cols }, (_, k) =>
    k > 0 && rows.slice(1).every((r) => !r[k] || NUMERIC.test(r[k].trim())));
  const natural = Array.from({ length: cols }, (_, k) => {
    const longest = Math.max(...rows.map((r, i) => estWidth(r[k] ?? '', i === 0)));
    return k === 0 ? Math.min(Math.max(longest, 72), 220) : Math.min(Math.max(longest, 56), 180);
  });
  const total = natural.reduce((a, b) => a + b, 0);
  const fits = avail > 0 && total <= avail;
  const widths = fits ? natural.map((w) => (w / total) * avail) : natural;
  const cell: TextStyle = { ...body, fontSize: fontSize.sm, lineHeight: 18, fontVariant: ['tabular-nums'] };
  const grid = (
    <View style={[styles.table, { borderColor: c.border }]}>
      {rows.map((row, r) => (
        <View
          key={r}
          style={[
            styles.tr,
            r === 0 ? { borderBottomWidth: 1, borderBottomColor: c.border } : { borderBottomWidth: StyleSheet.hairlineWidth, borderBottomColor: c.border },
            r > 0 && r % 2 === 0 && { backgroundColor: c.background },
          ]}
        >
          {Array.from({ length: cols }, (_, k) => (
            <View
              key={k}
              style={[styles.td, { width: widths[k], alignItems: numeric[k] ? 'flex-end' : 'flex-start' }]}
            >
              <Inline
                text={row[k] ?? ''}
                style={{ ...cell, fontWeight: r === 0 ? '700' : '400', textAlign: numeric[k] ? 'right' : 'left' }}
              />
            </View>
          ))}
        </View>
      ))}
    </View>
  );
  // The wrapper always has a definite width (the caller's, else measured)
  // and clips; anything wider than it lives inside the horizontal
  // ScrollView, so the table can never push the bubble off-screen.
  return (
    <View
      style={[styles.tableWrap, avail > 0 && { width: avail }]}
      onLayout={width ? undefined : (e) => setMeasured(e.nativeEvent.layout.width)}
    >
      {fits ? grid : (
        <ScrollView horizontal showsHorizontalScrollIndicator style={avail > 0 && { width: avail }}>
          {grid}
        </ScrollView>
      )}
    </View>
  );
}

/** True when the reply carries a pipe table — the bubble should then take the full width. */
export function hasTable(md: string): boolean {
  return /^\s*\|.*\|\s*$/m.test(md);
}

/**
 * A run of prose (everything between tables) as ONE natively selectable
 * text: on iOS a read-only multiline TextInput (UITextView), which gives
 * the system long-press → selection handles → Copy, exactly like ChatGPT /
 * Claude; on Android a selectable Text does the same. Styled spans
 * (headings, bold, code) are nested Text children.
 */
export function SelectableProse({ style, children }: { style: TextStyle; children: ReactNode }) {
  if (Platform.OS === 'ios') {
    return (
      <TextInput
        multiline
        editable={false}
        scrollEnabled={false}
        textAlignVertical="top"
        style={[style, styles.prose]}
      >
        {children}
      </TextInput>
    );
  }
  return <Text selectable style={style}>{children}</Text>;
}

/**
 * `width` is the content width available to the block (the bubble's inner
 * width). Pass it whenever it is known — tables size their columns from it
 * and scroll sideways when they don't fit.
 *
 * Prose blocks are grouped into runs and rendered as SelectableProse, so a
 * selection can span paragraphs; tables sit between runs as their own
 * (horizontally scrollable) views.
 */
export function Markdown({ text, color, width }: { text: string; color: string; width?: number }) {
  const c = useColors();
  const body: TextStyle = { color, fontSize: chatType.size, lineHeight: chatType.lineHeight };
  const blocks = parse(text);

  type Prose = Exclude<Block, { kind: 'table' | 'embed' }>;
  type TableBlock = Extract<Block, { kind: 'table' }>;
  type EmbedBlock = Extract<Block, { kind: 'embed' }>;
  const runs: (Prose[] | TableBlock | EmbedBlock)[] = [];
  for (const b of blocks) {
    if (b.kind === 'table' || b.kind === 'embed') { runs.push(b); continue; }
    const last = runs[runs.length - 1];
    if (Array.isArray(last)) last.push(b); else runs.push([b]);
  }

  const gap = <Text style={{ fontSize: 4, lineHeight: chatType.paragraphGap }}>{'\n'}</Text>;
  const span = (b: Prose, key: number, first: boolean) => {
    switch (b.kind) {
      case 'h':
        return (
          <Text key={key}>
            {first ? null : gap}
            <Inline
              text={b.text}
              style={{
                ...body,
                fontWeight: '600',
                fontSize: b.level === 1 ? chatType.h1 : b.level === 2 ? chatType.h2 : chatType.h3,
                lineHeight: b.level === 1 ? 30 : chatType.lineHeight + 2,
              }}
            />
            {'\n'}
          </Text>
        );
      case 'li':
        return (
          <Text key={key}>
            <Text style={body}>{`${b.marker}  `}</Text>
            <Inline text={b.text} style={body} />
            {'\n'}
          </Text>
        );
      case 'code':
        return (
          <Text key={key}>
            {first ? null : gap}
            <Text style={{ ...body, fontFamily: 'Menlo', fontSize: chatType.code, lineHeight: 22, backgroundColor: c.surface }}>{b.text}</Text>
            {'\n'}
          </Text>
        );
      default:
        return (
          <Text key={key}>
            {first ? null : gap}
            <Inline text={b.text} style={body} />
            {'\n'}
          </Text>
        );
    }
  };

  return (
    <View>
      {runs.map((r, i) =>
        Array.isArray(r) ? (
          <SelectableProse key={i} style={body}>
            {r.map((b, j) => span(b, j, j === 0))}
          </SelectableProse>
        ) : r.kind === 'embed' ? (
          r.what === 'chart'
            ? <CustomChart key={i} chartId={r.id} ticker={r.ticker} />
            : <MetricTile key={i} metricId={r.id} ticker={r.ticker} />
        ) : (
          <Table key={i} rows={r.rows} body={body} width={width} />
        ),
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  prose: { padding: 0, paddingTop: 0, margin: 0, backgroundColor: 'transparent' },
  tableWrap: { marginVertical: spacing.sm, alignSelf: 'stretch' },
  table: { borderWidth: StyleSheet.hairlineWidth, borderRadius: 6, overflow: 'hidden' },
  tr: { flexDirection: 'row' },
  td: { paddingVertical: 5, paddingHorizontal: 6, justifyContent: 'center' },
});
