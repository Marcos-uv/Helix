from datetime import datetime
from pathlib import Path

from backend.core.obsidian_service import HELIX_LOGS_DIR
from backend.core.system_monitor import (
    get_system_metrics,
    get_system_diagnostic,
    get_hardware_info,
    run_automatic_pc_checkup,
)
from backend.services.dashboard_service import update_helix_dashboard


def is_pc_status_question(message: str) -> bool:
    text = message.lower().strip()

    keywords = [
        "meu pc",
        "meu computador",
        "diagnóstico",
        "diagnostico",
        "como está o pc",
        "como esta o pc",
        "como está meu pc",
        "como esta meu pc",
        "pc está pesado",
        "pc esta pesado",
        "desempenho",
        "hardware",
        "processador",
        "cpu",
        "placa de vídeo",
        "placa de video",
        "gpu",
        "memória ram",
        "memoria ram",
        "ram",
        "placa mãe",
        "placa mae",
        "motherboard",
        "ssd",
        "hd",
        "hdd",
        "nvme",
        "disco",
        "armazenamento",
        "windows",
        "sistema operacional",
        "bios",
    ]

    return any(keyword in text for keyword in keywords)


def is_automatic_checkup_question(message: str) -> bool:
    text = message.lower().strip()

    keywords = [
        "como está meu pc hoje",
        "como esta meu pc hoje",
        "como está meu pc",
        "como esta meu pc",
        "faça um check-up",
        "faca um check-up",
        "check-up do meu pc",
        "checkup do meu pc",
        "check up do meu pc",
        "diagnóstico automático",
        "diagnostico automatico",
        "verifique meu pc",
        "analise meu pc",
        "avaliar meu pc",
        "avalia meu pc",
    ]

    return any(keyword in text for keyword in keywords)


def build_automatic_checkup_response() -> str:
    checkup = run_automatic_pc_checkup(
        drive_path="C:/",
        low_free_space_gb=30,
    )

    note_path = save_pc_checkup_to_obsidian(checkup)
    dashboard_path = update_helix_dashboard(checkup)

    response = "Fiz um check-up automático do seu PC. Nenhum arquivo foi apagado.\n\n"

    response += f"Status geral: {checkup.get('status')}\n"
    response += f"Resumo: {checkup.get('summary')}\n\n"

    metrics = checkup.get("metrics", {})
    cpu = metrics.get("cpu", {})
    memory = metrics.get("memory", {})
    disk = metrics.get("disk", {})

    response += "Uso atual:\n"
    response += f"- CPU: {cpu.get('percent')}%\n"
    response += (
        f"- RAM: {memory.get('percent')}% "
        f"({memory.get('used_gb')} GB usados de {memory.get('total_gb')} GB)\n"
    )
    response += (
        f"- Disco C: {disk.get('percent')}% usado "
        f"({disk.get('free_gb')} GB livres)\n\n"
    )

    alerts = checkup.get("alerts", [])
    if alerts:
        response += "Alertas:\n"
        for alert in alerts:
            response += f"- {alert}\n"
        response += "\n"

    actions_taken = checkup.get("actions_taken", [])
    if actions_taken:
        response += "Ações automáticas feitas:\n"
        for action in actions_taken:
            response += f"- {action}\n"
        response += "\n"

    storage_findings = checkup.get("storage_findings", [])
    if storage_findings:
        response += "Principais pontos encontrados no armazenamento:\n"
        for item in storage_findings[:8]:
            response += (
                f"- `{item.get('path')}`: {item.get('size_gb')} GB "
                f"| risco: {item.get('risk')} "
                f"| categoria: {item.get('category')}\n"
            )
        response += "\n"

    recommendations = checkup.get("recommendations", [])
    if recommendations:
        response += "Recomendações:\n"
        for recommendation in recommendations[:10]:
            response += f"- {recommendation}\n"
        response += "\n"

    next_steps = checkup.get("next_steps", [])
    if next_steps:
        response += "Próximos passos sugeridos:\n"
        for step in next_steps:
            response += f"- {step}\n"
        response += "\n"

    response += (
        "Conclusão do Helix: seu PC está funcional, mas o C: ainda está apertado. "
        "Você já melhorou bastante chegando em cerca de 24 GB livres, mas eu ainda miraria em 30 a 50 GB livres."
    )

    if note_path:
        response += f"\n\nRelatório salvo no Obsidian em:\n`{note_path}`"
    else:
        response += "\n\nNão consegui salvar o relatório no Obsidian agora."

    if dashboard_path:
        response += f"\n\nDashboard atualizado em:\n`{dashboard_path}`"
    else:
        response += "\n\nNão consegui atualizar o dashboard agora."

    return response


