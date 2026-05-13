import {
  AppShell,
  Badge,
  Button,
  Group,
  NavLink,
  Text,
  Title,
} from "@mantine/core";
import {
  IconChartBar,
  IconDatabaseSearch,
  IconFileText,
  IconListCheck,
  IconLogout,
  IconMessageCircle,
} from "@tabler/icons-react";
import { NavLink as RouterNavLink, Outlet, useLocation } from "react-router-dom";

import { useMe } from "../../api/auth";
import { useTickets } from "../../api/tickets";
import { useAuth } from "../../stores/auth";

export function ShellLayout() {
  const { token, logout } = useAuth();
  const { data: me } = useMe(Boolean(token));
  const tickets = useTickets({
    enabled: Boolean(token),
    refetchInterval: 30000,
  });
  const location = useLocation();
  const isChatPage = location.pathname.startsWith("/chat");
  const isOperator = me?.role === "admin" || me?.role === "agent";
  const requestsLabel =
    isOperator ? "Запросы" : "Мои запросы";
  const activeTickets =
    tickets.data?.filter(
      (ticket) =>
        ticket.confirmed_by_user &&
        ["confirmed", "in_progress"].includes(ticket.status),
    ) ?? [];
  const overdueCount = activeTickets.filter((ticket) => ticket.is_sla_breached).length;
  const unassignedCount = activeTickets.filter((ticket) => ticket.agent_id == null).length;
  const newCount = activeTickets.filter((ticket) => ticket.status === "confirmed").length;
  const userDraftCount =
    tickets.data?.filter(
      (ticket) => ticket.status === "pending_user" && !ticket.confirmed_by_user,
    ).length ?? 0;
  const requestAlertCount = isOperator
    ? overdueCount || unassignedCount || newCount
    : userDraftCount;
  const requestAlertColor =
    overdueCount > 0 ? "red" : unassignedCount > 0 ? "orange" : "blue";

  return (
    <AppShell
      className={isChatPage ? "app-shell chat-shell" : "app-shell"}
      header={{ height: 58 }}
      navbar={{ width: 240, breakpoint: 0 }}
    >
      <AppShell.Header className="app-header">
        <Group justify="space-between" h="100%" px="md">
          <Group gap="sm">
            <Title order={3}>Точка поддержки</Title>
            {me?.role && <Badge variant="light">{me.role}</Badge>}
          </Group>
          <Group gap="sm">
            {me && (
              <Text size="sm" c="dimmed">
                {me.username}
              </Text>
            )}
            <Button
              variant="subtle"
              color="gray"
              leftSection={<IconLogout size={16} />}
              onClick={logout}
            >
              Выйти
            </Button>
          </Group>
        </Group>
      </AppShell.Header>

      <AppShell.Navbar p="sm">
        <NavLink
          component={RouterNavLink}
          to="/dashboard"
          label="Обзор"
          leftSection={<IconChartBar size={18} />}
          active={location.pathname.startsWith("/dashboard")}
        />
        <NavLink
          component={RouterNavLink}
          to="/chat"
          label="Чат"
          leftSection={<IconMessageCircle size={18} />}
          active={location.pathname.startsWith("/chat")}
        />
        <NavLink
          component={RouterNavLink}
          to="/tickets"
          label={requestsLabel}
          leftSection={<IconFileText size={18} />}
          rightSection={
            requestAlertCount > 0 ? (
              <Badge size="xs" color={requestAlertColor} variant="filled">
                {requestAlertCount}
              </Badge>
            ) : undefined
          }
          active={location.pathname.startsWith("/tickets")}
        />
        {me?.role === "admin" && (
          <NavLink
            component={RouterNavLink}
            to="/knowledge"
            label="База знаний"
            leftSection={<IconDatabaseSearch size={18} />}
            active={location.pathname.startsWith("/knowledge")}
          />
        )}
        {me?.role === "admin" && (
          <NavLink
            component={RouterNavLink}
            to="/jobs"
            label="Очереди"
            leftSection={<IconListCheck size={18} />}
            active={location.pathname.startsWith("/jobs")}
          />
        )}
      </AppShell.Navbar>

      <AppShell.Main className={`app-main${isChatPage ? " chat-main" : ""}`}>
        <Outlet />
      </AppShell.Main>
    </AppShell>
  );
}
