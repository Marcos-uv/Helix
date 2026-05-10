import re

from backend.core.system_monitor import (
    scan_storage_usage,
    scan_full_drive_exhaustive,
    scan_specific_folder_audit,
)


def is_storage_cleanup_question(message: str) -> bool:
    text = message.lower().strip()

    keywords = [
        "liberar espaço",
        "liberar espaco",
        "limpar o c",
        "limpar c:",
        "limpar disco",
        "espaço no c",
        "espaco no c",
        "c: cheio",
        "disco c cheio",
        "ocupando espaço",
        "ocupando espaco",
        "arquivos grandes",
        "pastas grandes",
        "onde posso liberar",
        "o que posso apagar",
        "o que posso mover",
    ]

    return any(keyword in text for keyword in keywords)


def _build_storage_scan_context(user_message: str) -> str:
    if not is_storage_cleanup_question(user_message):
        return ""

    try:
        scan = scan_storage_usage()

        context = "\n\nContexto do scanner seguro de armazenamento:\n"
        context += "- Modo: apenas análise. Nenhum arquivo foi apagado.\n"
        context += f"- Total escaneado: {scan.get('total_scanned_gb')} GB\n"

        folders = scan.get("folders", [])

        if folders:
            context += "\nPastas analisadas, ordenadas por tamanho:\n"

            for folder in folders:
                context += (
                    f"- {folder.get('name')}: "
                    f"{folder.get('size_gb')} GB | "
                    f"risco: {folder.get('risk')} | "
                    f"categoria: {folder.get('category')} | "
                    f"sugestão: {folder.get('suggestion')} | "
                    f"caminho: {folder.get('path')}\n"
                )

        alerts = scan.get("alerts", [])
        recommendations = scan.get("recommendations", [])

        if alerts:
            context += "\nAlertas do scanner:\n"
            for alert in alerts:
                context += f"- {alert}\n"

        if recommendations:
            context += "\nRecomendações do scanner:\n"
            for recommendation in recommendations:
                context += f"- {recommendation}\n"

        context += (
            "\nInstrução para o Helix: responda com base nesse scanner. "
            "Não diga para apagar arquivos de sistema. "
            "Explique o que é mais seguro revisar, mover ou limpar manualmente. "
            "Sempre peça confirmação antes de qualquer ação destrutiva."
        )

        return context

    except Exception as exc:
        print(f"Erro ao montar contexto de armazenamento: {exc}")
        return "\n\nContexto de armazenamento: não foi possível executar o scanner agora.\n"


def build_storage_scan_response() -> str:
    scan = scan_storage_usage()

    folders = scan.get("folders", [])
    alerts = scan.get("alerts", [])
    recommendations = scan.get("recommendations", [])

    response = "Fiz um scanner seguro do armazenamento. Nada foi apagado.\n\n"

    response += f"Total analisado nas pastas principais: {scan.get('total_scanned_gb')} GB.\n\n"

    if folders:
        response += "Pastas que mais chamaram atenção:\n"

        for folder in folders[:7]:
            exists = folder.get("exists")

            if not exists:
                continue

            response += (
                f"- {folder.get('name')}: {folder.get('size_gb')} GB "
                f"| risco: {folder.get('risk')} "
                f"| categoria: {folder.get('category')}\n"
                f"  Caminho: {folder.get('path')}\n"
                f"  Sugestão: {folder.get('suggestion')}\n"
            )

    if alerts:
        response += "\nAlertas encontrados:\n"

        for alert in alerts:
            response += f"- {alert}\n"

    if recommendations:
        response += "\nRecomendações seguras:\n"

        for recommendation in recommendations:
            response += f"- {recommendation}\n"

    response += (
        "\nMinha sugestão: comece revisando as pastas de baixo risco, como Downloads, "
        "Desktop, Vídeos, Imagens e documentos pessoais. Evite apagar manualmente "
        "pastas do Windows, Program Files ou arquivos de sistema.\n\n"
        "Posso te ajudar a montar uma lista do que revisar primeiro, mas não vou apagar nada sem confirmação."
    )

    return response


def is_full_storage_audit_question(message: str) -> bool:
    text = message.lower().strip()

    keywords = [
        "avaliação completa do armazenamento",
        "avaliacao completa do armazenamento",
        "auditoria completa do armazenamento",
        "varredura completa do c",
        "scan completo do c",
        "scanner completo do c",
        "analisar tudo no c",
        "análise completa do c",
        "analise completa do c",
        "mapa completo do armazenamento",
        "diagnóstico completo do armazenamento",
        "diagnostico completo do armazenamento",
        "o que está ocupando meu c",
        "o que esta ocupando meu c",
    ]

    return any(keyword in text for keyword in keywords)


