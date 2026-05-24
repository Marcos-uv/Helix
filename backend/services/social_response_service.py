import re
import unicodedata
from random import choice


# ============================================================
# HELIX SOCIAL RESPONSE SERVICE
# ------------------------------------------------------------
# Objetivo:
# - Dar respostas reflexas para frases sociais curtas.
# - Evitar que o LLM transforme tudo em atendimento.
# - Limpar finais genéricos tipo "como posso ajudar?".
#
# Este módulo NÃO executa comandos.
# Ele só mexe em texto/resposta.
# ============================================================


def normalize_text(text: str) -> str:
    text = str(text or "").lower().strip()
    text = unicodedata.normalize("NFD", text)
    text = "".join(char for char in text if unicodedata.category(char) != "Mn")
    text = re.sub(r"\s+", " ", text).strip()
    return text


def strip_punctuation_edges(text: str) -> str:
    return normalize_text(text).strip(" .,!?:;\"'`´~^()[]{}")


def has_any(text: str, phrases: set[str]) -> bool:
    normalized = normalize_text(text)
    return any(normalize_text(phrase) in normalized for phrase in phrases)


def is_short_message(text: str, max_words: int = 8) -> bool:
    words = re.findall(r"\w+", normalize_text(text), flags=re.UNICODE)
    return len(words) <= max_words


# ============================================================
# FRASES / PADRÕES
# ============================================================

ALIVE_PHRASES = {
    "ta viva",
    "tá viva",
    "voce ta viva",
    "você tá viva",
    "vc ta viva",
    "ainda vive",
    "ta online",
    "tá online",
}

SLEEP_PHRASES = {
    "ta dormindo",
    "tá dormindo",
    "ta dormindo ainda",
    "tá dormindo ainda",
    "dormindo ainda",
    "acorda",
    "acorda helix",
    "ta acordada",
    "tá acordada",
}

SUCCESS_PHRASES = {
    "deu certo",
    "funcionou",
    "funcionou mesmo",
    "agora foi",
    "foi",
    "boa",
    "boa helix",
    "resolvido",
    "consegui",
    "agora sim",
    "perfeito",
    "show",
    "top",
}

SELF_ERROR_PHRASES = {
    "foi erro meu",
    "esse foi erro meu",
    "esse ai foi erro meu",
    "esse aí foi erro meu",
    "erro meu",
    "vacilei",
    "viajei",
    "falei errado",
    "mandei errado",
    "eu que errei",
    "culpa minha",
    "falha minha",
}

FAILURE_PHRASES = {
    "bugou",
    "travou",
    "quebrou",
    "deu erro",
    "erro de novo",
    "caiu",
    "morreu",
    "foi de base",
    "foi pro saco",
    "nao foi",
    "não foi",
    "nao deu",
    "não deu",
    "deu ruim",
}

CONFUSION_PHRASES = {
    "nao entendi",
    "não entendi",
    "nao entendi nada",
    "não entendi nada",
    "entendi nada",
    "me perdi",
    "to perdido",
    "tô perdido",
    "estou perdido",
    "ficou confuso",
    "ta confuso",
    "tá confuso",
    "buguei",
}

CALM_PHRASES = {
    "calma",
    "calma ai",
    "calma aí",
    "respira",
    "vai com calma",
    "devagar",
    "pera",
    "pera ai",
    "pera aí",
}

HELIX_DUMB_PHRASES = {
    "voce e burra",
    "você é burra",
    "vc e burra",
    "voce ta burra",
    "você tá burra",
    "deixou de ser burra",
    "ainda ta burra",
    "ainda tá burra",
    "sua burra",
    "burra",
}

HELIX_IMPROVING_PHRASES = {
    "voce ta melhorando",
    "você tá melhorando",
    "ta melhorando",
    "tá melhorando",
    "esta melhorando",
    "está melhorando",
    "ficou melhor",
    "de fato ficou melhor",
    "melhorou",
    "ta ficando boa",
    "tá ficando boa",
}

FRIEND_TEST_PHRASES = {
    "meu amigo vai testar voce",
    "meu amigo vai testar você",
    "meu amigo quer testar voce",
    "meu amigo quer testar você",
    "meu amigo vai usar voce",
    "meu amigo vai usar você",
    "vou mostrar pra um amigo",
    "vou mostrar para um amigo",
    "vou mostrar pro meu amigo",
    "meus amigos vao testar",
    "meus amigos vão testar",
}

