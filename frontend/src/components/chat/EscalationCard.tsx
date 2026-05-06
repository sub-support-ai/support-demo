import {
  Alert,
  Button,
  Group,
  Select,
  Stack,
  Text,
  TextInput,
} from "@mantine/core";
import { IconArrowRight, IconAlertTriangle } from "@tabler/icons-react";
import { useEffect, useMemo, useState } from "react";

import type { EscalationContext, RequestContextDefaults } from "../../api/types";

const OTHER_VALUE = "__other__";
const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]{2,}$/;

const DEFAULT_OFFICE_OPTIONS = ["Главный офис", "Склад", "Удаленно"];
const DEFAULT_AFFECTED_ITEM_OPTIONS = [
  "Рабочее место",
  "Ноутбук",
  "Принтер/МФУ",
  "VPN",
  "1C",
  "Почта",
];

const REQUEST_TYPES = [
  {
    value: "vpn_issue",
    label: "VPN не работает",
    affectedItem: "VPN",
    detailsLabel: "Ошибка VPN и когда началось",
    detailsPlaceholder: "Например: ошибка 809, началось сегодня утром, пробовал переподключиться",
  },
  {
    value: "password_reset",
    label: "Сброс пароля",
    affectedItem: "Учетная запись",
    detailsLabel: "Система и логин",
    detailsPlaceholder: "Например: корпоративная почта, логин ivanov.i",
  },
  {
    value: "hardware_broken",
    label: "Сломано оборудование",
    affectedItem: "Рабочее место",
    detailsLabel: "Устройство и инвентарный номер",
    detailsPlaceholder: "Например: ноутбук HP, инв. 1042, не включается",
  },
  {
    value: "hr_request",
    label: "HR-запрос",
    affectedItem: "Кадровый документ",
    detailsLabel: "Что нужно от HR",
    detailsPlaceholder: "Например: справка о доходах за 2025 год",
  },
  {
    value: "finance_request",
    label: "Финансовый запрос",
    affectedItem: "Оплата/документы",
    detailsLabel: "Что нужно от финансов",
    detailsPlaceholder: "Например: согласовать счет, номер договора, сумма",
  },
  {
    value: "other",
    label: "Другое",
    detailsLabel: "Уточнение",
    detailsPlaceholder: "Опишите, какой тип запроса нужно передать специалисту",
  },
];

function toSelectOptions(values: string[], otherLabel: string) {
  const uniqueValues = Array.from(new Set(values.filter(Boolean)));
  return [
    ...uniqueValues.map((value) => ({ value, label: value })),
    { value: OTHER_VALUE, label: otherLabel },
  ];
}