def build_full_storage_audit_response() -> str:
    audit = scan_full_drive_exhaustive(
        root_path="C:/",
        top_limit=20,
    )

    largest_folders = audit.get("largest_folders", [])
    largest_files = audit.get("largest_files", [])
    safe_candidates = audit.get("safe_candidates", [])
    risky_candidates = audit.get("risky_candidates", [])

    response = "Fiz uma auditoria completa do armazenamento do C:. Nenhum arquivo foi apagado.\n\n"

    response += "Resumo da varredura:\n"
    response += f"- Tempo: {audit.get('elapsed_seconds')} segundos\n"
    response += f"- Total acessível escaneado: {audit.get('total_scanned_gb')} GB\n"
    response += f"- Arquivos analisados: {audit.get('file_count')}\n"
    response += f"- Pastas analisadas: {audit.get('folder_count')}\n"
    response += f"- Itens ignorados por segurança/permissão: {audit.get('skipped_count')}\n\n"

    response += "Maiores pastas encontradas:\n"

    for folder in largest_folders[:10]:
        response += (
            f"- {folder.get('path')}: {folder.get('size_gb')} GB "
            f"| risco: {folder.get('risk')} "
            f"| categoria: {folder.get('category')}\n"
            f"  Sugestão: {folder.get('suggestion')}\n"
        )

    response += "\nMaiores arquivos encontrados:\n"

    for file_item in largest_files[:8]:
        response += (
            f"- {file_item.get('path')}: {file_item.get('size_gb')} GB "
            f"| risco: {file_item.get('risk')} "
            f"| categoria: {file_item.get('category')}\n"
            f"  Sugestão: {file_item.get('suggestion')}\n"
        )

    response += "\nAvaliação do Helix:\n"

    paths_text = " ".join(
        [item.get("path", "").lower() for item in largest_folders + largest_files]
    )

    if "appdata\\local\\amd\\dxccache" in paths_text:
        response += (
            "- O cache AMD DxcCache apareceu como um dos maiores pontos. "
            "Esse é um forte candidato para investigação/limpeza controlada.\n"
        )

    if "steam\\steamapps" in paths_text:
        response += (
            "- A Steam está ocupando bastante espaço. O caminho mais seguro é revisar jogos instalados "
            "e itens de workshop pela própria Steam, não apagando pastas manualmente.\n"
        )

    if "honkaiimpact3rd" in paths_text:
        response += (
            "- HonkaiImpact3rd apareceu como um dos maiores jogos. Se você não joga mais, "
            "desinstalar pela Steam pode liberar bastante espaço.\n"
        )

    if "hiberfil.sys" in paths_text:
        response += (
            "- O arquivo hiberfil.sys apareceu ocupando espaço. Se você não usa hibernação, "
            "dá para liberar espaço desativando a hibernação pelo Windows. Não apague esse arquivo manualmente.\n"
        )

    if "bluestacks_nxt" in paths_text:
        response += (
            "- O BlueStacks tem arquivos grandes de máquina virtual. Se você não usa mais, "
            "o melhor caminho é desinstalar/limpar pelo próprio BlueStacks ou pelo Windows.\n"
        )

    response += "\nCandidatos mais seguros para investigar primeiro:\n"

    for item in safe_candidates[:8]:
        response += (
            f"- {item.get('path')}: {item.get('size_gb')} GB "
            f"| {item.get('suggestion')}\n"
        )

    response += "\nÁreas que NÃO recomendo apagar manualmente:\n"

    for item in risky_candidates[:8]:
        response += (
            f"- {item.get('path')}: {item.get('size_gb')} GB "
            f"| motivo: {item.get('suggestion')}\n"
        )

    response += (
        "\nPrioridade recomendada:\n"
        "1. Revisar cache AMD DxcCache.\n"
        "2. Revisar jogos e workshop da Steam.\n"
        "3. Verificar se você usa hibernação; se não usa, podemos desativar com segurança guiada.\n"
        "4. Revisar BlueStacks se você não usa mais.\n"
        "5. Não mexer manualmente em Windows, Program Files, ProgramData ou Postgres.\n\n"
        "Posso te guiar na próxima etapa, começando pelo item mais seguro: cache AMD ou Steam."
    )

    return response