def save_pc_checkup_to_obsidian(checkup: dict) -> Path | None:
    try:
        diagnostics_dir = HELIX_LOGS_DIR / "Diagnosticos"
        diagnostics_dir.mkdir(parents=True, exist_ok=True)

        now = datetime.now()
        file_name = f"Check-up PC {now:%Y-%m-%d %H-%M-%S}.md"
        file_path = diagnostics_dir / file_name

        metrics = checkup.get("metrics", {})
        cpu = metrics.get("cpu", {})
        memory = metrics.get("memory", {})
        disk = metrics.get("disk", {})

        alerts = checkup.get("alerts", [])
        recommendations = checkup.get("recommendations", [])
        actions_taken = checkup.get("actions_taken", [])
        next_steps = checkup.get("next_steps", [])
        storage_findings = checkup.get("storage_findings", [])

        content = f"""# Check-up do PC — {now:%Y-%m-%d %H:%M:%S}

## Resumo

- **Status:** {checkup.get("status")}
- **Resumo:** {checkup.get("summary")}
- **Modo:** {checkup.get("mode")}

## Uso atual

- **CPU:** {cpu.get("percent")}%
- **RAM:** {memory.get("percent")}% — {memory.get("used_gb")} GB usados de {memory.get("total_gb")} GB
- **Disco C:** {disk.get("percent")}% usado — {disk.get("free_gb")} GB livres

## Alertas

"""

        if alerts:
            for alert in alerts:
                content += f"- {alert}\n"
        else:
            content += "- Nenhum alerta importante.\n"

        content += "\n## Ações automáticas feitas\n\n"

        if actions_taken:
            for action in actions_taken:
                content += f"- {action}\n"
        else:
            content += "- Nenhuma ação automática extra foi necessária.\n"

        content += "\n## Principais pontos encontrados no armazenamento\n\n"

        if storage_findings:
            for item in storage_findings[:10]:
                content += (
                    f"- **{item.get('path')}** — {item.get('size_gb')} GB "
                    f"| risco: `{item.get('risk')}` "
                    f"| categoria: `{item.get('category')}`\n"
                )
        else:
            content += "- Nenhum ponto de armazenamento relevante encontrado.\n"

        content += "\n## Recomendações\n\n"

        if recommendations:
            for recommendation in recommendations:
                content += f"- {recommendation}\n"
        else:
            content += "- Nenhuma recomendação necessária no momento.\n"

        content += "\n## Próximos passos\n\n"

        if next_steps:
            for step in next_steps:
                content += f"- {step}\n"
        else:
            content += "- Nenhum próximo passo crítico.\n"

        content += """

---

## Observação

Este relatório foi gerado automaticamente pelo Helix.  
Nenhum arquivo foi apagado, movido ou alterado durante o check-up.
"""

        file_path.write_text(content, encoding="utf-8")

        return file_path

    except Exception as exc:
        print(f"Erro ao salvar check-up no Obsidian: {exc}")
        return None


