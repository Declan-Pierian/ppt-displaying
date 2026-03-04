export interface FontData {
  name: string | null;
  size_pt: number | null;
  bold: boolean;
  italic: boolean;
  underline: boolean;
  strikethrough: boolean;
  color: string | null;
}

export interface HyperlinkData {
  url: string;
}

export interface TextRun {
  text: string;
  font: FontData;
  hyperlink: HyperlinkData | null;
}

export interface BulletData {
  type: "char" | "number";
  char?: string;
  number_type?: string;
}

export interface ParagraphData {
  alignment: string;
  line_spacing_pt: number | null;
  space_before_pt: number | null;
  space_after_pt: number | null;
  level: number;
  bullet: BulletData | null;
  runs: TextRun[];
}

export interface TextBody {
  paragraphs: ParagraphData[];
}

export interface Position {
  left_emu: number;
  top_emu: number;
  width_emu: number;
  height_emu: number;
}

export interface FillData {
  type: "none" | "solid" | "gradient" | "pattern";
  color?: string;
  gradient_stops?: Array<{ color: string; position: number }>;
  angle_degrees?: number | null;
  fg_color?: string | null;
  bg_color?: string | null;
}

export interface BorderData {
  color: string | null;
  width_pt: number | null;
  dash_style: string | null;
}

export interface ShadowData {
  color?: string;
  blur_radius_emu?: number;
  dist_emu?: number;
  direction?: number;
  opacity?: number;
}

export interface ImageData {
  media_path: string | null;
  original_width_px: number | null;
  original_height_px: number | null;
  crop: {
    left: number;
    top: number;
    right: number;
    bottom: number;
  } | null;
  alt_text: string;
}

export interface CellBorder {
  top: { color: string; width_pt: number };
  bottom: { color: string; width_pt: number };
  left: { color: string; width_pt: number };
  right: { color: string; width_pt: number };
}

export interface TableCell {
  row: number;
  col: number;
  row_span: number;
  col_span: number;
  fill: FillData;
  border: CellBorder;
  vertical_alignment: string;
  margin_emu: { left: number; right: number; top: number; bottom: number };
  text_body: TextBody;
}

export interface TableData {
  rows: number;
  columns: number;
  column_widths_emu: number[];
  row_heights_emu: number[];
  cells: TableCell[];
}

export interface ChartSeriesData {
  name: string | null;
  values: number[];
}

export interface ChartData {
  chart_type: string;
  rendered_image_path: string | null;
  data: {
    categories: string[];
    series: ChartSeriesData[];
  };
  title: string | null;
}

export interface GroupData {
  child_offset_x_emu: number;
  child_offset_y_emu: number;
  child_extent_x_emu: number;
  child_extent_y_emu: number;
  shapes: ShapeData[];
}

export interface BaseShape {
  shape_id: string;
  position: Position;
  rotation_degrees: number;
  z_order: number;
}

export interface TextBoxShape extends BaseShape {
  shape_type: "text_box";
  fill: FillData;
  border: BorderData;
  text_body: TextBody;
  hyperlink: string | null;
}

export interface ImageShape extends BaseShape {
  shape_type: "image";
  image: ImageData;
  border: BorderData;
  hyperlink: string | null;
}

export interface TableShape extends BaseShape {
  shape_type: "table";
  table: TableData;
}

export interface ChartShape extends BaseShape {
  shape_type: "chart";
  chart: ChartData;
}

export interface AutoShapeData extends BaseShape {
  shape_type: "auto_shape";
  auto_shape_type: string;
  fill: FillData;
  border: BorderData;
  text_body: TextBody | null;
  hyperlink: string | null;
  shadow: ShadowData | null;
}

export interface GroupShape extends BaseShape {
  shape_type: "group";
  group: GroupData;
}

export interface MediaShapeData extends BaseShape {
  shape_type: "media";
  media: {
    media_path: string | null;
    media_type: string;
  };
}

export interface PlaceholderShape extends BaseShape {
  shape_type: "placeholder_unsupported";
  placeholder: {
    label: string;
    text: string;
  };
}

export type ShapeData =
  | TextBoxShape
  | ImageShape
  | TableShape
  | ChartShape
  | AutoShapeData
  | GroupShape
  | MediaShapeData
  | PlaceholderShape;

export interface BackgroundData {
  type: "none" | "solid" | "gradient" | "image" | "pattern";
  color?: string;
  gradient_stops?: Array<{ color: string; position: number }>;
  image_path?: string;
}

export interface SlideData {
  slide_index: number;
  slide_number: number;
  background: BackgroundData;
  shapes: ShapeData[];
  notes: string | null;
  slide_image?: string;
}

export interface PresentationData {
  presentation_id: number;
  title: string;
  slide_width_emu: number;
  slide_height_emu: number;
  slides: SlideData[];
}

export interface PresentationMeta {
  id: number;
  title: string;
  slide_count: number;
  slide_width_emu: number;
  slide_height_emu: number;
  created_at: string;
}

export interface PresentationAdminMeta extends PresentationMeta {
  original_filename: string;
  status: string;
  is_active: boolean;
  error_message: string | null;
  updated_at: string | null;
}

export interface UploadLog {
  id: number;
  presentation_id: number | null;
  original_filename: string;
  file_size_bytes: number;
  status: string;
  error_message: string | null;
  processing_time_ms: number | null;
  created_at: string;
}
