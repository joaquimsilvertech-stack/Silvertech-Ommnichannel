from __future__ import annotations


class EvolutionAPIError(Exception):
    """Erro base seguro para falhas na integracao com a Evolution API."""

    default_error_code = 'EVOLUTION_REQUEST_ERROR'
    default_retryable = False
    default_message = 'Falha na comunicacao com a Evolution API.'

    def __init__(
        self,
        message: str | None = None,
        *,
        operation: str | None = None,
        status_code: int | None = None,
        error_code: str | None = None,
        retryable: bool | None = None,
    ) -> None:
        super().__init__(message or self.default_message)
        self.operation = operation
        self.status_code = status_code
        self.error_code = error_code or self.default_error_code
        self.retryable = self.default_retryable if retryable is None else retryable


class EvolutionConfigurationError(EvolutionAPIError):
    default_error_code = 'EVOLUTION_CONFIGURATION_ERROR'
    default_message = 'Configuracao invalida da Evolution API.'


class EvolutionAuthenticationError(EvolutionAPIError):
    default_error_code = 'EVOLUTION_AUTHENTICATION_ERROR'
    default_message = 'A Evolution API recusou a autenticacao.'


class EvolutionRateLimitError(EvolutionAPIError):
    default_error_code = 'EVOLUTION_RATE_LIMIT'
    default_retryable = True
    default_message = 'Limite de requisicoes da Evolution API excedido.'


class EvolutionTimeoutError(EvolutionAPIError):
    default_error_code = 'EVOLUTION_TIMEOUT'
    default_retryable = True
    default_message = 'A Evolution API excedeu o tempo limite.'


class EvolutionConnectionError(EvolutionAPIError):
    default_error_code = 'EVOLUTION_CONNECTION_ERROR'
    default_retryable = True
    default_message = 'Nao foi possivel conectar a Evolution API.'


class EvolutionUnavailableError(EvolutionAPIError):
    default_error_code = 'EVOLUTION_UNAVAILABLE'
    default_retryable = True
    default_message = 'A Evolution API esta indisponivel.'


class EvolutionInvalidRequestError(EvolutionAPIError):
    default_error_code = 'EVOLUTION_INVALID_REQUEST'
    default_message = 'A Evolution API recusou a requisicao.'


class EvolutionNotFoundError(EvolutionAPIError):
    default_error_code = 'EVOLUTION_NOT_FOUND'
    default_message = 'O recurso solicitado nao foi encontrado na Evolution API.'


class EvolutionConflictError(EvolutionAPIError):
    default_error_code = 'EVOLUTION_CONFLICT'
    default_message = 'A operacao entrou em conflito na Evolution API.'


class EvolutionInvalidResponseError(EvolutionAPIError):
    default_error_code = 'EVOLUTION_INVALID_RESPONSE'
    default_message = 'A Evolution API retornou uma resposta invalida.'


class EvolutionUnexpectedResponseError(EvolutionAPIError):
    default_error_code = 'EVOLUTION_UNEXPECTED_RESPONSE'
    default_message = 'A Evolution API retornou um status inesperado.'

