import logging
import uuid
from typing import Any, Callable, List, Optional, Tuple

logger = logging.getLogger(__name__)


class RollbackError(Exception):
    """Raised when one or more rollback operations fail."""

    def __init__(self, message: str, failures: List[Exception]) -> None:
        super().__init__(message)
        self.failures = failures


class Transaction:
    def __init__(self, db_manager: Any) -> None:
        self.db_manager = db_manager
        self.operations: List[Tuple[Callable, Any]] = []
        self.rollback_operations: List[Tuple[Callable, Any]] = []
        self.transaction_id = str(uuid.uuid4())

    async def __aenter__(self) -> "Transaction":
        return self

    async def __aexit__(
        self,
        exc_type: Optional[type],
        exc_val: Optional[BaseException],
        exc_tb: Optional[Any],
    ) -> Optional[bool]:
        if exc_type:
            logger.warning(
                "Exception raised inside transaction context: %s",
                exc_type.__name__,
                exc_info=(exc_type, exc_val, exc_tb),  # type: ignore
                extra={
                    "transaction_id": self.transaction_id,
                    "exception_type": exc_type.__name__,
                },
            )
            await self.rollback()
            return False
        return None

    def add_operation(
        self,
        operation: Callable,
        data: Any,
        *,
        rollback_operation: Optional[Callable] = None,
        rollback_data: Optional[Any] = None,
    ) -> None:
        self.operations.append((operation, data))

        operation_name = getattr(operation, "__name__", str(operation))
        payload_summary = self._describe_payload(data)
        logger.debug(
            "Queued transaction operation %s with payload summary: %s",
            operation_name,
            payload_summary,
        )

        if rollback_operation is not None:
            if rollback_data is None:
                raise ValueError(
                    "rollback_data must be provided when rollback_operation is specified"
                )

            self.rollback_operations.insert(0, (rollback_operation, rollback_data))

    async def commit(self) -> None:
        total_operations = len(self.operations)
        logger.info(
            "Committing transaction with %d operation(s)",
            total_operations,
        )
        current_operation_name: Optional[str] = None
        try:
            for operation, data in self.operations:
                operation_name = getattr(operation, "__name__", str(operation))
                current_operation_name = operation_name
                payload_summary = self._describe_payload(data)
                logger.debug(
                    "Executing transaction operation %s with payload summary: %s",
                    operation_name,
                    payload_summary,
                )
                await operation(data)
        except Exception:
            if current_operation_name is not None:
                logger.exception(
                    "Transaction commit failed while executing operation %s; initiating rollback",
                    current_operation_name,
                    extra={
                        "transaction_id": self.transaction_id,
                        "failed_operation": current_operation_name,
                    },
                )
            else:
                logger.exception(
                    "Transaction commit failed before any operations were executed; initiating rollback",
                    extra={"transaction_id": self.transaction_id},
                )
            await self.rollback()
            raise
        else:
            logger.info(
                "Transaction committed successfully after executing %d operation(s)",
                total_operations,
            )

    async def rollback(self) -> None:
        if not self.rollback_operations:
            logger.info(
                "Rollback requested but no compensating operations were registered"
            )
            return

        total_rollback_operations = len(self.rollback_operations)
        logger.info(
            "Rolling back transaction with %d compensating operation(s)",
            total_rollback_operations,
        )

        exceptions: List[Exception] = []
        for operation, data in self.rollback_operations:
            op_name = getattr(operation, "__name__", str(operation))
            payload_summary = self._describe_payload(data)
            logger.debug(
                "Executing rollback operation %s with payload summary: %s",
                op_name,
                payload_summary,
            )
            try:
                await operation(data)
            except Exception as exc:
                logger.exception("Rollback operation %s failed", op_name)
                exceptions.append(exc)

        if exceptions:
            logger.error(
                "Transaction rollback completed with %d failure(s). The system may be in an inconsistent state.",
                len(exceptions),
                extra={
                    "transaction_id": self.transaction_id,
                    "failure_count": len(exceptions),
                },
            )
            raise RollbackError(
                f"{len(exceptions)} rollback operation(s) failed", exceptions
            )

        logger.info(
            "Transaction rollback completed after executing %d compensating operation(s)",
            total_rollback_operations,
        )

    @staticmethod
    def _describe_payload(data: Any) -> str:
        if data is None:
            return "<none>"

        if hasattr(data, "__len__"):
            try:
                return f"{len(data)} item(s)"
            except Exception:
                return "<unknown size>"

        return data.__class__.__name__
