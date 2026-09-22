import asyncio

import pytest

pytestmark = pytest.mark.unit

from agentic_inquiry.database.transaction import Transaction


class CustomManager:
    def __init__(self):
        self.operations = []
        self.rollbacks = []

    async def insert_custom_records(self, payload):
        self.operations.append(("insert_custom_records", list(payload)))

    async def insert_and_fail(self, payload):
        self.operations.append(("insert_and_fail", list(payload)))
        raise RuntimeError("insertion failed")

    async def remove_custom_records(self, payload):
        self.rollbacks.append(list(payload))

def test_transaction_commit_with_custom_manager_methods():
    async def run_test():
        manager = CustomManager()
        transaction = Transaction(manager)

        transaction.add_operation(
            manager.insert_custom_records,
            ["row-1"],
            rollback_operation=manager.remove_custom_records,
            rollback_data=["row-1"],
        )

        await transaction.commit()

        assert manager.operations == [("insert_custom_records", ["row-1"])]
        assert manager.rollbacks == []

    asyncio.run(run_test())


def test_transaction_rollback_with_custom_manager_methods():
    async def run_test():
        manager = CustomManager()
        transaction = Transaction(manager)

        transaction.add_operation(
            manager.insert_custom_records,
            ["row-1"],
            rollback_operation=manager.remove_custom_records,
            rollback_data=["row-1"],
        )
        transaction.add_operation(
            manager.insert_and_fail,
            ["row-2"],
            rollback_operation=manager.remove_custom_records,
            rollback_data=["row-2"],
        )

        with pytest.raises(RuntimeError):
            await transaction.commit()

        assert manager.operations == [
            ("insert_custom_records", ["row-1"]),
            ("insert_and_fail", ["row-2"]),
        ]
        # Rollbacks should be executed in reverse order to ensure compensation
        assert manager.rollbacks == [["row-2"], ["row-1"]]

    asyncio.run(run_test())
