"""In-process provenance for provider message content, distinct from tool calls."""


class ProviderText(str):
    """Literal provider text must stay text even when it resembles tool JSON.

    A string subclass preserves existing provider/text APIs. Only transport
    extractors create this marker; it is not a field the model can author.
    """
