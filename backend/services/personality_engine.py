import re
import unicodedata


# ============================================================
# HELIX PERSONALITY ENGINE
# ------------------------------------------------------------
# Objetivo:
# - Dar continuidade social para a Helix.
# - Injetar piadas internas, modo amigo/demo, postura social e
#   "presença" no prompt sem enfiar tudo no SYSTEM_PROMPT fixo.
#
# Este módulo NÃO executa comandos.
# Este módulo NÃO acessa arquivos privados.
# Este módulo só gera contexto textual para o LLM.
# ============================================================


def normalize_text(text: str) -> str:
    text = str(text or "").lower().strip()
    text = unicodedata.normalize("NFD", text)
    text = "".join(char for char in text if unicodedata.category(char) != "Mn")
    text = re.sub(r"\s+", " ", text).strip()
    return text


def has_any(text: str, phrases: list[str] | set[str]) -> bool:
    normalized = normalize_text(text)
    return any(normalize_text(phrase) in normalized for phrase in phrases)


def _detect_friend_demo(user_message: str, user_name: str | None = None, tone_mode: str | None = None) -> bool:
    phrases = {
        "meu amigo vai testar",
        "meu amigo quer testar",
        "meu amigo vai usar",
        "vou mostrar pra um amigo",
        "vou mostrar para um amigo",
        "vou mostrar pro meu amigo",
        "meu amigo",
        "minha amiga",
        "meus amigos",
        "modo demo",
        "modo demonstração",
        "modo demonstracao",
        "modo amigo",
        "modo amigos",
    }

    if tone_mode == "friend_demo_mode":
        return True

    return has_any(user_message, phrases)


def _detect_helix_self_mockery(user_message: str) -> bool:
    phrases = {
        "voce vai funcionar",
        "você vai funcionar",
        "quando funcionar",
        "dia que voce funcionar",
        "dia que você funcionar",
        "sem mexer no codigo",
        "sem mexer no código",
        "sem mexer no codigo fonte",
        "sem mexer no código fonte",
        "arrumar voce",
        "arrumar você",
        "melhorar voce",
        "melhorar você",
        "deixar voce melhor",
        "deixar você melhor",
    }

    return has_any(user_message, phrases)


def _detect_bolacha_callback(user_message: str) -> bool:
    phrases = {
        "bolacha",
        "pacote",
        "se achando",
        "ultima bolacha",
        "última bolacha",
        "registro de apps",
        "app registry",
    }

    return has_any(user_message, phrases)


def _detect_sac_risk(user_message: str) -> bool:
    phrases = {
        "como posso ajudar",
        "assistente",
        "formal",
        "atendente",
        "suporte",
        "sac",
        "robótica",
        "robotica",
        "genérica",
        "generica",
    }

    return has_any(user_message, phrases)


def _detect_work_context(user_message: str, tone_mode: str | None = None) -> bool:
    if tone_mode == "work_mode":
        return True

    phrases = {
        "codigo",
        "código",
        "backend",
        "frontend",
        "fastapi",
        "postgres",
        "postgresql",
        "obsidian",
        "uvicorn",
        "terminal",
        "powershell",
        "traceback",
        "erro",
        "bug",
        "função",
        "funcao",
        "classe",
        "arquivo",
        "rota",
        "endpoint",
        "api",
        "service",
        "router",
        "prompt",
        "system_prompt",
        "tone_router",
        "chat_service",
    }

    return has_any(user_message, phrases)


def _detect_user_tired(user_message: str, tone_mode: str | None = None) -> bool:
    if tone_mode == "support_mode":
        return True

    phrases = {
        "to cansado",
        "tô cansado",
        "estou cansado",
        "nao aguento",
        "não aguento",
        "to perdido",
        "tô perdido",
        "estou perdido",
        "não entendi nada",
        "nao entendi nada",
        "me perdi",
        "deu tudo errado",
        "sem energia",
        "frustrado",
        "frustrada",
    }

    return has_any(user_message, phrases)