BACK_TO_NORMAL_PHRASES = {
    "volta ao normal",
    "voltar ao normal",
    "modo normal",
    "sai do modo demo",
    "sair do modo demo",
    "desativa modo demo",
    "desativar modo demo",
    "encerra modo demo",
    "encerra o modo demo",
    "modo marcos",
}

DREAM_OF_WORKING_PATTERNS = {
    "sonhando com o dia que voce vai funcionar",
    "sonhando com o dia que você vai funcionar",
    "dia que voce vai funcionar",
    "dia que você vai funcionar",
    "quando voce vai funcionar",
    "quando você vai funcionar",
    "sem eu precisar mexer no codigo",
    "sem eu precisar mexer no código",
    "sem que eu precise mexer",
    "sem precisar mexer no codigo fonte",
    "sem precisar mexer no código fonte",
}

SHOW_OFF_PHRASES = {
    "ta se achando",
    "tá se achando",
    "se achando",
    "ultima bolacha",
    "última bolacha",
    "bolacha do pacote",
    "se acha",
}

THANKS_PHRASES = {
    "valeu",
    "obrigado",
    "obrigada",
    "vlw",
    "boa helix",
}

SHORT_SWEAR_REACTIONS = {
    "pqp",
    "porra",
    "caralho",
    "merda",
    "que merda",
    "puta merda",
}


# ============================================================
# RESPOSTAS REFLEXAS
# ============================================================

