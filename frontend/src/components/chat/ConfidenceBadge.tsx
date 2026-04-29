import { Badge } from "@mantine/core";

export function ConfidenceBadge({ confidence }: { confidence?: number | null }) {
  if (confidence === null || confidence === undefined) {
    return null;
  }

  const percent = Math.round(confidence * 100);
  const color = confidence >= 0.8 ? "green" : confidence >= 0.6 ? "yellow" : "red";

  return (
    <Badge color={color} variant="light" size="sm">
      {percent}%
    </Badge>
  );
}