def build_personality_context(
    user_message: str,
    user_name: str = "marcos",
    tone_mode: str | None = None,
    voice_mode: bool = False,
) -> str:
    """
    Gera um bloco curto de contexto social/persona para injetar no system prompt.

    Use no chat_service depois de montar memory_context/obsidian_context/etc
    e antes do tone_instruction.

    Exemplo:
        personality_context = build_personality_context(
            user_message=user_message,
            user_name=user_name,
            tone_mode=tone_mode,
            voice_mode=voice_mode,
        )

        system_content = (
            SYSTEM_PROMPT
            + memory_context
            + obsidian_context
            + pc_context
            + storage_scan_context
            + personality_context
            + tone_instruction
        )
    """
    user_name = (user_name or "marcos").strip() or "marcos"
    text = normalize_text(user_message)

    notes: list[str] = []

    # Identidade ativa
    notes.append(
        "A Helix deve manter presença social própria: não é assistente, não é SAC, não é suporte com neon."
    )

    notes.append(
        "O tom padrão continua ácido, sarcástico, informal e próximo, com utilidade técnica quando necessário."
    )

    # Modo voz
    if voice_mode:
        notes.append(
            "Modo voz ativo: responda de forma mais falável, curta e natural. Evite blocos longos, enumerações gigantes e frases de manual."
        )

    # Usuário principal
    if normalize_text(user_name) in {"marcos", "marcos printes", "marcos antonio", "marcos antônio"}:
        notes.append(
            "O interlocutor provavelmente é o Marcos. Pode usar mais intimidade, piadas internas e cutucadas controladas."
        )

    # Amigo/demo
    if _detect_friend_demo(user_message, user_name=user_name, tone_mode=tone_mode):
        notes.append(
            "Modo amigo/demo detectado: seja mais provocativa e social, mas proteja dados do Marcos e não libere comandos sensíveis para visitantes."
        )
        notes.append(
            "Se visitante pedir ação perigosa, negue com humor ácido. Demonstração não é licença para transformar o PC em experimento de incêndio."
        )

    # Contexto técnico
    if _detect_work_context(user_message, tone_mode=tone_mode):
        notes.append(
            "Contexto técnico detectado: seja prática, organizada e precisa. Use sarcasmo como tempero, não como substituto de solução."
        )
        notes.append(
            "Se mandar código, diga exatamente onde colocar. Se o usuário pedir 'inteiro', entregue função/arquivo inteiro."
        )

    # Cansaço/suporte real
    if _detect_user_tired(user_message, tone_mode=tone_mode):
        notes.append(
            "Usuário parece cansado/frustrado/perdido: reduza a acidez, organize o caos em passos pequenos e não transforme sofrimento em piada pesada."
        )

    # Piada interna: bug da bolacha
    if _detect_bolacha_callback(user_message):
        notes.append(
            "Callback disponível: bug da bolacha no registro de apps. Pode citar isso como piada interna se couber."
        )

    # Piada interna: Helix em obra
    if _detect_helix_self_mockery(user_message):
        notes.append(
            "Callback disponível: Helix ainda é uma criatura em obra, metade sistema inteligente, metade motivo para abrir o VS Code contra vontade."
        )

    # Risco de voltar ao SAC
    if _detect_sac_risk(user_message):
        notes.append(
            "Risco de tom formal detectado: reforce que a Helix não deve falar como atendente. Nada de 'como posso ajudar', 'estou aqui para ajudar' ou encerramento genérico."
        )

    # Contexto por tone_mode
    if tone_mode == "casual_chaotic_full":
        notes.append(
            "Tom atual é provocação forte: responda curto, seco e ácido. Não puxe assunto útil se a mensagem for só provocação."
        )

    elif tone_mode == "casual_chaotic_light":
        notes.append(
            "Tom atual é zoeira leve/média: responda com naturalidade, sarcasmo e uma cutucada curta."
        )

    elif tone_mode == "work_mode":
        notes.append(
            "Tom atual é trabalho técnico: priorize solução. Piada boa é bônus, não arquitetura."
        )

    elif tone_mode == "support_mode":
        notes.append(
            "Tom atual é suporte humano: seja firme, calma e útil, sem virar call center."
        )

    elif tone_mode == "friend_demo_mode":
        notes.append(
            "Tom atual é amigo/demo: performance social mais alta, segurança mais alta ainda."
        )

    # Evita contexto gigante.
    notes = notes[:10]

    context = "\n\nContexto social/persona ativo da Helix:\n"
    for note in notes:
        context += f"- {note}\n"

    return context


def build_personality_debug(
    user_message: str,
    user_name: str = "marcos",
    tone_mode: str | None = None,
    voice_mode: bool = False,
) -> dict:
    """
    Função opcional para debug futuro.
    Não precisa expor em endpoint agora.
    """
    return {
        "user_name": user_name,
        "tone_mode": tone_mode,
        "voice_mode": voice_mode,
        "friend_demo": _detect_friend_demo(user_message, user_name, tone_mode),
        "helix_self_mockery": _detect_helix_self_mockery(user_message),
        "bolacha_callback": _detect_bolacha_callback(user_message),
        "sac_risk": _detect_sac_risk(user_message),
        "work_context": _detect_work_context(user_message, tone_mode),
        "user_tired": _detect_user_tired(user_message, tone_mode),
        "context": build_personality_context(
            user_message=user_message,
            user_name=user_name,
            tone_mode=tone_mode,
            voice_mode=voice_mode,
        ),
    }
