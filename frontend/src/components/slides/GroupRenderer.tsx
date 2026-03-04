import type { CSSProperties } from "react";
import type { GroupShape } from "../../types/slide";
import { emuToPx } from "../../lib/slideUtils";
import ShapeRenderer from "./ShapeRenderer";

interface Props {
  shape: GroupShape;
  presentationId: number;
}

export default function GroupRenderer({ shape, presentationId }: Props) {
  const group = shape.group;

  const containerStyle: CSSProperties = {
    position: "absolute",
    left: emuToPx(shape.position.left_emu),
    top: emuToPx(shape.position.top_emu),
    width: emuToPx(shape.position.width_emu),
    height: emuToPx(shape.position.height_emu),
    zIndex: shape.z_order + 1,
    transform: shape.rotation_degrees ? `rotate(${shape.rotation_degrees}deg)` : undefined,
    overflow: "visible",
  };

  // Calculate scale factors for the group's internal coordinate space
  const scaleX = shape.position.width_emu / (group.child_extent_x_emu || shape.position.width_emu);
  const scaleY = shape.position.height_emu / (group.child_extent_y_emu || shape.position.height_emu);

  const innerStyle: CSSProperties = {
    position: "relative",
    width: emuToPx(group.child_extent_x_emu || shape.position.width_emu),
    height: emuToPx(group.child_extent_y_emu || shape.position.height_emu),
    transform: `scale(${scaleX}, ${scaleY})`,
    transformOrigin: "top left",
  };

  const sortedShapes = [...(group.shapes || [])].sort((a, b) => a.z_order - b.z_order);

  return (
    <div style={containerStyle}>
      <div style={innerStyle}>
        {sortedShapes.map((child) => (
          <ShapeRenderer key={child.shape_id} shape={child} presentationId={presentationId} />
        ))}
      </div>
    </div>
  );
}
