from exceptions.exception import AIDocumentIntelligenceError
from logger.logger import DocumentIntelligenceLogger

logger_manager = DocumentIntelligenceLogger()
logger = logger_manager.get_logger()


def calculate_payment():
    try:
        amount = 100
        result = amount / 0

    except Exception as error:
        raise AIDocumentIntelligenceError(
            "Payment calculation failed",
            error_details=error,
        ) from error


try:
    calculate_payment()

except AIDocumentIntelligenceError as error:

    logger.error(
        str(error),
        **error.log_fields(),
    )

finally:
    logger_manager.close()