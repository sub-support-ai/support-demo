import { ActionIcon, Textarea } from "@mantine/core";
import { IconSend } from "@tabler/icons-react";
import { FormEvent, useState } from "react";

export function Composer({
  disabled,
  loading,
  onSend,
  value: controlledValue,
  onChange: onControlledChange,
}: {
  disabled?: boolean;
  loading?: boolean;
  onSend: (content: string) => Promise<void> | void;
  /** Controlled value — если передан, компонент работает в controlled-режиме. */
  value?: string;
  onChange?: (value: string) => void;
}) {
  const [internalValue, setInternalValue] = useState("");
  const isControlled = controlledValue !== undefined;
  const value = isControlled ? controlledValue : internalValue;

  function setValue(v: string) {
    if (isControlled) {
      onControlledChange?.(v);
    } else {
      setInternalValue(v);
    }
  }

  async function submit(event?: FormEvent) {
    event?.preventDefault();
    const content = value.trim();
    if (!content || disabled || loading) {
      return;
    }
    await onSend(content);
    setValue("");
  }

  return (
    <form className="composer" onSubmit={submit}>
      <Textarea
        classNames={{
          root: "composer-input-root",
          input: "composer-input",
        }}
        autosize
        minRows={1}
        maxRows={5}
        value={value}
        disabled={disabled}
        placeholder="Опишите проблему"
        onChange={(event) => setValue(event.currentTarget.value)}
        onKeyDown={(event) => {
          if (event.key === "Enter" && !event.shiftKey) {
            submit(event);
          }
        }}
      />
      <ActionIcon
        className="composer-send"
        type="submit"
        size={42}
        radius="sm"
        loading={loading}
        disabled={!value.trim() || disabled}
        aria-label="Отправить"
      >
        <IconSend size={20} />
      </ActionIcon>
    </form>
  );
}
