import { Anchor, Collapse, Group, Text, UnstyledButton } from "@mantine/core";
import { IconChevronDown, IconChevronRight, IconFileText } from "@tabler/icons-react";
import { useDisclosure } from "@mantine/hooks";

import type { Source } from "../../api/types";

export function Sources({ sources }: { sources?: Source[] | null }) {
  const [opened, { toggle }] = useDisclosure(false);

  if (!sources?.length) {
    return null;
  }

  return (
    <div className="sources">
      <UnstyledButton onClick={toggle} className="sources-toggle">
        <Group gap={6}>
          {opened ? <IconChevronDown size={14} /> : <IconChevronRight size={14} />}
          <Text size="xs" fw={600}>
            Источники ({sources.length})
          </Text>
        </Group>
      </UnstyledButton>
      <Collapse in={opened}>
        <div className="sources-list">
          {sources.map((source, index) => (
            <Group key={`${source.title}-${index}`} gap={8} wrap="nowrap">
              <IconFileText size={14} />
              {source.url ? (
                <Anchor href={source.url} target="_blank" size="xs">
                  {source.title}
                </Anchor>
              ) : (
                <Text size="xs">{source.title}</Text>
              )}
            </Group>
          ))}
        </div>
      </Collapse>
    </div>
  );
}
