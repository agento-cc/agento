from __future__ import annotations

from textual.widgets import Static


class FieldDetailPanel(Static):

    def __init__(self, **kwargs) -> None:
        super().__init__("Select a field to view details", **kwargs)

    def update_field(self, field) -> None:
        if field is None:
            self.update("Select a field to view details")
            return

        value_display = "****" if field.obscure else (field.value if field.value is not None else "")

        lines = [
            f"Path:   {field.path}",
            f"Label:  {field.label}",
            f"Type:   {field.field_type}",
            f"Source: {field.source}",
            f"Value:  {value_display}",
        ]

        if field.options:
            opts = ", ".join(f"{o['value']} ({o['label']})" for o in field.options)
            lines.append(f"Options: {opts}")

        if field.source == "env":
            lines.append("")
            lines.append("This value is set via environment variable")
        elif field.source == "db:inherited":
            lines.append("")
            lines.append("This value is inherited from a parent scope")

        self.update("\n".join(lines))
