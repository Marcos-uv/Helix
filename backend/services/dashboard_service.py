import re
from datetime import datetime
from pathlib import Path

from backend.core.obsidian_service import HELIX_BRAIN_DIR
from backend.core.system_monitor import run_automatic_pc_checkup


def is_dashboard_update_question(message: str) -> bool:
    text = message.lower().strip()

    keywords = [
        "atualize o dashboard",
        "atualizar o dashboard",
        "atualiza o dashboard",
        "atualize meu dashboard",
        "atualizar meu dashboard",
        "atualiza meu dashboard",
        "sincronize o dashboard",
        "sincronizar o dashboard",
        "sincroniza o dashboard",
        "regenere o dashboard",
        "regenerar o dashboard",
        "dashboard do obsidian",
        "dashboard helix",
        "atualize o painel",
        "atualizar o painel",
        "atualiza o painel",
        "painel do helix",
    ]

    return any(keyword in text for keyword in keywords)


def update_helix_dashboard(checkup: dict | None = None) -> Path | None:
    try:
        dashboard_path = HELIX_BRAIN_DIR / "Dashboard Helix.md"
        dashboard_path.parent.mkdir(parents=True, exist_ok=True)

        now = datetime.now()

        if checkup is None:
            checkup = run_automatic_pc_checkup(
                drive_path="C:/",
                low_free_space_gb=30,
            )

        metrics = checkup.get("metrics", {})
        cpu = metrics.get("cpu", {})
        memory = metrics.get("memory", {})
        disk = metrics.get("disk", {})

        alerts = checkup.get("alerts", [])
        recommendations = checkup.get("recommendations", [])
        next_steps = checkup.get("next_steps", [])
        storage_findings = checkup.get("storage_findings", [])

        auto_block = f"""<!-- HELIX_AUTO_STATUS_START -->

## 🖥️ Status automático do PC

> Última atualização: **{now:%d/%m/%Y %H:%M:%S}**  
> Gerado automaticamente pelo Helix.

### Estado geral

- **Status:** `{checkup.get("status")}`
- **Resumo:** {checkup.get("summary")}
- **Modo:** `{checkup.get("mode")}`

### Uso atual

- **CPU:** {cpu.get("percent")}%
- **RAM:** {memory.get("percent")}% — {memory.get("used_gb")} GB usados de {memory.get("total_gb")} GB
- **Disco C:** {disk.get("percent")}% usado — {disk.get("free_gb")} GB livres

### Alertas

"""

        if alerts:
            for alert in alerts:
                auto_block += f"- {alert}\n"
        else:
            auto_block += "- Nenhum alerta importante no momento.\n"

        auto_block += "\n### Pontos de armazenamento\n\n"

        if storage_findings:
            for item in storage_findings[:8]:
                auto_block += (
                    f"- `{item.get('path')}` — {item.get('size_gb')} GB "
                    f"| risco: `{item.get('risk')}` "
                    f"| categoria: `{item.get('category')}`\n"
                )
        else:
            auto_block += "- Nenhum ponto crítico de armazenamento encontrado.\n"

        auto_block += "\n### Recomendações\n\n"

        if recommendations:
            for recommendation in recommendations[:8]:
                auto_block += f"- {recommendation}\n"
        else:
            auto_block += "- Nenhuma recomendação crítica no momento.\n"

        auto_block += "\n### Próximos passos\n\n"

        if next_steps:
            for step in next_steps:
                auto_block += f"- [ ] {step}\n"
        else:
            auto_block += "- [ ] Nenhum próximo passo crítico.\n"

        auto_block += "\n<!-- HELIX_AUTO_STATUS_END -->\n"

        if dashboard_path.exists():
            current_content = dashboard_path.read_text(encoding="utf-8")
        else:
            current_content = "# 🧠 Dashboard Helix\n\nPainel principal do sistema Helix.\n\n"

        pattern = re.compile(
            r"<!-- HELIX_AUTO_STATUS_START -->.*?<!-- HELIX_AUTO_STATUS_END -->",
            re.DOTALL,
        )

        if pattern.search(current_content):
            new_content = pattern.sub(lambda _: auto_block.strip(), current_content)
        else:
            new_content = current_content.rstrip() + "\n\n" + auto_block.strip() + "\n"

        dashboard_path.write_text(new_content, encoding="utf-8")

        return dashboard_path

    except Exception as exc:
        print(f"Erro ao atualizar Dashboard Helix: {exc}")
        return None


def build_dashboard_update_response() -> str:
    checkup = run_automatic_pc_checkup(
        drive_path="C:/",
        low_free_space_gb=30,
    )

    dashboard_path = update_helix_dashboard(checkup)

    if not dashboard_path:
        return (
            "Tentei atualizar o Dashboard Helix, mas algo falhou no caminho.\n\n"
            "Nada foi apagado ou alterado fora da tentativa de escrita do dashboard. "
            "Verifique se o Obsidian Vault está acessível e se o arquivo não está bloqueado."
        )

    metrics = checkup.get("metrics", {})
    cpu = metrics.get("cpu", {})
    memory = metrics.get("memory", {})
    disk = metrics.get("disk", {})

    response = "Dashboard Helix atualizado no Obsidian.\n\n"
    response += f"Arquivo: `{dashboard_path}`\n\n"

    response += "Resumo do check-up usado no dashboard:\n"
    response += f"- Status: {checkup.get('status')}\n"
    response += f"- Resumo: {checkup.get('summary')}\n"
    response += f"- CPU: {cpu.get('percent')}%\n"
    response += (
        f"- RAM: {memory.get('percent')}% "
        f"({memory.get('used_gb')} GB de {memory.get('total_gb')} GB)\n"
    )
    response += (
        f"- Disco C: {disk.get('percent')}% usado "
        f"({disk.get('free_gb')} GB livres)\n\n"
    )

    response += (
        "Atualizei só o bloco automático entre os marcadores do Helix. "
        "O resto do dashboard ficou intacto. Cirurgia limpa, sem drama."
    )

    return response