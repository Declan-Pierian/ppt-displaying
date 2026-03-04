import type { CSSProperties } from "react";
import type { TableShape, TableCell, ParagraphData, TextRun } from "../../types/slide";
import { emuToPx } from "../../lib/slideUtils";

interface Props {
  shape: TableShape;
}

export default function TableRenderer({ shape }: Props) {
  const table = shape.table;

  const containerStyle: CSSProperties = {
    position: "absolute",
    left: emuToPx(shape.position.left_emu),
    top: emuToPx(shape.position.top_emu),
    width: emuToPx(shape.position.width_emu),
    height: emuToPx(shape.position.height_emu),
    zIndex: shape.z_order + 1,
    overflow: "hidden",
  };

  const totalWidthEmu = table.column_widths_emu.reduce((a, b) => a + b, 0);

  // Build a grid of cells indexed by [row][col]
  const cellMap = new Map<string, TableCell>();
  table.cells.forEach((cell) => {
    cellMap.set(`${cell.row}-${cell.col}`, cell);
  });

  // Track which cells are covered by spans
  const covered = new Set<string>();
  table.cells.forEach((cell) => {
    for (let r = cell.row; r < cell.row + cell.row_span; r++) {
      for (let c = cell.col; c < cell.col + cell.col_span; c++) {
        if (r !== cell.row || c !== cell.col) {
          covered.add(`${r}-${c}`);
        }
      }
    }
  });

  return (
    <div style={containerStyle}>
      <table
        style={{
          width: "100%",
          height: "100%",
          borderCollapse: "collapse",
          tableLayout: "fixed",
        }}
      >
        <colgroup>
          {table.column_widths_emu.map((w, i) => (
            <col key={i} style={{ width: `${(w / totalWidthEmu) * 100}%` }} />
          ))}
        </colgroup>
        <tbody>
          {Array.from({ length: table.rows }, (_, rowIdx) => (
            <tr key={rowIdx}>
              {Array.from({ length: table.columns }, (_, colIdx) => {
                const key = `${rowIdx}-${colIdx}`;
                if (covered.has(key)) return null;

                const cell = cellMap.get(key);
                if (!cell) return <td key={colIdx} />;

                return <CellRenderer key={colIdx} cell={cell} />;
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function CellRenderer({ cell }: { cell: TableCell }) {
  const fillBg = cell.fill?.type === "solid" ? cell.fill.color : undefined;

  const style: CSSProperties = {
    backgroundColor: fillBg || undefined,
    verticalAlign: cell.vertical_alignment === "middle"
      ? "middle"
      : cell.vertical_alignment === "bottom"
        ? "bottom"
        : "top",
    padding: `${emuToPx(cell.margin_emu.top)}px ${emuToPx(cell.margin_emu.right)}px ${emuToPx(cell.margin_emu.bottom)}px ${emuToPx(cell.margin_emu.left)}px`,
    borderTop: `${cell.border.top.width_pt}pt solid ${cell.border.top.color}`,
    borderBottom: `${cell.border.bottom.width_pt}pt solid ${cell.border.bottom.color}`,
    borderLeft: `${cell.border.left.width_pt}pt solid ${cell.border.left.color}`,
    borderRight: `${cell.border.right.width_pt}pt solid ${cell.border.right.color}`,
    overflow: "hidden",
    wordBreak: "break-word",
  };

  return (
    <td
      rowSpan={cell.row_span > 1 ? cell.row_span : undefined}
      colSpan={cell.col_span > 1 ? cell.col_span : undefined}
      style={style}
    >
      {cell.text_body?.paragraphs?.map((para, i) => (
        <CellParagraph key={i} para={para} />
      ))}
    </td>
  );
}

function CellParagraph({ para }: { para: ParagraphData }) {
  const style: CSSProperties = {
    textAlign: (para.alignment as any) || "left",
    margin: 0,
    lineHeight: "1.3",
  };

  if (!para.runs.length) return <p style={style}>&nbsp;</p>;

  return (
    <p style={style}>
      {para.runs.map((run, j) => (
        <CellRun key={j} run={run} />
      ))}
    </p>
  );
}

function CellRun({ run }: { run: TextRun }) {
  const font = run.font;
  const style: CSSProperties = {
    fontFamily: font.name ? `"${font.name}", Calibri, sans-serif` : "Calibri, sans-serif",
    fontSize: font.size_pt ? `${font.size_pt}pt` : "10pt",
    fontWeight: font.bold ? "bold" : "normal",
    fontStyle: font.italic ? "italic" : "normal",
    color: font.color || undefined,
    textDecoration: font.underline ? "underline" : undefined,
  };

  return <span style={style}>{run.text}</span>;
}
