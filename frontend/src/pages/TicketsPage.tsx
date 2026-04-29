import { Alert, LoadingOverlay, Paper, SimpleGrid, Text, Title } from "@mantine/core";

import { getApiError } from "../api/client";
import { useTickets } from "../api/tickets";
import { TicketCard } from "../components/tickets/TicketCard";

export function TicketsPage() {
  const tickets = useTickets();

  return (
    <div className="content-page">
      <Paper className="tickets-panel" withBorder>
        <LoadingOverlay visible={tickets.isLoading} />
        <Title order={2} mb="xs">
          Мои тикеты
        </Title>
        <Text size="sm" c="dimmed" mb="md">
          Активные и отправленные обращения.
        </Text>
        {tickets.error && (
          <Alert color="red" variant="light" mb="md">
            {getApiError(tickets.error)}
          </Alert>
        )}
        {!tickets.data?.length && !tickets.isLoading ? (
          <div className="empty-state tickets">
            <Text fw={600}>Тикетов нет</Text>
          </div>
        ) : (
          <SimpleGrid cols={{ base: 1, md: 2 }} spacing="md">
            {tickets.data?.map((ticket) => (
              <TicketCard key={ticket.id} ticket={ticket} />
            ))}
          </SimpleGrid>
        )}
      </Paper>
    </div>
  );
}