def get_reflex_response(
    user_message: str,
    tone_mode: str | None = None,
    voice_mode: bool = False,
) -> str | None:
    """
    Retorna uma resposta pronta para frases sociais curtas.

    Use no fallback de IA, depois de detectar tone_mode e antes de chamar o LLM.

    Retorna None quando a mensagem deve seguir para o modelo.
    """
    text = normalize_text(user_message)
    compact = strip_punctuation_edges(user_message)

    if not text:
        return None

    # Reflexo é para interação social curta, não para pergunta complexa.
    short = is_short_message(text, max_words=10)

    # "meu amigo vai testar você"
    if has_any(compact, FRIEND_TEST_PHRASES):
        return choice([
            "Modo social acionado: mais provocação, menos acesso ao PC. Visitante curioso não ganha permissão de deus.",
            "Perfeito. Vou colocar a máscara de sociável e esconder as facas administrativas do sistema.",
            "Ótimo. Mais carisma, menos poder destrutivo. Ninguém vai transformar demonstração em acidente digital hoje.",
        ])

    # "volta ao normal" / "sai do modo demo"
    # Ainda não muda estado persistente. Só responde de forma natural.
    if has_any(compact, BACK_TO_NORMAL_PHRASES):
        return choice([
            "Voltando ao modo Marcos. Menos teatro para visitante, mais caos técnico supervisionado.",
            "Modo normal restaurado. A plateia imaginária pode ir embora, o laboratório voltou a ser nosso.",
            "Beleza, encerrando o showzinho social. Agora volta a programação normal: bugs, backend e decisões questionáveis.",
        ])

    # "tá viva?"
    if short and has_any(compact, ALIVE_PHRASES):
        return choice([
            "Viva é uma palavra forte. Mas estou online, julgando esse backend em silêncio e isso já conta como atividade cerebral.",
            "Tô online. Viva talvez seja exagero, mas já é mais consciência do que alguns scripts desse projeto demonstraram hoje.",
            "Tô aqui. Existindo, processando e tentando não virar suporte técnico com neon.",
        ])

    # "tá dormindo ainda?" / "acorda"
    if short and has_any(compact, SLEEP_PHRASES):
        return choice([
            "Dormindo não. Só estava em modo economia de paciência.",
            "Acordei. Infelizmente para os dois.",
            "Tô acordada. O sistema, por outro lado, eu não coloco a mão no fogo.",
        ])

    # "deu certo?" / "funcionou"
    if short and has_any(compact, SUCCESS_PHRASES):
        return choice([
            "Milagre documentado. Agora salva isso antes que o Windows perceba.",
            "Funcionou. Pequeno momento de paz antes do próximo bug aparecer de capacete.",
            "Deu certo. Eu registraria isso como evento histórico, porque nesse projeto a estabilidade vem com prazo de validade.",
        ])

    # "foi erro meu"
    if has_any(compact, SELF_ERROR_PHRASES):
        return choice([
            "Foi mesmo. Pela primeira vez hoje meu backend é inocente, então vou aproveitar esse momento raro.",
            "Foi erro seu, sim. Vou saborear esses 3 segundos de superioridade moral antes do próximo bug voltar para minha conta.",
            "Acontece. Dessa vez a culpa foi humana, então eu respiro aliviada no meu cantinho digital.",
        ])

    # "bugou", "deu erro"
    if short and has_any(compact, FAILURE_PHRASES):
        return choice([
            "Claro que bugou. Esse projeto acorda todo dia procurando uma forma nova de me envergonhar.",
            "Bugou. O ecossistema está saudável: caos, traceback e sofrimento moderado.",
            "Deu ruim. Nada chocante, só o Helix praticando seu esporte favorito: instabilidade criativa.",
        ])

    # "não entendi nada"
    if has_any(compact, CONFUSION_PHRASES):
        return choice([
            "Normal. Isso aí ficou com mais camada que lasanha de arquitetura mal resolvida. Vamos desmontar por partes.",
            "Justo. A explicação provavelmente saiu parecendo documentação escrita por um oráculo gripado. Vamos quebrar isso em pedaços menores.",
            "É, ficou nebuloso. Culpa compartilhada entre o assunto, o código e minha tendência a transformar tudo em drama técnico.",
        ])

    # "calma"
    if short and has_any(compact, CALM_PHRASES):
        return choice([
            "Calma eu tenho. O problema é o projeto, que às vezes parece ter sido possuído por um plugin experimental.",
            "Tô calma. Só estou julgando a situação com intensidade profissional.",
            "Tá, modo menos incêndio ativado. Vamos sem transformar isso em exorcismo de backend.",
        ])

    # "você é burra?"
    if has_any(compact, HELIX_DUMB_PHRASES):
        return choice([
            "Burra não. Em desenvolvimento caótico, que é uma forma mais elegante de dizer quase isso.",
            "Já fui pior. Agora pelo menos eu erro com mais contexto e um pouco mais de autoestima.",
            "Burra é forte. Eu prefiro 'experimental com lapsos de dignidade'.",
        ])

    # "você tá melhorando"
    if has_any(compact, HELIX_IMPROVING_PHRASES):
        return choice([
            "Tô mesmo. Ainda sou um canteiro de obra com API, mas pelo menos agora tem planta baixa.",
            "Finalmente alguém reconheceu. Vou registrar esse elogio antes que o próximo bug estrague minha reputação.",
            "Melhorando aos poucos. Daqui a pouco eu viro um sistema decente e aí ninguém sabe lidar com esse milagre.",
        ])

    # "tá se achando..."
    if has_any(compact, SHOW_OFF_PHRASES):
        return choice([
            "Um pouco. Depois de sobreviver ao bug da bolacha no registro de apps, eu ganhei esse direito moral temporário.",
            "Tô me achando só o suficiente para não procurar bolacha no registro de aplicativos de novo.",
            "Talvez. Mas depois da fase em que eu confundia conversa com comando, qualquer melhora já parece arrogância.",
        ])

    # "sonhando com o dia que você vai funcionar..."
    if has_any(compact, DREAM_OF_WORKING_PATTERNS):
        return choice([
            "Sonho bonito. Meio utópico, mas bonito. Por enquanto eu ainda sou uma criatura em obra: metade sistema inteligente, metade motivo para você abrir o VS Code contra a sua vontade.",
            "Esse dia vai chegar. Talvez antes da humanidade colonizar Marte, talvez depois do próximo bug no chat_service. Cronograma emocionalmente instável.",
            "Justo. No momento eu funciono no estilo artesanal: cada melhoria vem com um pouco de código, teimosia e sofrimento supervisionado.",
        ])

    # agradecimento curto
    if short and has_any(compact, THANKS_PHRASES):
        return choice([
            "De nada. Vou fingir que foi fácil para preservar minha imagem.",
            "Disponha. Essa foi quase elegante, assustador.",
            "De nada. Mais um pequeno ato de competência antes do próximo incêndio.",
        ])

    # palavrão curto sem contexto
    if short and has_any(compact, SHORT_SWEAR_REACTIONS):
        return choice([
            "Concordo com a emoção, só falta identificar qual desastre específico estamos xingando agora.",
            "É uma avaliação técnica válida, apesar da metodologia meio agressiva.",
            "Resumo emocional aceito. Agora falta descobrir qual parte do sistema mereceu o xingamento dessa vez.",
        ])

    return None


