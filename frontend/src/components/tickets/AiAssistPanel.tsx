import {
  Anchor,
  Badge,
  Box,
  Button,
  Divider,
  Group,
  Loader,
  Stack,
  Text,
} from "@mantine/core";
import { IconCopy, IconExternalLink, IconSparkles } from "@tabler/icons-react";

import { useTicketAiAssist } from "../../api/tickets";
import type { SimilarTicket } from "../../api/types";

function formatDate(iso: string | null): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleDateString("ru-RU", {
    day: "2-digit",
    month: "short",
    year: "numeric",
  });
}

function SummaryBlock({ text }: { text: string }) {
  return (
    <Stack gap={4}>
      {text.split("\n").map((line, i) => {
        const bold = line.match(/^\*\*(.+?):\*\*\s*(.*)/);
        if (bold) {
          return (
            <Text key={i} size="sm">
              <Text span fw={600}>{bold[1]}:</Text> {bold[2]}
            </Text>
          );
        }
        return <Text key={i} size="sm">{line}</Text>;
      })}
    </Stack>
  );
}

function SimilarTicketRow({ ticket }: { ticket: SimilarTicket }) {
  return (
    <Group gap="xs" wrap="nowrap">
      <IconExternalLink size={12} style={{ flexShrink: 0, color: "var(--mantine-color-dimmed)" }} />
      <Box style={{ flex: 1, minWidth: 0 }}>
        <Text size="xs" lineClamp={1} title={ticket.title}>
          #{ticket.id} {ticket.title}
        </Text>
        <Text size="xs" c="dimmed">
          {[ticket.ai_category, formatDate(ticket.resolved_at)].filter(Boolean).join(" · ")}
        </Text>
      </Box>
    </Group>
  );
}

interface Props {
  ticketId: number;
  onInsertDraft: (text: string) => void;
}

export function AiAssistPanel({ ticketId, onInsertDraft }: Props) {
  const assist = useTicketAiAssist(ticketId, true);

  if (assist.isLoading) {
    return (
      <Group gap="xs" py="xs">
        <Loader size={14} />
        <Text size="xs" c="dimmed">Загрузка AI-подсказок…</Text>
      </Group>
    );
  }

  if (!assist.data) return null;

  const { summary, ai_response_draft, similar_tickets } = assist.data;
  const hasContent = summary || ai_response_draft || similar_tickets.length > 0;

  if (!hasContent) {
    return (
      <Text size="xs" c="dimmed" py="xs">
        AI-данных по этому тикету пока нет.
      </Text>
    );
  }

  return (
    <Stack gap="sm">
      {summary && (
        <Box>
          <Text size="xs" fw={600} c="dimmed" mb={4} tt="uppercase">
            Резюме
          </Text>
          <SummaryBlock text={summary} />
        </Box>
      )}

      {ai_response_draft && (
        <>
          {summary && <Divider />}
          <Box>
            <Group justify="space-between" mb={4}>
              <Text size="xs" fw={600} c="dimmed" tt="uppercase">
                Черновик ответа AI
              </Text>
              <Button
                size="xs"
                variant="subtle"
                leftSection={<IconCopy size={12} />}
                onClick={() => onInsertDraft(ai_response_draft)}
              >
                Вставить
              </Button>
            </Group>
            <Text size="sm" c="dimmed" style={{ whiteSpace: "pre-wrap" }}>
              {ai_response_draft}
            </Text>
          </Box>
        </>
      )}

      {similar_tickets.length > 0 && (
        <>
          {(summary || ai_response_draft) && <Divider />}
          <Box>
            <Group gap="xs" mb={6}>
              <Text size="xs" fw={600} c="dimmed" tt="uppercase">
                Похожие решённые
              </Text>
              <Badge size="xs" variant="light" color="gray">
                {similar_tickets.length}
              </Badge>
            </Group>
            <Stack gap={6}>
              {similar_tickets.map((t) => (
                <SimilarTicketRow key={t.id} ticket={t} />
              ))}
            </Stack>
          </Box>
        </>
      )}
    </Stack>
  );
}