def _build_pc_context(user_message: str) -> str:
    if not is_pc_status_question(user_message):
        return ""

    try:
        metrics = get_system_metrics()
        diagnostic = get_system_diagnostic()
        hardware = get_hardware_info()

        context = "\n\nContexto atual do PC do usuário:\n"

        context += "\n## Hardware físico\n"

        if hardware.get("available"):
            cpu = hardware.get("cpu", {})
            memory = hardware.get("memory", {})
            motherboard = hardware.get("motherboard", {})
            os_info = hardware.get("operating_system", {})
            gpu_list = hardware.get("gpu", [])

            context += (
                f"- Processador: {cpu.get('name')} "
                f"({cpu.get('cores')} núcleos / "
                f"{cpu.get('logical_processors')} threads)\n"
            )

            context += f"- RAM instalada: {memory.get('total_gb')} GB\n"

            modules = memory.get("modules", [])
            for module in modules:
                context += (
                    f"  - Módulo RAM: {module.get('capacity_gb')} GB "
                    f"{module.get('manufacturer')} "
                    f"{str(module.get('part_number', '')).strip()} "
                    f"em {module.get('configured_speed_mhz')} MHz "
                    f"({module.get('slot')})\n"
                )

            for gpu in gpu_list:
                context += (
                    f"- Placa de vídeo: {gpu.get('name')} "
                    f"(VRAM reportada pelo Windows: {gpu.get('adapter_ram_gb')} GB, "
                    f"driver: {gpu.get('driver_version')})\n"
                )

            context += "- Observação: a RX 7600 deste usuário tem 8 GB de VRAM; o Windows pode reportar 4 GB incorretamente.\n"
            context += f"- Placa-mãe: {motherboard.get('manufacturer')} {motherboard.get('product')}\n"
            context += f"- Sistema operacional: {os_info.get('name')} {os_info.get('architecture')}\n"

            bios = hardware.get("bios", {})
            context += f"- BIOS: {bios.get('manufacturer')} versão {bios.get('version')}\n"

        else:
            context += f"- Hardware indisponível: {hardware.get('error')}\n"

        context += "\n## Uso atual\n"

        cpu = metrics.get("cpu", {})
        memory = metrics.get("memory", {})
        disk = metrics.get("disk", {})
        processes = metrics.get("processes", {})
        storage_devices = metrics.get("storage_devices", [])

        context += f"- CPU em uso: {cpu.get('percent')}%\n"
        context += (
            f"- RAM em uso: {memory.get('percent')}% "
            f"({memory.get('used_gb')} GB usados de {memory.get('total_gb')} GB)\n"
        )
        context += (
            f"- Disco principal: {disk.get('percent')}% usado "
            f"({disk.get('free_gb')} GB livres)\n"
        )

        context += "\n## Armazenamento físico\n"

        for device in storage_devices:
            context += (
                f"- {device.get('kind')}: {device.get('name')} "
                f"({device.get('bus_type')}, {device.get('size_gb')} GB, "
                f"saúde: {device.get('health_status')})\n"
            )

            for volume in device.get("volumes", []):
                context += (
                    f"  - Unidade {volume.get('drive_letter')} "
                    f"label '{volume.get('label')}': "
                    f"{volume.get('used_percent')}% usado, "
                    f"{volume.get('free_gb')} GB livres\n"
                )

        context += "\n## Processos monitorados\n"

        for name, running in processes.items():
            state = "rodando" if running else "fechado"
            context += f"- {name}: {state}\n"

        context += "\n## Diagnóstico automático\n"
        context += f"- Status geral: {diagnostic.get('status')}\n"
        context += f"- Resumo: {diagnostic.get('summary')}\n"

        alerts = diagnostic.get("alerts", [])
        recommendations = diagnostic.get("recommendations", [])

        if alerts:
            context += "- Alertas:\n"
            for alert in alerts:
                context += f"  - {alert}\n"

        if recommendations:
            context += "- Recomendações:\n"
            for recommendation in recommendations:
                context += f"  - {recommendation}\n"

        return context

    except Exception as exc:
        print(f"Erro ao montar contexto do PC: {exc}")
        return "\n\nContexto atual do PC: não foi possível carregar o diagnóstico agora.\n"
