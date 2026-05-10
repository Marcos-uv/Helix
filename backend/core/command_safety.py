DANGEROUS_ACTIONS = {
    "obsidian_delete",
    "obsidian_rename",
    "close",
    "delete",
    "remove",
    "move",
    "rename",
    "run",
    "execute",
    "shell",
    "cmd",
    "powershell",
}

MODERATE_ACTIONS = {
    "obsidian_append",
    "obsidian_note",
    "obsidian_hub",
    "obsidian_link",
}

SAFE_ACTIONS = {
    "open",
    "search",
    "obsidian_list",
    "obsidian_open_note",
    "obsidian_read",
    "obsidian_search",
    "obsidian_restore",
}


def check_command_safety(action: str, target: str) -> dict:
    action = (action or "").lower().strip()
    target = (target or "").strip()

    if not action:
        return {
            "allowed": False,
            "requires_confirmation": False,
            "risk_level": "unknown",
            "reason": "Ação vazia ou inválida.",
        }

    if action in SAFE_ACTIONS:
        return {
            "allowed": True,
            "requires_confirmation": False,
            "risk_level": "low",
            "reason": "Comando considerado seguro.",
        }

    if action in MODERATE_ACTIONS:
        return {
            "allowed": True,
            "requires_confirmation": False,
            "risk_level": "medium",
            "reason": "Comando modifica ou cria conteúdo, mas não parece destrutivo.",
        }

    if action in DANGEROUS_ACTIONS:
        return {
            "allowed": False,
            "requires_confirmation": True,
            "risk_level": "high",
            "reason": "Comando pode fechar programas, apagar, mover, renomear ou alterar dados importantes.",
        }

    return {
        "allowed": False,
        "requires_confirmation": True,
        "risk_level": "unknown",
        "reason": "Ação desconhecida. Confirmação necessária por segurança.",
    }


def build_confirmation_message(action: str, target: str, safety: dict) -> str:
    return (
        "Esse comando precisa de confirmação antes de executar.\n\n"
        f"- Ação: `{action}`\n"
        f"- Alvo: `{target}`\n"
        f"- Risco: `{safety.get('risk_level')}`\n"
        f"- Motivo: {safety.get('reason')}\n\n"
        "Por segurança, confirme manualmente antes de prosseguir."
    )