export function EscalationCard({
  contextDefaults,
  disabled,
  loading,
  onEscalate,
}: {
  contextDefaults?: RequestContextDefaults | null;
  disabled?: boolean;
  loading?: boolean;
  onEscalate: (context: EscalationContext) => void;
}) {
  const [requesterName, setRequesterName] = useState("");
  const [requesterEmail, setRequesterEmail] = useState("");
  const [office, setOffice] = useState<string | null>(null);
  const [customOffice, setCustomOffice] = useState("");
  const [affectedItem, setAffectedItem] = useState<string | null>(null);
  const [customAffectedItem, setCustomAffectedItem] = useState("");
  const [requestType, setRequestType] = useState<string | null>(null);
  const [requestDetails, setRequestDetails] = useState("");

  const selectedRequestType = useMemo(() => {
    return REQUEST_TYPES.find((item) => item.value === requestType) ?? null;
  }, [requestType]);

  useEffect(() => {
    if (!contextDefaults) {
      return;
    }
    setRequesterName((current) => current || contextDefaults.requester_name);
    setRequesterEmail((current) => current || contextDefaults.requester_email);
    setOffice((current) => current || contextDefaults.office || null);
  }, [contextDefaults]);

  useEffect(() => {
    if (selectedRequestType?.affectedItem) {
      setAffectedItem((current) => current || selectedRequestType.affectedItem || null);
    }
  }, [selectedRequestType]);

  const officeOptions = useMemo(() => {
    const values = [
      ...(contextDefaults?.office_options ?? DEFAULT_OFFICE_OPTIONS),
      contextDefaults?.office ?? "",
    ];
    return toSelectOptions(values, "Другой офис");
  }, [contextDefaults]);

  const affectedItemOptions = useMemo(() => {
    return toSelectOptions(
      contextDefaults?.affected_item_options ?? DEFAULT_AFFECTED_ITEM_OPTIONS,
      "Другое",
    );
  }, [contextDefaults]);

  const context = useMemo<EscalationContext>(() => {
    const resolvedOffice =
      office === OTHER_VALUE ? customOffice.trim() : office?.trim();
    const resolvedAffectedItem =
      affectedItem === OTHER_VALUE
        ? customAffectedItem.trim()
        : affectedItem?.trim();
    return {
      requester_name: requesterName.trim(),
      requester_email: requesterEmail.trim(),
      office: resolvedOffice || "",
      affected_item: resolvedAffectedItem || "",
      request_type: selectedRequestType?.label ?? null,
      request_details: requestDetails.trim() || null,
    };
  }, [
    affectedItem,
    customAffectedItem,
    customOffice,
    office,
    requesterEmail,
    requesterName,
    requestDetails,
    selectedRequestType,
  ]);

  const canSubmit = Boolean(
    context.requester_name &&
      context.requester_email &&
      EMAIL_RE.test(context.requester_email) &&
      context.office &&
      context.affected_item &&
      context.request_type &&
      context.request_details,
  );

  return (
    <Alert
      color="red"
      variant="light"
      icon={<IconAlertTriangle size={18} />}
      className="escalation-card"
    >
      <Stack gap="sm">
        <div>
          <Text fw={600}>Уточните данные для черновика</Text>
          <Text size="sm" c="dimmed">
            Проблема и уже описанные действия попадут в черновик запроса из истории диалога.
            Укажите, от кого запрос, где он возник и что именно затронуто.
          </Text>
        </div>

        <Group grow align="start">
          <Select
            label="Тип запроса"
            data={REQUEST_TYPES.map((item) => ({
              value: item.value,
              label: item.label,
            }))}
            value={requestType}
            placeholder="Выберите сценарий"
            allowDeselect={false}
            required
            onChange={setRequestType}
          />
          <TextInput
            label={selectedRequestType?.detailsLabel ?? "Уточнение"}
            value={requestDetails}
            maxLength={2000}
            required
            placeholder={selectedRequestType?.detailsPlaceholder}
            onChange={(event) => setRequestDetails(event.currentTarget.value)}
          />
        </Group>

        <Group grow align="start">
          <TextInput
            label="Заявитель"
            value={requesterName}
            maxLength={100}
            required
            onChange={(event) => setRequesterName(event.currentTarget.value)}
          />
          <TextInput
            label="Email заявителя"
            value={requesterEmail}
            maxLength={255}
            required
            error={
              requesterEmail && !EMAIL_RE.test(requesterEmail)
                ? "Проверьте email"
                : undefined
            }
            onChange={(event) => setRequesterEmail(event.currentTarget.value)}
          />
        </Group>

        <Group grow align="start">
          <Select
            label="Офис"
            data={officeOptions}
            value={office}
            placeholder="Выберите офис"
            allowDeselect={false}
            required
            onChange={(value) => setOffice(value)}
          />
          <Select
            label="Что затронуто"
            data={affectedItemOptions}
            value={affectedItem}
            placeholder="Выберите объект"
            allowDeselect={false}
            required
            onChange={(value) => setAffectedItem(value)}
          />
        </Group>

        {(office === OTHER_VALUE || affectedItem === OTHER_VALUE) && (
          <Group grow align="start">
            {office === OTHER_VALUE && (
              <TextInput
                label="Офис"
                value={customOffice}
                maxLength={100}
                required
                onChange={(event) => setCustomOffice(event.currentTarget.value)}
              />
            )}
            {affectedItem === OTHER_VALUE && (
              <TextInput
                label="Что затронуто"
                value={customAffectedItem}
                maxLength={150}
                required
                onChange={(event) =>
                  setCustomAffectedItem(event.currentTarget.value)
                }
              />
            )}
          </Group>
        )}

        <Group justify="flex-end">
          <Button
            color="red"
            rightSection={<IconArrowRight size={16} />}
            loading={loading}
            disabled={disabled || !canSubmit}
            onClick={() => onEscalate(context)}
          >
            Создать запрос
          </Button>
        </Group>
      </Stack>
    </Alert>
  );
}
