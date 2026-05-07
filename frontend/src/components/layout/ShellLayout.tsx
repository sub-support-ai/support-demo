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
  IconFileText,
  IconLogout,
  IconMessageCircle,
} from "@tabler/icons-react";
import { NavLink as RouterNavLink, Outlet, useLocation } from "react-router-dom";

import { useMe } from "../../api/auth";
import { useAuth } from "../../stores/auth";

export function ShellLayout() {
  const { token, logout } = useAuth();
  const { data: me } = useMe(Boolean(token));
  const location = useLocation();
  const isChatPage = location.pathname.startsWith("/chat");
  const requestsLabel =
    me?.role === "admin" || me?.role === "agent" ? "Запросы" : "Мои запросы";

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
          active={location.pathname.startsWith("/tickets")}
        />
      </AppShell.Navbar>

      <AppShell.Main className={`app-main${isChatPage ? " chat-main" : ""}`}>
        <Outlet />
      </AppShell.Main>
    </AppShell>
  );
}