def extract_folder_path_from_message(message: str) -> str | None:
    text = message.strip()

    patterns = [
        r"analise a pasta (.+)$",
        r"analisa a pasta (.+)$",
        r"analisar a pasta (.+)$",
        r"avalie a pasta (.+)$",
        r"avaliar a pasta (.+)$",
        r"faça uma avaliação da pasta (.+)$",
        r"faca uma avaliacao da pasta (.+)$",
        r"escaneie a pasta (.+)$",
        r"escanear a pasta (.+)$",
        r"scanner da pasta (.+)$",
        r"scan da pasta (.+)$",
    ]

    lowered = text.lower()

    for pattern in patterns:
        match = re.match(pattern, lowered)

        if match:
            start_index = match.start(1)
            return text[start_index:].strip().strip('"').strip("'")

    path_match = re.search(r"[a-zA-Z]:\\[^<>|?*\n\r]+", text)

    if path_match:
        return path_match.group(0).strip().strip('"').strip("'")

    return None


def is_specific_folder_audit_question(message: str) -> bool:
    text = message.lower().strip()

    keywords = [
        "analise a pasta",
        "analisa a pasta",
        "analisar a pasta",
        "avalie a pasta",
        "avaliar a pasta",
        "avaliação da pasta",
        "avaliacao da pasta",
        "escaneie a pasta",
        "escanear a pasta",
        "scanner da pasta",
        "scan da pasta",
    ]

    if any(keyword in text for keyword in keywords):
        return True

    return extract_folder_path_from_message(message) is not None and (
        "pasta" in text or "analise" in text or "avalie" in text or "escaneie" in text
    )


def build_specific_folder_audit_response(folder_path: str) -> str:
    audit = scan_specific_folder_audit(
        folder_path=folder_path,
        top_limit=20,
    )

    if not audit.get("found"):
        return (
            "Não consegui analisar essa pasta.\n\n"
            f"Motivo: {audit.get('error')}\n\n"
            "Confere se o caminho está correto e tenta novamente."
        )

    largest_folders = audit.get("largest_folders", [])
    largest_files = audit.get("largest_files", [])
    safe_candidates = audit.get("safe_candidates", [])
    risky_candidates = audit.get("risky_candidates", [])

    response = "Fiz uma auditoria da pasta informada. Nenhum arquivo foi apagado.\n\n"

    response += "Resumo:\n"
    response += f"- Pasta: `{audit.get('path')}`\n"
    response += f"- Tamanho total: {audit.get('total_size_gb')} GB\n"
    response += f"- Arquivos analisados: {audit.get('file_count')}\n"
    response += f"- Pastas analisadas: {audit.get('folder_count')}\n"
    response += f"- Itens ignorados: {audit.get('skipped_count')}\n"
    response += f"- Risco da pasta: {audit.get('root_risk')}\n"
    response += f"- Categoria: {audit.get('root_category')}\n\n"

    response += f"Avaliação:\n{audit.get('summary')}\n\n"

    alerts = audit.get("alerts", [])
    if alerts:
        response += "Alertas:\n"
        for alert in alerts:
            response += f"- {alert}\n"
        response += "\n"

    response += "Maiores subpastas:\n"
    for folder in largest_folders[:8]:
        response += (
            f"- `{folder.get('path')}`: {folder.get('size_gb')} GB "
            f"| risco: {folder.get('risk')} "
            f"| categoria: {folder.get('category')}\n"
        )

    response += "\nMaiores arquivos:\n"
    for file_item in largest_files[:8]:
        response += (
            f"- `{file_item.get('path')}`: {file_item.get('size_gb')} GB "
            f"| risco: {file_item.get('risk')} "
            f"| categoria: {file_item.get('category')}\n"
        )

    if safe_candidates:
        response += "\nCandidatos mais seguros para investigar:\n"
        for item in safe_candidates[:6]:
            response += (
                f"- `{item.get('path')}`: {item.get('size_gb')} GB "
                f"| {item.get('suggestion')}\n"
            )

    if risky_candidates:
        response += "\nItens que eu NÃO recomendo apagar manualmente:\n"
        for item in risky_candidates[:6]:
            response += (
                f"- `{item.get('path')}`: {item.get('size_gb')} GB "
                f"| motivo: {item.get('suggestion')}\n"
            )

    recommendations = audit.get("recommendations", [])
    if recommendations:
        response += "\nRecomendações:\n"
        for recommendation in recommendations[:8]:
            response += f"- {recommendation}\n"

    response += (
        "\nConclusão: eu consigo mapear essa pasta e te dizer onde está o peso, "
        "mas qualquer limpeza deve ser feita com confirmação e respeitando o risco do caminho."
    )

    return response