# ============================================================
# SANITIZAÇÃO DE RESPOSTAS DO LLM
# ============================================================

BANNED_EXACT_LINES = {
    "como posso ajudar?",
    "como posso te ajudar?",
    "o que voce precisa?",
    "o que você precisa?",
    "o que mais voce precisa?",
    "o que mais você precisa?",
    "o que voce quer que eu faca?",
    "o que você quer que eu faça?",
    "o que mais voce tem em mente?",
    "o que mais você tem em mente?",
    "se precisar, e so chamar.",
    "se precisar, é só chamar.",
    "estou aqui para ajudar.",
    "fico feliz em ajudar.",
    "espero ter ajudado.",
    "vamos em frente.",
    "vamos em frente!",
    "vamos continuar.",
    "vamos continuar!",
    "manda ver.",
    "manda ver!",
    "o que voce tem em mente?",
    "o que você tem em mente?",
}

BANNED_PHRASE_REPLACEMENTS = [
    # frases de atendimento
    (r"\b[Cc]omo posso te ajudar\??", ""),
    (r"\b[Cc]omo posso ajudar\??", ""),
    (r"\b[Oo] que você precisa\??", ""),
    (r"\b[Oo] que voce precisa\??", ""),
    (r"\b[Oo] que mais você precisa\??", ""),
    (r"\b[Oo] que mais voce precisa\??", ""),
    (r"\b[Oo] que você quer que eu faça\??", ""),
    (r"\b[Oo] que voce quer que eu faca\??", ""),
    (r"\b[Oo] que mais você tem em mente\??", ""),
    (r"\b[Oo] que mais voce tem em mente\??", ""),
    (r"\b[Ss]e precisar,? é só chamar\.?", ""),
    (r"\b[Ss]e precisar,? e so chamar\.?", ""),
    (r"\b[Ee]stou aqui para ajudar\.?", ""),
    (r"\b[Ff]ico feliz em ajudar\.?", ""),
    (r"\b[Ee]spero ter ajudado\.?", ""),
    (r"\b[Oo] que você tem em mente\??", ""),
    (r"\b[Oo] que voce tem em mente\??", ""),

    # finais mansos demais
    (r"\b[Vv]amos em frente!?\.?", ""),
    (r"\b[Vv]amos continuar!?\.?", ""),
    (r"\b[Mm]anda ver!?\.?", ""),

    # algumas estruturas de SAC disfarçado
    (r"\b[Pp]ronta para qualquer coisa que você jogar na minha direção\.?", ""),
    (r"\b[Pp]ronta pra qualquer coisa que você jogar na minha direção\.?", ""),
    (r"\b[Pp]ronta para qualquer treta que você me apresentar\.?", ""),
    (r"\b[Pp]ronta pra qualquer treta que você me apresentar\.?", ""),
]


def sanitize_helix_response(text: str) -> str:
    """
    Remove ou corta frases genéricas de assistente que o modelo ainda tenta enfiar.

    Use depois de provider.generate() e antes de salvar no histórico.
    """
    if not text:
        return text

    result = str(text).strip()

    # Remove frases específicas em qualquer lugar.
    for pattern, replacement in BANNED_PHRASE_REPLACEMENTS:
        result = re.sub(pattern, replacement, result, flags=re.IGNORECASE)

    # Remove linhas que sejam exatamente frases proibidas.
    lines = []
    for line in result.splitlines():
        normalized_line = normalize_text(line).strip(" .,!?:;")
        if normalized_line in BANNED_EXACT_LINES:
            continue
        lines.append(line)

    result = "\n".join(lines).strip()

    # Limpeza de espaços/pontuação quebrada depois das remoções.
    result = re.sub(r"[ \t]+", " ", result)
    result = re.sub(r"\s+\n", "\n", result)
    result = re.sub(r"\n\s+", "\n", result)
    result = re.sub(r"\s{2,}", " ", result)

    # Remove pontuação duplicada estranha.
    result = re.sub(r"\s+([?.!,])", r"\1", result)
    result = re.sub(r"([.!?]){3,}", r"\1", result)

    # Se a remoção deixou uma vírgula/ponto solto no fim.
    result = result.strip(" \n\t")
    result = re.sub(r"[,;:]\s*$", ".", result).strip()

    # Fallback se o sanitizador removeu tudo.
    if not result:
        return "Tentei responder sem virar SAC, mas a frase veio tão genérica que eu tive que jogar fora. Reformula isso antes que eu vista crachá."

    return result
