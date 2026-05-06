import {
  Alert,
  Button,
  Group,
  Select,
  Stack,
  Text,
  TextInput,
} from "@mantine/core";
import { IconAlertTriangle, IconArrowRight } from "@tabler/icons-react";
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
    value: "VPN не работает",
    label: "VPN не работает",
    affectedItem: "VPN",
    detailsLabel: "Ошибка VPN и когда началось",
    detailsPlaceholder: "Например: ошибка 809, началось сегодня утром, пробовал переподключиться",
  },
  {
    value: "Сброс пароля",
    label: "Сброс пароля",
    affectedItem: "Учетная запись",
    detailsLabel: "Система и логин",
    detailsPlaceholder: "Например: доменная учетная запись, login.petrov",
  },
  {
    value: "Сломано оборудование",
    label: "Сломано оборудование",
    affectedItem: "Оборудование",
    detailsLabel: "Устройство и инвентарный номер",
    detailsPlaceholder: "Например: ноутбук HP, инв. 1042, не включается",
  },
  {
    value: "HR-запрос",
    label: "HR-запрос",
    affectedItem: "HR",
    detailsLabel: "Тема HR-запроса",
    detailsPlaceholder: "Например: справка, отпуск, доступ к кадровому документу",
  },
  {
    value: "Финансовый запрос",
    label: "Финансовый запрос",
    affectedItem: "Финансы",
    detailsLabel: "Документ или операция",
    detailsPlaceholder: "Например: счет, акт, выплата, номер документа",
  },
  {
    value: "Другое",
    label: "Другое",
    affectedItem: "",
    detailsLabel: "Что именно нужно уточнить",
    detailsPlaceholder: "Опишите важные детали для специалиста",
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

  useEffect(() => {
    if (!contextDefaults) {
      return;
    }
    setRequesterName((current) => current || contextDefaults.requester_name);
    setRequesterEmail((current) => current || contextDefaults.requester_email);
    setOffice((current) => current || contextDefaults.office || null);
  }, [contextDefaults]);

  const officeOptions = useMemo(() => {
    const values = [
      ...(contextDefaults?.office_options ?? DEFAULT_OFFICE_OPTIONS),
      contextDefaults?.office ?? "",
    ];
    return toSelectOptions(values, "Другой офис");
  }, [contextDefaults]);

  const affectedItemOptions = useMemo(() => {
    return toSelectOptions(
      [
        ...(contextDefaults?.affected_item_options ?? DEFAULT_AFFECTED_ITEM_OPTIONS),
        ...REQUEST_TYPES.map((item) => item.affectedItem),
      ],
      "Другое",
    );
  }, [contextDefaults]);

  const selectedRequestType = REQUEST_TYPES.find(
    (item) => item.value === requestType,
  );

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
      request_type: requestType,
      request_details: requestDetails.trim(),
    };
  }, [
    affectedItem,
    customAffectedItem,
    customOffice,
    office,
    requestDetails,
    requestType,
    requesterEmail,
    requesterName,
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

  function handleRequestTypeChange(value: string | null) {
    setRequestType(value);
    const nextType = REQUEST_TYPES.find((item) => item.value === value);
    if (nextType?.affectedItem && !affectedItem) {
      setAffectedItem(nextType.affectedItem);
    }
  }

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
            Проблема и уже описанные действия попадут в запрос из истории
            диалога. Укажите, от кого запрос, где он возник и что именно
            затронуто.
          </Text>
        </div>

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
            label="Тип запроса"
            data={REQUEST_TYPES}
            value={requestType}
            placeholder="Выберите сценарий"
            allowDeselect={false}
            required
            onChange={handleRequestTypeChange}
          />
          <TextInput
            label={selectedRequestType?.detailsLabel ?? "Уточнение"}
            value={requestDetails}
            placeholder={selectedRequestType?.detailsPlaceholder}
            required
            onChange={(event) => setRequestDetails(event.currentTarget.value)}
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
